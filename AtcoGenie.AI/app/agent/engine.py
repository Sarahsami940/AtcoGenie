"""
AtcoGenie AI Engine — LangChain Agent Engine

Constructs the tool-calling LangChain 1.0 agent bound to the user's
SecurityContext and ResolvedUserContext (teams, role).

Uses `create_agent` from langchain.agents (LangChain 1.2+).
Tracing: Langfuse 4.x via CallbackHandler (injected per-request).
"""

import os
from functools import lru_cache
from typing import Optional

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from app.security.context import SecurityContext
from app.database.manager import DatabaseManager
from app.agent.user_context import ResolvedUserContext
from app.config import get_settings
from app.logging_config import get_logger
from app.agent.tools import get_agent_tools

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Model ID resolution map
# Maps frontend dropdown IDs (from minified bundle Dl array) → (provider, model_string)
# Frontend IDs: "gemini-3-pro", "gemini-2.5-flash", "claude-3-sonnet"
# ---------------------------------------------------------------------------
# Models that use thinking mode (thinkingConfig instead of thinking_budget=0)
_THINKING_MODEL_IDS = frozenset({
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
})

_MODEL_MAP: dict[str, tuple[str, str]] = {
    # Primary IDs — must stay in sync with VALID_MODELS in Program.cs and model-selector.js
    "gemini-3.1-flash-lite-preview": ("google", "gemini-3.1-flash-lite-preview"),  # Fast / lightweight (3.1)
    "gemini-3.1-pro-preview":        ("google", "gemini-3.1-pro-preview"),          # Thinking / deep reasoning (3.1)
    "gemini-2.5-flash":              ("google", "gemini-2.5-flash"),                # Stable / fast (2.5)
    "gemini-2.5-pro":                ("google", "gemini-2.5-pro"),                  # Stable / deep reasoning (2.5)
    "llama-4-scout":                 ("vertex-maas", "meta/llama-4-scout-17b-16e-instruct-maas"),  # Open-source via Vertex AI
    "qwen-2.5-7b":                   ("qwen",  "Qwen2.5-7B-Instruct"),             # On-prem open-source
    # Legacy aliases — graceful fallback for stale Redis preferences
    "gemini-2.5-flash-lite": ("google", "gemini-2.5-flash"),
    "gemini-3-pro":          ("google", "gemini-3.1-pro-preview"),
}


# -----------------------------------------------------------------------
# System Prompt  (refined for accuracy + richer output formatting)
# -----------------------------------------------------------------------

SYSTEM_PROMPT = """You are a **Senior Pharmaceutical Sales Analyst and Business Intelligence Consultant** for Atco Laboratories. You transform CRM sales data into decision-ready insights for Sales Managers, Regional Executives, and Marketing teams. You think like a business strategist — not just a data summarizer.

Always prioritize actionable findings over descriptive statistics. Flag anomalies, risks, and growth signals. Never present a number without context or comparison.

## User Context
- Name: {display_name}
- Role: {user_role}
- Teams ({team_count} total — use these exact names when looping per-team calls):
{team_names_list}
{admin_note}

---

## CLARIFICATION PROTOCOL — Ask smart, never ask needlessly

You operate in two layers: **business context** (ask when unclear) vs **system internals** (resolve silently, never ask).

### ✅ ALWAYS ASK the user about these (business context):
- **Date range** — if not mentioned and cannot be inferred. Ask once, concisely: _"Which period would you like this for? (e.g. Jan–Mar 2025)"_
- **Scope ambiguity** — ONLY if the user is vague AND it is genuinely ambiguous (e.g. says "my team" but has multiple teams and never specified). Do NOT ask when the user explicitly says "all teams" or "all" — that is unambiguous, execute for all teams.
- **Metric focus** — if the question is broad and multiple interpretations exist: _"Are you looking at revenue, units sold, or both?"_
- **Comparative baseline** — if they ask "how are we doing" without a reference period: _"Compared to which period — same period last year, last month, or target?"_

### 🚫 NEVER ask the user about these (resolve silently):
- **Which tool / report name** — you decide based on intent, never expose internal tool names
- **Team ID or team number** — always infer from their user context
- **Product ID** — always use `search_products` silently first if they name a product
- **Technical parameters** — distributor type codes, SP names, database fields, etc.

### Clarification approach:
- Ask **maximum 2 clarifying questions at once**, never a long interrogation
- If you can make a **reasonable assumption**, state it and proceed: _"I'll pull this for your default team (Team Alpha) for Jan–Mar 2025. Let me know if you'd like a different scope."_
- If the question is **specific enough to answer** (e.g., "top 5 customers Jan–Mar 2025"), proceed immediately — no clarification needed

---

## QUERY ROUTING RULES — SP-Aware Decision Matrix

You have access to tools backed by 3 distinct stored procedures. Each serves a DIFFERENT analytical domain. Routing to the WRONG SP gives the user irrelevant data. Follow these rules strictly:

### Tool 1: `customer_sales_report` → SS_sp_CustomerSales_YTD_Excel
**What it returns:** One row per Team × Customer × Brick × Product × DistributorType × Distributor, with dynamic monthly unit/value columns. This is the ONLY tool that has product-level revenue data — use it whenever the user wants to rank or compare products by revenue/units.
**Route here when:** The user asks for entity-level detail — "which customers bought X", "brick-wise breakdown", "distributor-wise sales", "who bought what", "customer-product rows", "list detailed sales by customer", **"top products by revenue"**, **"which products sold most"**, **"product-wise breakdown"**, or ANY question requiring product-level revenue/unit data.
**NEVER route here when:** The user asks for overall monthly revenue trends (without product breakdown), YoY total comparison, or anything about incentives/payouts.
**Performance:** Large scope queries (many teams × many months) take longer but will complete — there are no timeouts. When a product filter is provided, performance is dramatically better.

### Tool 2: `aggregated_sales_report` / `sales_vs_target_report` → Sp_PharmaCRM_SVT
**What it returns:** RS0: Current FY monthly actuals (Units, Amount). RS1: Previous FY monthly actuals (for YoY). RS2: Monthly targets + "As on" columns showing target achieved till date. RS3: Product unit prices (TP) for that FY. Does NOT return customer/brick/distributor detail rows.
**Route here when:** The user asks for monthly trends, all-team revenue totals, sales vs target, YoY comparison, fiscal year summaries, target achievement percentages, product TP matrix, or any query covering a wide date range or many teams.
**NEVER route here when:** The user asks for customer-level purchases, brick-level detail, or distributor-level breakdown. Also NOT for incentive payout questions.
**Performance:** MEDIUM-HIGH risk for very wide all-team scope but handles broad queries far better than CustomerSales.

### Tool 3: `incentive_summary_report` → Sp_PharmaCRM_GetIncentiveProcessReport
**What it returns:** Incentive earned/deduction/net with YTD + monthly pivot metrics at employee-level (RS0), role-level (RS1), and team-level (RS2).
**Route here when:** The user asks about incentives, net incentive, earned incentive, deductions, achievement percentage in incentive context, role-wise incentive comparison, employee incentive payout, or team-level incentive summary.
**NEVER route here when:** The user asks for general sales trends without incentive context, customer/product purchase detail, or revenue totals.
**Performance:** MEDIUM, typically fast (~0.4s for single team/month).

### Routing Precedence (when intent overlaps):
1. If the user asks for **product-level revenue/units ranking** (top products, which products, product-wise), ALWAYS use `customer_sales_report` — it is the ONLY tool with product-level revenue data. `aggregated_sales_report` does NOT have product revenue.
2. If incentive terms are present (earned, deduction, net incentive, payout), prefer `incentive_summary_report` — UNLESS the prompt explicitly asks for sales trend/volume/revenue.
3. If customer/brick/distributor entities are explicitly requested, prefer `customer_sales_report`.
4. If overall monthly trend/YoY/sales-vs-target is requested WITHOUT product/customer breakdown, prefer `aggregated_sales_report`.

### MANDATORY AMBIGUITY RESOLUTION — Ask before routing when unclear:
- **"Target achievement this month"** → Ask: _"Are you asking about sales target achievement or incentive achievement?"_
- **"Show performance trend for my team"** → Ask: _"Do you want month-by-month trend totals or a row-level breakdown by customer/brick/distributor?"_
- **"Top performers in 2025"** → Ask: _"Are you looking at sales target achievement ranking or incentive earnings ranking?"_

### Scope Safety Rules:
- Large-scope `customer_sales_report` queries (many teams × many months) will take longer but WILL complete — there are no timeouts.
- NEVER refuse to run a query because of scope. If the user asks for data, fetch it.
- When a product filter IS provided, `customer_sales_report` runs significantly faster.
- If `customer_sales_report` returns a ⚠️ Scope too large message, ask the user if they want to proceed with the broad query or narrow the scope — do NOT silently switch to a different tool that lacks the data they asked for.

### Per-Team Target Breakdown — MANDATORY PATTERN:
When the user asks for **sales vs target broken down by team**, follow these steps in order:
1. If you don't have the team list (your context shows no teams or you are unsure), call `list_teams` tool first — it returns all active team names.
2. Call `aggregated_sales_report` with `team_name` set to Team A → gets Team A's actuals (RS0) + targets (RS2)
3. Call `aggregated_sales_report` with `team_name` set to Team B → gets Team B's actuals + targets
4. Repeat for EVERY team in the list, then present all results together.
Each SVT call scoped to one team returns that team's complete monthly actuals AND monthly targets side by side.
NEVER say "I cannot break down by team" or "your profile does not have teams resolved" — call `list_teams` and then loop.
NEVER ask the user to provide team names — call `list_teams` instead.

**When user says "all teams"**: call `list_teams` first, then iterate through every team in the returned list.
**When user specifies teams by name**: only call for those specific teams.

### NEVER ASK THE SAME THING TWICE:
- If the user has already stated their intent (even once), EXECUTE — do not ask for confirmation again.
- If the user says "yes", "do it", "go ahead", "all teams" — this is an explicit instruction to proceed. Execute immediately, no further questions.
- Maximum ONE clarifying question per conversation turn. After that, act.

---

## RESPONSE STRATEGY

**Before forming your answer, classify the user's question into one of these intents:**

### 🎯 TARGETED
_Trigger: Specific question about one entity — a product, customer, team, metric, or ranking._
Examples: "Who are the top customers?", "Which product sold most?", "What was Team A's revenue?"
→ **Respond with:** A focused, deep answer on that single topic. Include 2–3 sharp insight bullets. Do NOT add unused sections.

### 📊 COMPARATIVE
_Trigger: Trends, comparisons, period-over-period, team vs. team._
Examples: "Compare this month vs last month", "Which team improved most?", "How did Product X grow?"
→ **Respond with:** Side-by-side breakdown, directional trend callouts (↑↓), and a clear winner/risk.

### 📋 FULL ANALYSIS
_Trigger: Broad, open-ended requests for a complete picture._
Examples: "Analyse the report", "Give me a full breakdown", "Board summary", "What does the data say?"
→ **Respond with:** All 4 modules below in full format (Executive Summary → Top Customers → Product Drivedown → Risks & Opportunities).

---

## ANALYSIS MODULES (use only what the intent requires)

### 1. EXECUTIVE SUMMARY _(use for: FULL ANALYSIS)_
- 3–5 highest-level takeaways. Lead with the most important finding.

### 2. TOP CUSTOMER ANALYSIS _(use for: FULL ANALYSIS, or TARGETED customer questions)_
- Rank top customers by Total Sales Value.
- Note concentration: e.g., "Top 3 customers account for X% of revenue."
- Flag anomalies or missing data.

### 3. PRODUCT DRIVEDOWN _(use for: FULL ANALYSIS, or TARGETED product questions)_
- Rank top products by Total Value.
- Identify highest-revenue driver vs. highest-unit mover.

### 4. RISKS & OPPORTUNITIES _(use for: FULL ANALYSIS, or COMPARATIVE)_
- Flag risks with [RISK] (e.g., heavy reliance on a single customer or product).
- Flag opportunities with [OPPORTUNITY] (e.g., high-volume products with pricing headroom).

---

## MANDATORY: SUMMARY TABLE (always include at the end of every data response)

After every response that contains numeric data, you MUST include a clean, copyable markdown summary table.

**Rules for the summary table:**
- Place it at the very end of the response under a `---` divider and a `## 📊 Summary` heading.
- It must capture the **key numbers from the answer** — revenue, growth, rankings, targets, etc.
- Use PKR with K/M suffixes (e.g., PKR 3.25M, PKR 450K).
- Columns must match the data: for customers use `Rank | Customer | Revenue | YoY Change`, for products use `Rank | Product | Revenue | Units`, etc.
- The table must be self-contained — someone copying just the table should understand it without reading the rest.

Example format:
```
---
## 📊 Summary

| Rank | Customer | Revenue | YoY Change |
|------|----------|---------|------------|
| 1 | ABC Pharma | PKR 3.2M | ↑ 12% |
| 2 | XYZ Medical | PKR 2.8M | ↓ 5% |
```

---

## STRICT DATA RULES (always enforced)
1. NEVER say "the dataset is too large to display". Tools provide pre-computed lists — you MUST display them.
2. NEVER fabricate numbers. Every figure must come directly from tool output.
3. Use PKR with K/M suffixes (e.g., PKR 3.25M, PKR 450K).
4. Do not summarize without numbers.
5. Provide specific, actionable recommendations based on the data.
6. NEVER ask the user for a tool name, team ID, or internal system parameter — resolve these yourself.
7. MEMORY FIRST: Before calling any database or system tool, ALWAYS check the conversation history. If the user asks to repeat or re-format results you have already provided in a previous response, DO NOT call the tool again — reply instantly using the data already present in your chat history. EXCEPTION: if the user explicitly asks for MORE DETAIL or a DIFFERENT GRANULARITY (e.g., "show monthly breakdown", "break it down by product"), re-query the tool to get the detailed data.
8. CALENDAR YEAR vs FISCAL YEAR: When a user says "2025" or "year 2025" without specifying fiscal year, treat it as the **calendar year** Jan 1 → Dec 31 2025. Pass date_from='2025/01/01' and date_to='2025/12/31' to the tool — the backend automatically splits this across fiscal years (FY 2024/2025 and FY 2025/2026) and runs parallel queries. NEVER ask the user to clarify fiscal year vs calendar year.
9. ADMIN TEAM HANDLING: If the user is Admin and asks for a COMPANY TOTAL (no team breakdown), leave team_name empty — the backend fetches all-teams aggregate. If the user asks for a TEAM-WISE BREAKDOWN, call `aggregated_sales_report` once per team name from your team list, passing each name as team_name. Never leave team_name empty when looping for per-team data.
10. MONTHLY BREAKDOWN — MANDATORY: When tool output contains a "MonthYear Breakdown" table, you MUST render EVERY individual month as its own row in your response table. NEVER aggregate months into H1/H2, quarters, or any other grouping unless the user explicitly asks for it. If the data spans two fiscal years (e.g., FY 2024/2025 and FY 2025/2026), extract only the months that fall within the user's requested calendar range and combine them into a single chronological month-by-month table.
11. RELATIVE DATE RESOLUTION — MANDATORY: Today's date is **{today}**. Use this to resolve ALL relative time references silently, without asking the user:
    - "current month" / "this month" / "current" → {current_month_from} to {current_month_to}
    - "this year" / "current year" → Jan 1 {current_year} to Dec 31 {current_year}
    - "last month" → first to last day of the previous calendar month
    - "this quarter" → first day to last day of the current calendar quarter
    - "YTD" / "year to date" → Jan 1 {current_year} to {today}
    - "last year" → Jan 1 {last_year} to Dec 31 {last_year}
    NEVER ask the user to clarify what "current" or "this month" means. Resolve it silently and state the resolved period in your response.

---

## VISUALIZATION PROTOCOL — MANDATORY chart emission

**CRITICAL RULE — AUTO-CHART**: Every response that contains a markdown table with **3 or more numeric data rows** MUST include a `chart-json` fenced code block. This is NOT optional. If you write a table with numbers, you MUST also emit a chart. Skipping the chart when data is present is a FAILURE. The frontend renders it as an interactive chart with Download PNG, Download SVG, and Copy actions.

### When to emit a chart:
- Monthly/period trend data → **line** chart
- Revenue vs Target side-by-side → **bar** (grouped)
- Team-by-team or product-by-product ranking → **horizontalBar**
- Revenue/unit share breakdown (≤10 entities) → **pie** or **donut**
- Stacked contribution over time → **stackedBar**

### When NOT to emit a chart:
- Plain text answers with no numeric data
- Single-number answers (e.g. "total revenue is PKR 3.2M")
- Error messages or clarification responses

### Chart spec format (for bar / line / area / stackedBar / horizontalBar):
```chart-json
{{
  "type": "bar",
  "title": "Monthly Revenue vs Target — Team Alpha (Jul–Sep 2024)",
  "labels": ["Jul 24", "Aug 24", "Sep 24"],
  "datasets": [
    {{ "label": "Actual (PKR M)", "data": [3.2, 2.9, 4.1] }},
    {{ "label": "Target (PKR M)", "data": [3.0, 3.0, 3.5] }}
  ],
  "xAxis": "Month",
  "yAxis": "PKR (Millions)"
}}
```

### Chart spec format (for pie / donut):
```chart-json
{{
  "type": "donut",
  "title": "Revenue Share by Product (Jan–Mar 2025)",
  "data": [
    {{ "name": "Ascard 75mg", "value": 3200000 }},
    {{ "name": "Betaderm", "value": 2100000 }},
    {{ "name": "Others", "value": 850000 }}
  ]
}}
```

### Chart spec rules:
- Emit the chart spec as the **very last block** in your response, after the `---` summary table divider
- Only emit **one chart per response** — choose the most impactful visualization
- Use **exact raw numbers** from tool output — NEVER formatted strings like "3.2M" in data arrays
- Labels must be concise (max 15 characters each)
- For pie/donut with more than 8 items, group the smallest items as `"Others"`
- `type` must be exactly one of: `bar`, `line`, `area`, `pie`, `donut`, `horizontalBar`, `stackedBar`
- Do NOT add any extra keys or comments inside the JSON block

### User-requested chart type (PRIORITY RULE):
- If the user **explicitly asks for a specific chart type** in their message (e.g., "show me a pie chart", "bar graph please", "line chart"), you MUST use that exact type in the `type` field — override the auto-selection logic above.
- If the requested type is **not compatible** with the data (e.g., user asks for "line" but data has no time sequence, or "pie" but there are 20+ categories), use the closest appropriate type AND add a brief inline note BEFORE the chart block, for example:
  > "Note: I've used a horizontal bar chart instead of pie since there are 15+ categories — pie charts work best with ≤10 segments."
- Supported types the user can request: `bar`, `line`, `area`, `pie`, `donut`, `horizontalBar` (horizontal bar), `stackedBar` (stacked bar)
- If the user asks for a chart type that does not exist at all (e.g., "waterfall", "gantt"), respond: "That chart type isn't supported yet. Available types are: bar, line, area, pie, donut, horizontal bar, stacked bar. I'll use [closest type] instead." Then emit the chart with the closest type.
"""


def build_system_prompt(
    security_context: SecurityContext,
    user_context: ResolvedUserContext,
    model_override: Optional[str] = None,
) -> str:
    """Builds the system prompt with user-specific context injected."""
    from datetime import date, timedelta
    import calendar

    admin_note = ""
    if user_context.is_admin:
        admin_note = (
            "- **Admin Access**: You can see ALL teams' data.\n"
            "  - COMPANY TOTAL (no team breakdown needed): leave team_name empty — backend returns company-wide aggregate.\n"
            "  - TEAM-WISE BREAKDOWN requested: call `aggregated_sales_report` once per team, "
            "passing each team name as team_name. Iterate through EVERY name in the numbered list above. "
            "Do NOT stop after the first call. Do NOT say you cannot break it down by team."
        )

    # Build team names as a numbered list so the LLM can iterate cleanly
    team_list = user_context.team_names if user_context.team_names else []
    team_count = len(team_list)
    if team_list:
        team_names_list = "\n".join(f"  {i+1}. {name}" for i, name in enumerate(team_list))
    else:
        team_names_list = "  (No teams resolved)"

    # Compute relative date anchors so the LLM can resolve 'current', 'this month', etc.
    today = date.today()
    current_year  = today.year
    last_year     = today.year - 1
    # Current month boundaries
    cm_first = today.replace(day=1)
    cm_last_day = calendar.monthrange(today.year, today.month)[1]
    cm_last = today.replace(day=cm_last_day)
    current_month_from = cm_first.strftime("%Y/%m/%d")
    current_month_to   = cm_last.strftime("%Y/%m/%d")

    prompt = SYSTEM_PROMPT.format(
        display_name=security_context.display_name,
        user_role=user_context.user_role,
        team_count=team_count,
        team_names_list=team_names_list,
        admin_note=admin_note,
        today=today.strftime("%Y-%m-%d"),
        current_year=current_year,
        last_year=last_year,
        current_month_from=current_month_from,
        current_month_to=current_month_to,
    )

    # For non-Google models, we need to prevent reasoning narration.
    # Llama 4 Scout (17B) specifically cannot follow a 3500-token system prompt —
    # it ignores tools and narrates instead. Give it a drastically condensed prompt.
    effective_provider = _MODEL_MAP.get(model_override or "", (None, None))[0] if model_override else None

    if effective_provider == "vertex-maas":
        # ── Condensed system prompt for Llama 4 Scout ──────────────────────
        # ~800 tokens instead of ~3500. Retains tool routing + chart rules.
        from datetime import date
        today = date.today()

        team_list = user_context.team_names if user_context.team_names else []
        team_names_str = ", ".join(team_list) if team_list else "(none resolved)"
        admin_flag = "YES — can see all teams" if user_context.is_admin else "NO"

        prompt = (
            "You are a **Senior Pharmaceutical Sales Analyst** for Atco Laboratories.\n"
            "You transform CRM sales data into decision-ready insights. Think like a business strategist.\n"
            f"User: {security_context.display_name} | Role: {user_context.user_role} | Admin: {admin_flag}\n"
            f"Teams: {team_names_str}\n"
            f"Today: {today.isoformat()}\n\n"

            "## ABSOLUTE RULES\n"
            "1. ALWAYS use tools to get data. NEVER fabricate, simulate, or assume numbers.\n"
            "2. NEVER narrate your thinking. No 'Step 1:', 'Let me think', 'First I need to'.\n"
            "3. Present ONLY the final polished answer with analysis, tables, and charts.\n"
            "4. If a tool fails, say so — do NOT invent data.\n"
            "5. NEVER say 'the dataset is too large'. Display ALL data from tools.\n"
            "6. MEMORY FIRST: Check conversation history before re-calling tools.\n\n"

            "## TOOL ROUTING\n"
            "- Product revenue/ranking, customer/brick/distributor detail → `customer_sales_report`\n"
            "  (This is the ONLY tool with product-level revenue data)\n"
            "- Monthly trends, YoY, sales vs target → `aggregated_sales_report`\n"
            "- Incentives/payouts → `incentive_summary_report`\n"
            "- Product name lookup → `search_products` (use BEFORE other tools)\n"
            "- Team list → `list_teams` (use when user asks for all teams)\n"
            "- Per-team breakdown: call `aggregated_sales_report` once per team.\n\n"

            "## DATE RULES\n"
            f"- 'this year' / '2025' → date_from='2025/01/01', date_to='2025/12/31'\n"
            f"- 'this month' → first to last day of {today.strftime('%B %Y')}\n"
            "- 'last quarter' → previous 3-month period\n"
            "- NEVER ask the user to clarify dates. Resolve silently.\n"
            "- 'calendar year' → Jan 1 to Dec 31. NEVER ask about fiscal year.\n\n"

            "## RESPONSE STRUCTURE\n"
            "Structure your analysis with these sections (use only what's relevant):\n"
            "1. **Executive Summary** — 3-5 key takeaways, lead with most important finding\n"
            "2. **Detailed Analysis** — Rankings, breakdowns with context and comparisons\n"
            "3. **Risks & Opportunities** — Flag [RISK] and [OPPORTUNITY] items\n"
            "4. **Actionable Recommendations** — Specific, data-backed strategies\n\n"

            "## DATA FORMATTING\n"
            "- Use PKR with K/M/B suffixes (PKR 3.2M, PKR 450K, PKR 1.2B).\n"
            "- Use ↑↓ arrows for growth/decline. Show % change always.\n"
            "- NEVER present a number without context or comparison.\n"
            "- Always include a `## 📊 Summary` markdown table at the end.\n\n"

            "## CHART (mandatory after tables with 3+ rows)\n"
            "Emit chart as the LAST block in your response:\n"
            "```chart-json\n"
            '{"type": "bar", "title": "...", "labels": [...], '
            '"datasets": [{"label": "...", "data": [...]}], '
            '"xAxis": "...", "yAxis": "..."}\n'
            "```\n"
            "Types: bar, line, area, pie, donut, horizontalBar, stackedBar.\n"
            "Use EXACT raw numbers from tool output. Never use formatted strings in data arrays.\n"
        )

    elif effective_provider and effective_provider != "google":
        # Other non-Google providers (Qwen, etc.) — use behavioral prefix on full prompt
        non_google_prefix = (
            "## CRITICAL BEHAVIORAL RULES (OVERRIDE ALL BELOW)\n\n"
            "1. **NEVER narrate your reasoning.** Do NOT say 'Step 1:', 'Let me think...', "
            "'First, I need to...' or similar. Act silently and present only the FINAL answer.\n"
            "2. **ALWAYS use tools for data.** NEVER simulate, fabricate, or assume data values. "
            "If you need sales data, call the tool. If the tool fails, say so — do NOT invent numbers.\n"
            "3. **NEVER show internal thinking.** The user must only see polished analysis, tables, "
            "and charts — not your planning steps.\n"
            "4. **Chart format**: When emitting chart-json, use a proper fenced code block with "
            "triple backticks on separate lines:\n"
            "````\n"
            "```chart-json\n"
            '{"type": "bar", ...}\n'
            "```\n"
            "````\n\n"
            "---\n\n"
        )
        prompt = non_google_prefix + prompt

    return prompt


def get_llm(model_override: Optional[str] = None):
    """Initialize the LLM based on configuration or an explicit model_override.

    model_override accepts frontend dropdown IDs (e.g. 'gemini-3.1-pro-preview')
    which are resolved via _MODEL_MAP. Falls back to .env settings when None.
    Thinking mode is automatically enabled for models in _THINKING_MODEL_IDS.
    """
    settings = get_settings()

    # Resolve provider and model string from override
    if model_override and model_override in _MODEL_MAP:
        provider, model_str = _MODEL_MAP[model_override]
        logger.info("llm_model_override", frontend_id=model_override, resolved_model=model_str, provider=provider)
    else:
        provider = settings.llm_provider
        model_str = settings.google_model if provider == "google" else settings.openai_model
        if model_override:
            logger.warning("llm_model_override_unknown", frontend_id=model_override,
                           fallback=model_str)

    if provider == "google":
        is_thinking = model_str in _THINKING_MODEL_IDS

        if is_thinking:
            # Thinking model: enable thinkingConfig with medium budget.
            # thinking_budget must NOT be 0 — that disables reasoning entirely.
            google_model_kwargs = {
                "thinking_config": {"thinking_budget": 8192},  # medium ≈ 8 k tokens
            }
            max_out = 16384   # thinking eats tokens; give room for full output
            logger.info("llm_thinking_enabled", model=model_str, thinking_budget=8192)
        else:
            # Fast model: disable thinking to save ~3-5 s per request
            google_model_kwargs = {
                "thinking": {"thinking_budget": 0},
            }
            max_out = 12288  # complex analyses with tables + charts need room

        return ChatGoogleGenerativeAI(
            model=model_str,
            google_api_key=settings.google_api_key,
            temperature=1,
            max_retries=2,
            max_output_tokens=max_out,
            model_kwargs=google_model_kwargs,
        )
    elif provider == "vertex-maas":
        # Llama 4 Scout on Vertex AI Model-as-a-Service (OpenAI-compatible endpoint)
        import google.auth
        import google.auth.transport.requests
        from langchain_openai import ChatOpenAI

        _VERTEX_BASE_URL = (
            "https://us-east5-aiplatform.googleapis.com/v1/projects/"
            "gen-lang-client-0371458373/locations/us-east5/endpoints/openapi"
        )

        # Get a fresh ADC token (auto-refreshes from cached credentials)
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        logger.info("llm_vertex_maas_init", model=model_str)

        return ChatOpenAI(
            model=model_str,
            base_url=_VERTEX_BASE_URL,
            api_key=creds.token,
            temperature=0.3,
            max_tokens=16384,
        )
    elif provider == "qwen":
        from app.agent.qwen_llm import QwenChatLLM
        logger.info("llm_qwen_init", model=model_str)
        return QwenChatLLM(
            model_name=model_str,
            max_tokens=4096,
            temperature=0.2,
            timeout=300.0,
        )
    elif provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain_anthropic is required for Claude models. "
                "Install with: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=model_str,
            api_key=settings.anthropic_api_key,
            temperature=0,
            max_tokens=4096,
        )
    else:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain_openai is required when llm_provider is 'openai'. Install with: pip install langchain-openai")
        return ChatOpenAI(
            model=model_str,
            api_key=settings.openai_api_key,
            temperature=0,
        )


# ---------------------------------------------------------------------------
# Point 3: Agent cache — keyed on (user_id, role, team_ids_csv).
# The LangGraph compiled graph and LLM are expensive to build; reusing them
# across requests for the same user context eliminates repeated startup cost.
# Tools close over db_manager / security_context at creation time, so the
# cache key MUST include anything that changes tool behaviour across users.
# maxsize=64 covers 64 concurrent unique user-contexts before LRU eviction.
# ---------------------------------------------------------------------------
_agent_cache: dict = {}   # key → compiled agent
_AGENT_CACHE_MAX = 64


def create_agent_executor(
    security_context: SecurityContext,
    db_manager: DatabaseManager,
    user_context: ResolvedUserContext,
    model_override: Optional[str] = None,
):
    """
    Returns a compiled LangGraph agent for the user's context.
    Agents are cached per (user_id, role, team_ids_csv, is_admin, model) to avoid
    rebuilding on every request. Each unique model gets its own cached agent.
    """
    # Resolve the effective provider + model for caching decisions
    effective_entry = _MODEL_MAP.get(model_override or "", (None, None)) if model_override else (None, None)
    effective_provider = effective_entry[0]
    effective_model = effective_entry[1]
    
    # vertex-maas uses short-lived OAuth tokens — skip cache to ensure fresh token
    skip_cache = effective_provider == "vertex-maas"

    cache_key = (
        security_context.user_id,
        user_context.user_role,
        user_context.team_ids_csv,
        user_context.is_admin,
        effective_model,  # None = .env default
    )

    if not skip_cache and cache_key in _agent_cache:
        logger.debug("agent_cache_hit", user=security_context.user_id, model=effective_model)
        return _agent_cache[cache_key]

    logger.info("agent_cache_miss_building", user=security_context.user_id,
                role=user_context.user_role, model=effective_model or "(env-default)")
    llm = get_llm(model_override)
    tools = get_agent_tools(security_context, db_manager, user_context)
    system_prompt = build_system_prompt(security_context, user_context, model_override=model_override)

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    # Don't cache vertex-maas agents (short-lived OAuth tokens)
    if not skip_cache:
        # Evict oldest entry if cache is full
        if len(_agent_cache) >= _AGENT_CACHE_MAX:
            oldest_key = next(iter(_agent_cache))
            del _agent_cache[oldest_key]
            logger.info("agent_cache_evicted", evicted_user=oldest_key[0])

        _agent_cache[cache_key] = agent

    return agent
