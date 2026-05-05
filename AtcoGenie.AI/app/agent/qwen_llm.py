"""
QwenChatLLM — LangChain BaseChatModel wrapper for the on-prem Qwen 2.5-7B-Instruct API.

The Qwen server exposes a custom /chat and /chat/stream API (NOT OpenAI-compatible).
This wrapper translates LangChain's message protocol into Qwen's HTTP API and implements
prompt-based tool calling via <tool_call> tags as documented in the API guide.

Tool Calling Strategy:
  LangChain's create_agent uses bind_tools() to inject tool schemas. For models that
  don't support native function calling, we inject tool descriptions into the system
  prompt and parse <tool_call> XML tags from the model output. The parsed calls are
  returned as AIMessage.tool_calls so LangChain's agent loop handles them natively.
"""

import json
import re
from typing import Any, List, Optional, Iterator

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from app.logging_config import get_logger

logger = get_logger(__name__)

# Regex for parsing <tool_call>...</tool_call> from Qwen output
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE
)

# Default Qwen server URL (on-prem)
QWEN_BASE_URL = "http://10.10.35.88:8005"


def _parse_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from <tool_call> tags in model output.
    Returns list of dicts: [{"name": str, "arguments": dict, "id": str}]
    """
    calls = []
    for i, m in enumerate(_TOOL_CALL_RE.finditer(text)):
        raw = m.group(1).strip()
        # Strip code fences if the model wrapped it
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("qwen_tool_call_parse_failed", raw=raw[:200])
            continue
        name = body.get("name")
        args = body.get("arguments") or body.get("args") or {}
        if isinstance(name, str) and isinstance(args, dict):
            calls.append({
                "name": name,
                "args": args,
                "id": f"qwen_call_{i}",
            })
    return calls


def _build_tool_directive(tools: list[dict]) -> str:
    """Builds the tool-use instruction block to append to the system prompt."""
    if not tools:
        return ""

    tool_lines = []
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        params = t.get("parameters", {}).get("properties", {})
        param_names = ", ".join(params.keys()) if params else ""
        tool_lines.append(f"- {name}({param_names}): {desc[:150]}")

    return (
        "\n\n--- TOOL USE ---\n"
        "You have these tools available:\n"
        + "\n".join(tool_lines)
        + "\n\n"
        "When you need to call a tool, respond with ONLY this exact format and nothing else:\n"
        "<tool_call>\n"
        '{"name": "<tool_name>", "arguments": {<args as JSON>}}\n'
        "</tool_call>\n\n"
        "Do not say you cannot access data — you have these tools. Use them.\n"
        "To answer the user directly without a tool, respond with plain text.\n"
        "Exactly ONE tool per response.\n"
        "--- END TOOL USE ---\n"
    )


def _messages_to_qwen(messages: List[BaseMessage], tool_schemas: list[dict]) -> list[dict]:
    """Convert LangChain messages → Qwen /chat message format.
    Injects tool directive into the system message if tools are bound.
    """
    tool_directive = _build_tool_directive(tool_schemas)
    result = []
    system_injected = False

    for msg in messages:
        if isinstance(msg, SystemMessage):
            content = msg.content
            if tool_directive and not system_injected:
                content = content + tool_directive
                system_injected = True
            result.append({"role": "system", "content": content})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, ToolMessage):
            # Feed tool results back as a user message (Qwen pattern)
            result.append({
                "role": "user",
                "content": f"Tool {msg.name} returned: {msg.content}",
            })
        else:
            result.append({"role": "user", "content": str(msg.content)})

    # If no system message existed, prepend one with tool directive
    if tool_directive and not system_injected:
        result.insert(0, {"role": "system", "content": tool_directive})

    return result


class QwenChatLLM(BaseChatModel):
    """LangChain BaseChatModel that calls the on-prem Qwen 2.5-7B API."""

    model_name: str = "Qwen2.5-7B-Instruct"
    base_url: str = Field(default=QWEN_BASE_URL)
    max_tokens: int = 4096
    temperature: float = 0.2
    top_p: float = 0.9
    timeout: float = 300.0
    _tool_schemas: list[dict] = []

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "qwen-chat"

    @property
    def _identifying_params(self) -> dict:
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    def bind_tools(self, tools: list, **kwargs) -> "QwenChatLLM":
        """Bind tool schemas so they get injected into the system prompt.
        Returns a new instance with the tools bound (immutable pattern).
        """
        schemas = []
        for t in tools:
            if hasattr(t, "get_input_schema"):
                schema = t.get_input_schema().schema() if hasattr(t.get_input_schema(), "schema") else {}
            else:
                schema = {}
            schemas.append({
                "name": getattr(t, "name", str(t)),
                "description": getattr(t, "description", ""),
                "parameters": schema,
            })
        # Create a copy with tools bound
        new_instance = self.model_copy()
        new_instance._tool_schemas = schemas
        return new_instance

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation via POST /chat."""
        qwen_messages = _messages_to_qwen(messages, self._tool_schemas)

        payload = {
            "messages": qwen_messages,
            "max_tokens": self.max_tokens,
            "temperature": max(self.temperature, 0.01),  # Qwen deadlocks on exactly 0
            "top_p": self.top_p,
        }

        try:
            resp = httpx.post(
                f"{self.base_url}/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
        except httpx.HTTPStatusError as e:
            logger.error("qwen_api_error", status=e.response.status_code, body=e.response.text[:300])
            raise
        except Exception as e:
            logger.error("qwen_request_failed", error=str(e))
            raise

        # Parse tool calls from output
        tool_calls = _parse_tool_calls(text)
        if tool_calls:
            # Strip the tool_call tags from visible content
            clean_text = _TOOL_CALL_RE.sub("", text).strip()
            ai_msg = AIMessage(
                content=clean_text,
                tool_calls=tool_calls,
            )
        else:
            ai_msg = AIMessage(content=text)

        generation = ChatGeneration(message=ai_msg)
        return ChatResult(generations=[generation])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Streaming generation via POST /chat/stream (SSE)."""
        qwen_messages = _messages_to_qwen(messages, self._tool_schemas)

        payload = {
            "messages": qwen_messages,
            "max_tokens": self.max_tokens,
            "temperature": max(self.temperature, 0.01),
            "top_p": self.top_p,
        }

        full_text = []
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/stream",
                json=payload,
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if "token" in event:
                        token = event["token"]
                        full_text.append(token)
                        chunk = ChatGenerationChunk(
                            message=AIMessageChunk(content=token)
                        )
                        if run_manager:
                            run_manager.on_llm_new_token(token)
                        yield chunk
                    elif event.get("done"):
                        break
                    elif "error" in event:
                        logger.error("qwen_stream_error", error=event["error"])
                        break
        except Exception as e:
            logger.error("qwen_stream_failed", error=str(e))
            raise

        # After streaming, check if the full text contains tool calls
        # If so, yield a final chunk with tool_calls metadata
        combined = "".join(full_text)
        tool_calls = _parse_tool_calls(combined)
        if tool_calls:
            # Yield a final chunk that carries tool_calls
            final_chunk = ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=tool_calls,
                )
            )
            yield final_chunk
