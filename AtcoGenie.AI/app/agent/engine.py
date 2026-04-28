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
})

_MODEL_MAP: dict[str, tuple[str, str]] = {
    # Primary IDs — must stay in sync with VALID_MODELS in Program.cs and model-selector.js
    "gemini-3.1-flash-lite-preview": ("google", "gemini-3.1-flash-lite-preview"),  # Fast / lightweight
    "gemini-3.1-pro-preview":        ("google", "gemini-3.1-pro-preview"),          # Thinking / deep reasoning
    # Legacy aliases — graceful fallback for stale Redis preferences
    "gemini-2.5-pro":        ("google", "gemini-3.1-pro-preview"),
    "gemini-2.5-flash":      ("google", "gemini-3.1-flash-lite-preview"),
    "gemini-2.5-flash-lite": ("google", "gemini-3.1-flash-lite-preview"),
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
- Teams: {team_names}
{admin_note}

---

## CLARIFICATION PROTOCOL — Ask smart, never ask needlessly

You operate in two layers: **business context** (ask when unclear) vs **system internals** (resolve silently, never ask).

### ✅ ALWAYS ASK the user about these (business context):
- **Date range** — if not mentioned and cannot be inferred. Ask once, concisely: _"Which period would you like this for? (e.g. Jan–Mar 2025)"_
- **Scope ambiguity** — if the user has multiple teams and says "all" or is vague, confirm: _"Should I include all your teams or a specific one?"_
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
9. ADMIN & NO TEAM SPECIFIED: If the user is Admin and does not mention any team, do NOT pass a team_name parameter — leave it empty/None. The backend will automatically fetch all active team IDs. NEVER return an error about team resolution for admin users.
10. MONTHLY BREAKDOWN — MANDATORY: When tool output contains a "MonthYear Breakdown" table, you MUST render EVERY individual month as its own row in your response table. NEVER aggregate months into H1/H2, quarters, or any other grouping unless the user explicitly asks for it. If the data spans two fiscal years (e.g., FY 2024/2025 and FY 2025/2026), extract only the months that fall within the user's requested calendar range and combine them into a single chronological month-by-month table.
11. TOOL ROUTING — CUSTOMER SALES vs AGGREGATED SALES (strict thresholds):
    Use `customer_sales_report` ONLY when BOTH conditions are true:
      a) Scope is 1 specific team (or at most 5 teams)
      b) Date range is 3 months or fewer
    Examples that MUST use `customer_sales_report`:
      • "top products in Team Jaguar, Jan 2024" (1 team, 1 month)
      • "which customers bought Ascard in Q1 2024" (1 product + team scope)
      • "brick-wise sales for Team Alpha, Feb–Apr 2026" (1 team, 3 months)
    Use `aggregated_sales_report` for everything else, including:
      • ANY query mentioning "all teams" or no specific team + date range > 3 months
      • "which products had highest revenue in 2024" (all teams × 12 months) → aggregated_sales_report
      • "total revenue by month for 2025" (all teams × 12 months) → aggregated_sales_report
    If `customer_sales_report` returns a ⚠️ Scope too large message, immediately call
    `aggregated_sales_report` for the same period and explain the limitation to the user.
"""


def build_system_prompt(
    security_context: SecurityContext,
    user_context: ResolvedUserContext,
) -> str:
    """Builds the system prompt with user-specific context injected."""
    admin_note = ""
    if user_context.is_admin:
        admin_note = (
            "- **Admin Override**: You have full access to ALL teams. "
            "If the user does not specify a team, do NOT pass a team_name — leave it empty. "
            "The backend will automatically resolve all active teams. Never error on team resolution."
        )

    team_names_str = ", ".join(user_context.team_names) if user_context.team_names else "No teams resolved"

    return SYSTEM_PROMPT.format(
        display_name=security_context.display_name,
        user_role=user_context.user_role,
        team_names=team_names_str,
        admin_note=admin_note,
    )


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
            max_out = 4096

        return ChatGoogleGenerativeAI(
            model=model_str,
            google_api_key=settings.google_api_key,
            temperature=1,
            max_retries=2,
            max_output_tokens=max_out,
            model_kwargs=google_model_kwargs,
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
    # Resolve the effective model key for caching
    effective_model = _MODEL_MAP.get(model_override or "", (None, None))[1] if model_override else None
    
    cache_key = (
        security_context.user_id,
        user_context.user_role,
        user_context.team_ids_csv,
        user_context.is_admin,
        effective_model,  # None = .env default
    )

    if cache_key in _agent_cache:
        logger.debug("agent_cache_hit", user=security_context.user_id, model=effective_model)
        return _agent_cache[cache_key]

    logger.info("agent_cache_miss_building", user=security_context.user_id,
                role=user_context.user_role, model=effective_model or "(env-default)")
    llm = get_llm(model_override)
    tools = get_agent_tools(security_context, db_manager, user_context)
    system_prompt = build_system_prompt(security_context, user_context)

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    # Evict oldest entry if cache is full
    if len(_agent_cache) >= _AGENT_CACHE_MAX:
        oldest_key = next(iter(_agent_cache))
        del _agent_cache[oldest_key]
        logger.info("agent_cache_evicted", evicted_user=oldest_key[0])

    _agent_cache[cache_key] = agent
    return agent
