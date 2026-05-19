"""
AtcoGenie AI Engine — Multi-Turn Context Resolver

Resolves vague references in follow-up messages using the session context.
Lightweight approach: extracts entities from tool results and injects them
as a context preamble into the system prompt.

Handles:
- Pronoun references: "it", "that product", "this team", "them"
- Implicit continuations: "show me more", "break it down", "compare with last month"
- Entity carryover: previously mentioned teams, products, date ranges
"""

import re
from app.cache.session_context import SessionContext
from app.logging_config import get_logger

logger = get_logger(__name__)

# Patterns that indicate the user is referencing prior context
_REFERENCE_PATTERNS = [
    r"\b(it|its|that|those|these|this|them|the same|above|previous)\b",
    r"\b(show me more|more detail|break it down|drill down|expand|elaborate)\b",
    r"\b(compare with|compare to|versus|vs\.?)\b",
    r"\b(same (team|product|period|month|quarter|year))\b",
    r"\b(again|repeat|redo|re-run)\b",
]
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _REFERENCE_PATTERNS]


def has_vague_references(message: str) -> bool:
    """Returns True if the message contains pronouns or references to prior context."""
    return any(p.search(message) for p in _COMPILED_PATTERNS)


def build_context_preamble(ctx: SessionContext) -> str:
    """
    Builds a concise context preamble from the session state.
    Injected as a system message before the user's current message.
    """
    parts = []

    if ctx.last_intent:
        parts.append(f"- Previous intent: {ctx.last_intent}")

    if ctx.last_target_system:
        parts.append(f"- Last tool used: {ctx.last_target_system}")

    entities = ctx.resolved_entities
    if entities:
        if entities.get("teams"):
            parts.append(f"- Teams discussed: {', '.join(entities['teams'])}")
        if entities.get("products"):
            parts.append(f"- Products discussed: {', '.join(entities['products'])}")
        if entities.get("date_range"):
            parts.append(f"- Date range: {entities['date_range']}")
        if entities.get("customers"):
            parts.append(f"- Customers discussed: {', '.join(entities['customers'][:5])}")

    if not parts:
        return ""

    return (
        "## Previous Conversation Context\n"
        "The user may reference items from their previous question. Here is the context:\n"
        + "\n".join(parts)
        + "\n\nUse this context to resolve vague references like 'it', 'that team', 'same product', etc. "
        "If the reference is clear, proceed silently. If ambiguous, ask for clarification.\n"
    )


def extract_entities_from_tool_calls(messages: list) -> dict:
    """
    Scans the agent's tool call arguments from the response messages
    to extract entities (team names, products, date ranges) for context carryover.
    """
    entities: dict = {}

    for msg in messages:
        # LangChain tool-call messages have tool_calls attribute
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.get("args", {})

                # Extract team name
                if "team_name" in args and args["team_name"]:
                    entities.setdefault("teams", [])
                    tn = args["team_name"]
                    if tn not in entities["teams"]:
                        entities["teams"].append(tn)

                # Extract product
                if "product_name" in args and args["product_name"]:
                    entities.setdefault("products", [])
                    pn = args["product_name"]
                    if pn not in entities["products"]:
                        entities["products"].append(pn)

                # Extract date range
                if "date_from" in args and "date_to" in args:
                    entities["date_range"] = f"{args['date_from']} to {args['date_to']}"

    return entities


def infer_intent(message: str) -> str:
    """
    Classify the user's intent from their message text.
    Returns a short label for context tracking.
    """
    msg_lower = message.lower()

    if any(kw in msg_lower for kw in ["incentive", "payout", "deduction", "earned"]):
        return "incentive_analysis"
    if any(kw in msg_lower for kw in ["target", "vs target", "achievement"]):
        return "sales_vs_target"
    if any(kw in msg_lower for kw in ["trend", "month", "yoy", "year over year", "growth"]):
        return "trend_analysis"
    if any(kw in msg_lower for kw in ["customer", "brick", "distributor"]):
        return "customer_analysis"
    if any(kw in msg_lower for kw in ["product", "brand", "ranking", "top"]):
        return "product_analysis"
    if any(kw in msg_lower for kw in ["team", "compare team", "all teams"]):
        return "team_comparison"
    if any(kw in msg_lower for kw in ["upload", "excel", "file", "dataset"]):
        return "data_upload_analysis"

    return "general_query"


def infer_target_system(message: str) -> str:
    """Infer which tool the query will likely route to."""
    intent = infer_intent(message)
    mapping = {
        "incentive_analysis": "incentive_summary_report",
        "sales_vs_target": "aggregated_sales_report",
        "trend_analysis": "aggregated_sales_report",
        "customer_analysis": "customer_sales_report",
        "product_analysis": "customer_sales_report",
        "team_comparison": "aggregated_sales_report",
        "data_upload_analysis": "query_user_dataset",
    }
    return mapping.get(intent, "")
