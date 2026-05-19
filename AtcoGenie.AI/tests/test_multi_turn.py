"""
Tests for multi-turn conversation features:
- Context carryover (entity extraction + session context persistence)
- Reference resolution (pronouns, vague follow-ups)
- Summarization trigger logic
"""

import pytest
from app.cache.session_context import SessionContext, SessionContextCache
from app.agent.context_resolver import (
    has_vague_references,
    build_context_preamble,
    extract_entities_from_tool_calls,
    infer_intent,
    infer_target_system,
)
from app.agent.summarizer import (
    needs_summarization,
    inject_summary_into_messages,
    build_summarization_prompt,
    SUMMARIZE_THRESHOLD,
    KEEP_RECENT,
)


# === Context Resolver Tests ===

class TestVagueReferences:
    """Test detection of pronouns and vague follow-up patterns."""

    def test_detects_pronoun_it(self):
        assert has_vague_references("Show me more about it")

    def test_detects_pronoun_that(self):
        assert has_vague_references("What about that product?")

    def test_detects_show_me_more(self):
        assert has_vague_references("Show me more detail")

    def test_detects_break_it_down(self):
        assert has_vague_references("Break it down by month")

    def test_detects_drill_down(self):
        assert has_vague_references("Drill down into the numbers")

    def test_detects_same_team(self):
        assert has_vague_references("Do the same for the same team")

    def test_detects_compare_with(self):
        assert has_vague_references("Compare with last quarter")

    def test_detects_repeat(self):
        assert has_vague_references("Do that again")

    def test_no_false_positive_on_specific_query(self):
        assert not has_vague_references("Show me Team Alpha sales for January 2025")

    def test_no_false_positive_on_greeting(self):
        assert not has_vague_references("Hello, good morning")


class TestContextPreamble:
    """Test context preamble generation from session state."""

    def test_empty_context_returns_empty(self):
        ctx = SessionContext()
        assert build_context_preamble(ctx) == ""

    def test_builds_preamble_with_teams(self):
        ctx = SessionContext(
            last_intent="team_comparison",
            last_target_system="aggregated_sales_report",
            resolved_entities={"teams": ["Team Alpha", "Team Beta"]},
        )
        preamble = build_context_preamble(ctx)
        assert "Team Alpha" in preamble
        assert "Team Beta" in preamble
        assert "team_comparison" in preamble

    def test_builds_preamble_with_products(self):
        ctx = SessionContext(
            resolved_entities={"products": ["Ascard 75mg", "Betaderm"]},
        )
        preamble = build_context_preamble(ctx)
        assert "Ascard 75mg" in preamble

    def test_builds_preamble_with_date_range(self):
        ctx = SessionContext(
            resolved_entities={"date_range": "2025/01/01 to 2025/03/31"},
        )
        preamble = build_context_preamble(ctx)
        assert "2025/01/01 to 2025/03/31" in preamble

    def test_builds_preamble_with_all_fields(self):
        ctx = SessionContext(
            last_intent="product_analysis",
            last_target_system="customer_sales_report",
            resolved_entities={
                "teams": ["Team Alpha"],
                "products": ["Ascard 75mg"],
                "date_range": "2025/01/01 to 2025/03/31",
                "customers": ["ABC Pharma", "XYZ Medical"],
            },
        )
        preamble = build_context_preamble(ctx)
        assert "Previous Conversation Context" in preamble
        assert "Team Alpha" in preamble
        assert "Ascard 75mg" in preamble
        assert "ABC Pharma" in preamble


class TestEntityExtraction:
    """Test entity extraction from tool call arguments."""

    def test_extracts_team_name(self):
        # Simulate a LangChain AIMessage with tool_calls
        class FakeMessage:
            tool_calls = [{"args": {"team_name": "Team Alpha", "date_from": "2025/01/01", "date_to": "2025/03/31"}}]

        entities = extract_entities_from_tool_calls([FakeMessage()])
        assert entities["teams"] == ["Team Alpha"]
        assert entities["date_range"] == "2025/01/01 to 2025/03/31"

    def test_extracts_product_name(self):
        class FakeMessage:
            tool_calls = [{"args": {"product_name": "Ascard 75mg"}}]

        entities = extract_entities_from_tool_calls([FakeMessage()])
        assert entities["products"] == ["Ascard 75mg"]

    def test_deduplicates_teams(self):
        class FakeMessage:
            tool_calls = [
                {"args": {"team_name": "Team Alpha"}},
                {"args": {"team_name": "Team Alpha"}},
                {"args": {"team_name": "Team Beta"}},
            ]

        entities = extract_entities_from_tool_calls([FakeMessage()])
        assert entities["teams"] == ["Team Alpha", "Team Beta"]

    def test_skips_messages_without_tool_calls(self):
        class FakeMessage:
            pass  # no tool_calls attribute

        entities = extract_entities_from_tool_calls([FakeMessage()])
        assert entities == {}

    def test_handles_empty_tool_calls(self):
        class FakeMessage:
            tool_calls = []

        entities = extract_entities_from_tool_calls([FakeMessage()])
        assert entities == {}


class TestIntentClassification:
    """Test user intent classification."""

    def test_incentive_intent(self):
        assert infer_intent("Show me incentive earnings for Team Alpha") == "incentive_analysis"

    def test_target_intent(self):
        assert infer_intent("What's the target achievement?") == "sales_vs_target"

    def test_trend_intent(self):
        assert infer_intent("Show monthly trends for 2025") == "trend_analysis"

    def test_customer_intent(self):
        assert infer_intent("Top customers in Lahore brick") == "customer_analysis"

    def test_product_intent(self):
        assert infer_intent("Which product sold the most?") == "product_analysis"

    def test_team_intent(self):
        assert infer_intent("Compare all teams") == "team_comparison"

    def test_upload_intent(self):
        assert infer_intent("Analyze the uploaded excel file") == "data_upload_analysis"

    def test_general_intent(self):
        assert infer_intent("Hello, how are you?") == "general_query"


class TestTargetSystemInference:
    """Test that intent maps to the correct tool."""

    def test_incentive_routes_correctly(self):
        assert infer_target_system("Show me net incentive") == "incentive_summary_report"

    def test_trend_routes_correctly(self):
        assert infer_target_system("Monthly revenue trends") == "aggregated_sales_report"

    def test_customer_routes_correctly(self):
        assert infer_target_system("Top customers this quarter") == "customer_sales_report"

    def test_upload_routes_correctly(self):
        assert infer_target_system("Query the uploaded dataset") == "query_user_dataset"


# === Session Context Tests ===

class TestSessionContext:
    """Test SessionContext serialization."""

    def test_roundtrip(self):
        ctx = SessionContext(
            last_intent="product_analysis",
            last_target_system="customer_sales_report",
            resolved_entities={"teams": ["Alpha"], "products": ["Ascard"]},
            message_count=5,
            summary="User asked about Ascard sales.",
        )
        data = ctx.to_dict()
        restored = SessionContext.from_dict(data)

        assert restored.last_intent == "product_analysis"
        assert restored.last_target_system == "customer_sales_report"
        assert restored.resolved_entities["teams"] == ["Alpha"]
        assert restored.message_count == 5
        assert restored.summary == "User asked about Ascard sales."

    def test_empty_context(self):
        ctx = SessionContext()
        assert ctx.last_intent == ""
        assert ctx.resolved_entities == {}
        assert ctx.message_count == 0

    def test_from_dict_handles_missing_keys(self):
        ctx = SessionContext.from_dict({"last_intent": "test"})
        assert ctx.last_intent == "test"
        assert ctx.message_count == 0
        assert ctx.resolved_entities == {}


# === Summarization Tests ===

class TestSummarization:
    """Test summarization trigger and message injection."""

    def test_needs_summarization_below_threshold(self):
        assert not needs_summarization(5)
        assert not needs_summarization(19)

    def test_needs_summarization_at_threshold(self):
        assert needs_summarization(20)
        assert needs_summarization(30)

    def test_inject_summary_with_no_summary(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        result = inject_summary_into_messages(messages, "")
        assert result == messages  # unchanged

    def test_inject_summary_replaces_old_messages(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(12)]
        result = inject_summary_into_messages(messages, "Summary of older turns.")

        # Should have 1 summary system message + KEEP_RECENT messages
        assert len(result) == KEEP_RECENT + 1
        assert result[0]["role"] == "system"
        assert "Summary of older turns" in result[0]["content"]
        # Recent messages preserved
        assert result[-1]["content"] == "msg 11"

    def test_inject_summary_short_conversation_unchanged(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(4)]
        result = inject_summary_into_messages(messages, "Some summary")
        assert result == messages  # too short to summarize

    def test_build_summarization_prompt(self):
        messages = [
            {"role": "user", "content": "What are the top products?"},
            {"role": "assistant", "content": "Ascard 75mg leads with PKR 3.2M revenue."},
            {"role": "user", "content": "And the bottom performers?"},
            {"role": "assistant", "content": "Product X has the lowest at PKR 50K."},
            {"role": "user", "content": "msg5"},
            {"role": "assistant", "content": "msg6"},
            {"role": "user", "content": "msg7"},
            {"role": "assistant", "content": "msg8"},
            {"role": "user", "content": "msg9"},
            {"role": "assistant", "content": "msg10"},
        ]
        prompt = build_summarization_prompt(messages)
        assert "CONVERSATION TO SUMMARIZE" in prompt
        assert "top products" in prompt
        assert "Ascard 75mg" in prompt

    def test_build_summarization_prompt_short_conversation_empty(self):
        messages = [{"role": "user", "content": "hi"}]
        prompt = build_summarization_prompt(messages)
        assert prompt == ""
