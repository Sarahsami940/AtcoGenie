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
from typing import Any, AsyncIterator, List, Optional, Iterator

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
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

# Errors that indicate the Qwen server closed the connection after finishing
# generation — harmless, we already have all the tokens.
_BENIGN_STREAM_ERRORS = (
    "incomplete chunked read",
    "peer closed connection",
    "RemoteProtocolError",
    "ReadError",
    "IncompleteRead",
)


def _is_benign_stream_error(exc: Exception) -> bool:
    """Check if a streaming exception is just the Qwen server closing early."""
    msg = str(exc)
    return any(pattern in msg for pattern in _BENIGN_STREAM_ERRORS)


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


def _build_payload(messages: list[dict], max_tokens: int, temperature: float, top_p: float) -> dict:
    return {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": max(temperature, 0.01),  # Qwen deadlocks on exactly 0
        "top_p": top_p,
    }


def _text_to_ai_message(text: str, tool_schemas: list[dict]) -> AIMessage:
    """Convert raw Qwen text to an AIMessage, parsing any tool calls."""
    tool_calls = _parse_tool_calls(text) if tool_schemas else []
    if tool_calls:
        clean_text = _TOOL_CALL_RE.sub("", text).strip()
        return AIMessage(content=clean_text, tool_calls=tool_calls)
    return AIMessage(content=text)


class QwenChatLLM(BaseChatModel):
    """LangChain BaseChatModel that calls the on-prem Qwen 2.5-7B API.
    Implements both sync and async generation/streaming.
    """

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
                schema_obj = t.get_input_schema()
                schema = schema_obj.schema() if hasattr(schema_obj, "schema") else {}
            else:
                schema = {}
            schemas.append({
                "name": getattr(t, "name", str(t)),
                "description": getattr(t, "description", ""),
                "parameters": schema,
            })
        new_instance = self.model_copy()
        new_instance._tool_schemas = schemas
        return new_instance

    # ── Sync methods (fallback) ──────────────────────────────────────────

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation via POST /chat."""
        qwen_messages = _messages_to_qwen(messages, self._tool_schemas)
        payload = _build_payload(qwen_messages, self.max_tokens, self.temperature, self.top_p)

        try:
            resp = httpx.post(
                f"{self.base_url}/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "")
        except httpx.HTTPStatusError as e:
            logger.error("qwen_api_error", status=e.response.status_code, body=e.response.text[:300])
            raise
        except Exception as e:
            logger.error("qwen_request_failed", error=str(e))
            raise

        ai_msg = _text_to_ai_message(text, self._tool_schemas)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Streaming generation via POST /chat/stream (SSE) — sync version."""
        qwen_messages = _messages_to_qwen(messages, self._tool_schemas)
        payload = _build_payload(qwen_messages, self.max_tokens, self.temperature, self.top_p)

        full_text: list[str] = []
        done_received = False

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
                        chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
                        if run_manager:
                            run_manager.on_llm_new_token(token)
                        yield chunk
                    elif event.get("done"):
                        done_received = True
                        break
                    elif "error" in event:
                        logger.error("qwen_stream_error", error=event["error"])
                        break
        except Exception as e:
            if _is_benign_stream_error(e) and full_text:
                logger.debug("qwen_stream_closed_benign", tokens=len(full_text))
            else:
                logger.error("qwen_stream_failed", error=str(e))
                raise

        # Check for tool calls in accumulated output
        combined = "".join(full_text)
        tool_calls = _parse_tool_calls(combined) if self._tool_schemas else []
        if tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=tool_calls)
            )

    # ── Async methods (primary path — used by astream_events) ────────────

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generation via POST /chat."""
        qwen_messages = _messages_to_qwen(messages, self._tool_schemas)
        payload = _build_payload(qwen_messages, self.max_tokens, self.temperature, self.top_p)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/chat", json=payload)
                resp.raise_for_status()
                text = resp.json().get("response", "")
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout):
            logger.warning("qwen_timeout", timeout=self.timeout)
            friendly = (
                "⏳ The Qwen model server is currently unresponsive (timeout). "
                "This usually means the GPU is busy processing another request.\n\n"
                "**Please try again in a moment**, or switch to **Gemini 3.1 Flash** "
                "for instant responses."
            )
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=friendly))])
        except httpx.ConnectError:
            logger.error("qwen_connect_failed", url=self.base_url)
            friendly = (
                "🔌 Cannot reach the Qwen model server at `{}`.\n\n"
                "The server may be offline. Please try **Gemini 3.1 Flash** instead, "
                "or contact IT to check the Qwen server status."
            ).format(self.base_url)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=friendly))])
        except httpx.HTTPStatusError as e:
            logger.error("qwen_api_error", status=e.response.status_code, body=e.response.text[:300])
            raise
        except Exception as e:
            logger.error("qwen_request_failed", error=str(e))
            raise

        ai_msg = _text_to_ai_message(text, self._tool_schemas)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async 'streaming' — calls /chat (non-streaming) and yields the full
        response as a single chunk.

        Why not /chat/stream?  The Qwen server drops the TCP connection after
        sending {"done": true} without properly terminating HTTP chunked encoding.
        httpx raises RemoteProtocolError("incomplete chunked read") during context
        manager cleanup — after all tokens have been read but before __aexit__
        finishes.  There is no reliable way to suppress this on the client side
        because the error fires inside the `async with` teardown, not in user code.

        Using /chat avoids the issue entirely.  At ~12 tok/s the 7B model produces
        a full response in a few seconds — the UX difference is negligible.
        """
        # Reuse _agenerate which calls /chat safely
        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

        ai_msg = result.generations[0].message
        content = ai_msg.content or ""

        # Yield the full text as one chunk
        if content:
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=content))
            if run_manager:
                await run_manager.on_llm_new_token(content)
            yield chunk

        # If there were tool calls, yield them as a separate chunk
        if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=ai_msg.tool_calls)
            )
