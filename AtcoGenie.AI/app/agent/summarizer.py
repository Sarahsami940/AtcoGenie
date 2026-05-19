"""
AtcoGenie AI Engine — Conversation Summarization

Summarizes earlier conversation turns when the message count exceeds
a threshold, preserving key findings while freeing token budget.

Architecture:
- Triggered after every turn when message_count > SUMMARIZE_THRESHOLD
- Replaces older messages with a concise summary paragraph
- The summary is stored in Redis SessionContext and injected as a system message
- Recent messages (last 6) are always kept verbatim
"""

from app.logging_config import get_logger

logger = get_logger(__name__)

SUMMARIZE_THRESHOLD = 20  # trigger after 20 messages (10 full turns)
KEEP_RECENT = 6           # always keep the last 6 messages verbatim


def needs_summarization(message_count: int) -> bool:
    """Check if the conversation has grown enough to warrant summarization."""
    return message_count >= SUMMARIZE_THRESHOLD


def build_summarization_prompt(messages: list[dict]) -> str:
    """
    Build a prompt that asks the LLM to summarize older conversation context.
    Only the messages BEFORE the recent window are summarized.
    """
    # Split into old (to summarize) and recent (to keep)
    if len(messages) <= KEEP_RECENT:
        return ""

    old_messages = messages[:-KEEP_RECENT]

    # Build a transcript of the old messages
    transcript_parts = []
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate very long messages for the summarization input
        if len(content) > 1500:
            content = content[:1500] + "..."
        transcript_parts.append(f"[{role.upper()}]: {content}")

    transcript = "\n\n".join(transcript_parts)

    return (
        "Summarize the following conversation history into a concise paragraph. "
        "Preserve:\n"
        "- Key data findings (specific numbers, rankings, trends mentioned)\n"
        "- Entities discussed (team names, product names, date ranges, customers)\n"
        "- Any decisions or conclusions reached\n"
        "- The user's analytical goals and preferences\n\n"
        "Do NOT include greetings, confirmations, or tool execution details.\n"
        "Keep the summary under 300 words.\n\n"
        "--- CONVERSATION TO SUMMARIZE ---\n"
        f"{transcript}\n"
        "--- END ---\n\n"
        "Summary:"
    )


def inject_summary_into_messages(
    messages: list[dict],
    summary: str,
) -> list[dict]:
    """
    Replace older messages with a summary + keep recent messages verbatim.
    Returns a new message list ready for the agent.
    """
    if not summary or len(messages) <= KEEP_RECENT:
        return messages

    recent = messages[-KEEP_RECENT:]

    # Inject summary as a system message before recent messages
    summary_msg = {
        "role": "system",
        "content": (
            "## Conversation Summary (earlier turns)\n"
            f"{summary}\n\n"
            "Use this summary as context for the user's current question. "
            "The detailed messages from recent turns follow below."
        ),
    }

    return [summary_msg] + recent
