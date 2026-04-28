import uuid
import contextvars
from datetime import datetime, timezone
from typing import Any

# Global context var to hold the current CustomLangfuseCallbackHandler instance
current_tracer_cb: contextvars.ContextVar[Any] = contextvars.ContextVar('current_tracer_cb', default=None)

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _safe(val: Any) -> Any:
    """Recursively convert any value to JSON-safe primitives."""
    if val is None or isinstance(val, (int, float, bool)):
        return val
    if isinstance(val, str):
        # Truncate very large strings
        return val[:50_000] if len(val) > 50_000 else val
    if isinstance(val, dict):
        return {str(k): _safe(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_safe(v) for v in val]
    return str(val)

def log_db_query_span(sp_name: str, sql: str, args: Any) -> str:
    """
    Logs a discrete custom database span directly to the active tracer.
    Call this before executing the DB query.
    Returns a span_id that should be used to close the span via finish_db_query_span.
    """
    cb = current_tracer_cb.get()
    if not cb:
        return ""
    
    span_id = str(uuid.uuid4())
    cb._events.append({
        "id": str(uuid.uuid4()),
        "type": "span-create",
        "timestamp": _iso_now(),
        "body": {
            "id": span_id,
            "traceId": cb.trace_id,
            "name": f"SQL: {sp_name}",
            "startTime": _iso_now(),
            "input": _safe({"query": sql, "arguments": args}),
            "metadata": {"source": "database_manager"}
        }
    })
    return span_id

def finish_db_query_span(span_id: str, output_data: Any = None, level: str = "DEFAULT", error: str = None):
    """
    Closes a previously opened database query span.
    Provide output_data (like row count) or an error string if it failed.
    """
    cb = current_tracer_cb.get()
    if not cb or not span_id:
        return
        
    body = {
        "id": span_id,
        "traceId": cb.trace_id,
        "endTime": _iso_now(),
    }
    if output_data is not None:
        body["output"] = _safe(output_data)
    if level != "DEFAULT":
        body["level"] = level
    if error:
        body["statusMessage"] = str(error)
        body["level"] = "ERROR"
        
    cb._events.append({
        "id": str(uuid.uuid4()),
        "type": "span-update",
        "timestamp": _iso_now(),
        "body": body
    })
