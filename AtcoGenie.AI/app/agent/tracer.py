"""
AtcoGenie — Langfuse Tracer (Batch Mode)

Sends traces to Langfuse server via raw HTTP (no SDK pydantic dependency).
Required because Python 3.14 breaks pydantic v1, which all langfuse SDK versions use.

Strategy: Collect ALL events during a request, then flush them in ONE batch
at the end. This guarantees ordering and prevents lost events.
"""

import asyncio
import base64
import json
import uuid
import httpx
from datetime import datetime, timezone

from app.logging_config import get_logger

logger = get_logger(__name__)


def _b64_auth(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {token}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LangfuseTracer:
    """
    Lightweight async Langfuse tracer using raw HTTP ingestion API.
    Bypasses the SDK entirely to avoid pydantic v1 / Python 3.14 incompatibility.
    """

    def __init__(self, public_key: str, secret_key: str, host: str):
        self.host = host.rstrip("/")
        self.auth = _b64_auth(public_key, secret_key)
        self.ingest_url = f"{self.host}/api/public/ingestion"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def auth_check(self) -> bool:
        try:
            r = await self._client.get(
                f"{self.host}/api/public/projects",
                headers={"Authorization": self.auth}
            )
            return r.status_code == 200
        except Exception as e:
            logger.error("langfuse_auth_check_failed", error=str(e))
            return False

    async def ingest_batch(self, events: list[dict]) -> None:
        """POST a batch of events to the Langfuse ingestion endpoint."""
        if not events:
            return
        try:
            resp = await self._client.post(
                self.ingest_url,
                json={"batch": events},
                headers={
                    "Authorization": self.auth,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code not in (200, 201, 207):
                logger.warning("langfuse_ingest_fail", status=resp.status_code, body=resp.text[:300])
            else:
                logger.info("langfuse_batch_sent", event_count=len(events), status=resp.status_code)
        except Exception as e:
            logger.error("langfuse_ingest_error", error=str(e))


# ---------------------------------------------------------------------------
# Callback Handler — collects events, flushes at end
# ---------------------------------------------------------------------------

from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List, Optional


def _safe(val: Any) -> Any:
    """Recursively convert any value to JSON-safe primitives."""
    if val is None or isinstance(val, (int, float, bool)):
        return val
    if isinstance(val, str):
        # Truncate very large strings (e.g. 100k row SQL results)
        return val[:50_000] if len(val) > 50_000 else val
    if isinstance(val, dict):
        return {str(k): _safe(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_safe(v) for v in val]
    if hasattr(val, "model_dump") and callable(val.model_dump):
        try:
            return _safe(val.model_dump())
        except Exception:
            pass
    if hasattr(val, "dict") and callable(val.dict):
        try:
            return _safe(val.dict())
        except Exception:
            pass
    return str(val)


class CustomLangfuseCallbackHandler(AsyncCallbackHandler):
    """
    Collects LangChain callback events into a batch list.
    Call `flush()` after agent execution to send everything to Langfuse in one shot.
    """

    def __init__(
        self,
        tracer: LangfuseTracer,
        user_id: str,
        session_id: str,
        user_prompt: str,
        metadata: dict,
    ):
        self.tracer = tracer
        self.trace_id = str(uuid.uuid4())
        self.user_id = user_id
        self.session_id = session_id
        self.user_prompt = user_prompt
        self.metadata = metadata
        self._events: list[dict] = []
        self._run_to_span: Dict[str, str] = {}
        self._trace_start = _iso_now()

    # --- helpers ---

    def _span_id(self, run_id: uuid.UUID) -> str:
        key = str(run_id)
        if key not in self._run_to_span:
            self._run_to_span[key] = str(uuid.uuid4())
        return self._run_to_span[key]

    def _add(self, event_type: str, body: dict) -> None:
        self._events.append({
            "id": str(uuid.uuid4()),
            "type": event_type,
            "timestamp": _iso_now(),
            "body": body,
        })

    # --- flush (call this ONCE after agent completes) ---

    async def flush(self, final_output: str | None = None) -> None:
        """Send everything to Langfuse in one batch."""
        # Build trace-create as the FIRST event
        trace_event = {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": self._trace_start,
            "body": {
                "id": self.trace_id,
                "name": "atcogenie-query",
                "userId": self.user_id,
                "sessionId": self.session_id,
                "input": self.user_prompt,
                "output": final_output or "",
                "metadata": self.metadata,
                "tags": ["atcogenie", "production"],
                "timestamp": self._trace_start,
            },
        }

        all_events = [trace_event] + self._events
        logger.info("langfuse_flushing", trace_id=self.trace_id, total_events=len(all_events))
        await self.tracer.ingest_batch(all_events)

    # --- LangChain Callbacks ---

    async def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or (serialized.get("id", ["chain"])[-1] if serialized.get("id") else "chain")
        span_id = self._span_id(run_id)
        parent = self._run_to_span.get(str(parent_run_id)) if parent_run_id else None

        self._add("span-create", {
            "id": span_id,
            "traceId": self.trace_id,
            "parentObservationId": parent,
            "name": name,
            "startTime": _iso_now(),
            "input": _safe(inputs),
        })

    async def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._add("span-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "output": _safe(outputs),
        })

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._add("span-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "level": "ERROR",
            "statusMessage": str(error)[:2000],
        })

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        serialized = serialized or {}
        name = serialized.get("name", "tool")
        span_id = self._span_id(run_id)
        parent = self._run_to_span.get(str(parent_run_id)) if parent_run_id else None

        self._add("span-create", {
            "id": span_id,
            "traceId": self.trace_id,
            "parentObservationId": parent,
            "name": f"Tool: {name}",
            "startTime": _iso_now(),
            "input": _safe(input_str),
        })

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._add("span-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "output": _safe(output),
        })

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._add("span-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "level": "ERROR",
            "statusMessage": str(error)[:2000],
        })

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        serialized = serialized or {}
        name = serialized.get("name") or (serialized.get("id", ["llm"])[-1] if serialized.get("id") else "llm")
        inv = kwargs.get("invocation_params", {})
        model = inv.get("model") or inv.get("model_name", "unknown")
        span_id = self._span_id(run_id)
        parent = self._run_to_span.get(str(parent_run_id)) if parent_run_id else None

        self._add("generation-create", {
            "id": span_id,
            "traceId": self.trace_id,
            "parentObservationId": parent,
            "name": name,
            "model": model,
            "startTime": _iso_now(),
            "input": _safe(messages),
            "modelParameters": _safe(inv),
        })

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        output_txt = ""
        try:
            gens = response.generations
            if gens and len(gens) > 0 and len(gens[0]) > 0:
                gen = gens[0][0]
                output_txt = gen.text if gen.text else str(gen.message.content if hasattr(gen, "message") else gen)
        except Exception:
            output_txt = str(response)

        self._add("generation-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "completionStartTime": _iso_now(),
            "output": _safe(output_txt),
        })

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        parent_run_id: Optional[uuid.UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._add("generation-update", {
            "id": self._span_id(run_id),
            "traceId": self.trace_id,
            "endTime": _iso_now(),
            "level": "ERROR",
            "statusMessage": str(error)[:2000],
        })


# -----------------------------------------------------------------------
# Module-level singleton — initialized once at startup
# -----------------------------------------------------------------------

_tracer: LangfuseTracer | None = None


def init_tracer(public_key: str, secret_key: str, host: str) -> LangfuseTracer | None:
    global _tracer
    if not public_key or not secret_key:
        logger.warning("langfuse_inactive", reason="Missing public or secret key")
        return None
    _tracer = LangfuseTracer(public_key=public_key, secret_key=secret_key, host=host)
    logger.info("langfuse_tracer_ready", host=host)
    return _tracer


def get_tracer() -> LangfuseTracer | None:
    return _tracer
