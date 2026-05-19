# app/api/chat.py
"""
AtcoGenie AI Engine — Chat API Endpoint

Receives user prompts, resolves their identity context,
constructs the LangChain 1.0 agent with authorized tools, and returns insights.
"""

import asyncio
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Dict, Any, List, AsyncGenerator
from pydantic import BaseModel
import asyncio
import json
import threading

from app.security.context import SecurityContext
from app.middleware.auth import get_security_context
from app.database.manager import DatabaseManager, set_cancel_event as db_set_cancel_event
from app.cache.role_cache import RoleCache
from app.cache.session_context import SessionContextCache
from app.agent.user_context import resolve_user_context
from app.agent.engine import create_agent_executor
from app.agent.checkpointer import get_checkpointer
from app.agent.context_resolver import (
    has_vague_references, build_context_preamble,
    extract_entities_from_tool_calls, infer_intent, infer_target_system,
)
from app.agent.summarizer import needs_summarization, inject_summary_into_messages
from app.logging_config import get_logger
from app.agent import progress as progress_bus
from app.agent.tracer import get_tracer

logger = get_logger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    chat_history: List[Dict[str, str]] = []
    model: str | None = None  # Optional per-request model override from the frontend dropdown


def _get_db_manager(request: Request) -> DatabaseManager:
    if not hasattr(request.app.state, "db_manager"):
        raise HTTPException(status_code=500, detail="Database Manager not initialized.")
    return request.app.state.db_manager


def _get_role_cache(request: Request) -> RoleCache:
    if not hasattr(request.app.state, "role_cache"):
        raise HTTPException(status_code=500, detail="Role Cache not initialized.")
    return request.app.state.role_cache


def _get_session_ctx_cache(request: Request) -> SessionContextCache | None:
    return getattr(request.app.state, "session_ctx_cache", None)


async def _get_active_datasets(user_id: str, session_id: str, db_manager: DatabaseManager) -> str:
    """
    Returns a system-prompt string describing all ready uploads for this user
    in the given chat session. Files are scoped to the chat they were uploaded in.
    """
    pool = db_manager.get_pool("postgres")
    if not pool:
        return ""
    if not session_id:
        return ""  # No session = homepage, no datasets to show
    try:
        import json
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, filename, schema_json, sheet_names, row_count
                FROM document_uploads
                WHERE LOWER(user_id) = LOWER($1)
                  AND session_id = $2
                  AND status = 'ready'
                ORDER BY created_at DESC
                """,
                user_id,
                session_id,
            )
            if not rows:
                return ""

            datasets = []
            for r in rows:
                try:
                    schema = json.loads(r["schema_json"]) if isinstance(r["schema_json"], str) else (r["schema_json"] or {})
                    col_info = []
                    for c, dtype in schema.items():
                        if c == "_sheet":
                            continue
                        col_info.append(f"`{c}` ({dtype})")
                    cols_str = ", ".join(col_info) if col_info else "(no columns)"
                except Exception:
                    cols_str = "(schema unavailable)"

                try:
                    sheets = json.loads(r["sheet_names"]) if isinstance(r["sheet_names"], str) else (r["sheet_names"] or [])
                except Exception:
                    sheets = []

                sheet_hint = ""
                if len(sheets) > 1:
                    sheet_hint = f"\n  Sheets: {', '.join(repr(s) for s in sheets)}. Filter with `WHERE _sheet = '<name>'`."

                datasets.append(
                    f"- **'{r['filename']}'** (ID: `{r['id']}`, rows: {r['row_count']:,})"
                    f"\n  Columns: {cols_str}{sheet_hint}"
                )

            if datasets:
                return (
                    "The user has the following uploaded dataset(s) available for analysis:\n"
                    + "\n".join(datasets)
                    + "\n\n## UPLOADED DATA QUERY RULES"
                    + "\n- Use `query_user_dataset` tool with the exact ID and a DuckDB SQL query."
                    + "\n- The table is always named `data` (e.g. `SELECT * FROM data`)."
                    + "\n- **IMPORTANT**: Columns marked as `text` that look numeric (e.g. contain '-' or blanks) "
                    + "MUST be cast: `CAST(REPLACE(col, '-', '0') AS DOUBLE)`"
                    + "\n- Use DuckDB SQL syntax (supports GROUP BY, window functions, CTEs, etc.)."
                    + "\n- Return ALL results — never add LIMIT unless the user asks."
                )
            return ""
    except Exception as e:
        logger.error("fetch_active_datasets_failed", error=str(e))
        return ""



@router.post("/", response_model=Dict[str, Any])
async def chat(
    req: ChatRequest,
    request: Request,
    context: SecurityContext = Depends(get_security_context),
    db_manager: DatabaseManager = Depends(_get_db_manager),
    role_cache: RoleCache = Depends(_get_role_cache),
) -> Dict[str, Any]:
    """
    Main Chat endpoint.
    1. Resolves user's teams and role (cached in Redis)
    2. Builds LangChain agent with authorized tools
    3. Executes the prompt and returns the insight
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # 1. Resolve user's runtime context (teams, role)
    try:
        user_context = await resolve_user_context(context, db_manager, role_cache)
    except Exception as e:
        logger.error("user_context_resolution_failed", user=context.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to resolve user context.")

    # 2. Build the LangChain Agent
    try:
        agent = create_agent_executor(context, db_manager, user_context)
    except Exception as e:
        logger.error("agent_init_failed", user=context.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to initialize the Insight Engine.")

    # 3. Execute the agent using LangChain 1.0 create_agent's invoke pattern
    try:
        logger.info("chat_request", user=context.user_id, role=user_context.user_role,
                     teams=user_context.team_ids_csv, message_length=len(req.message))

        # Build messages input for the agent graph
        messages = []
        # Inject session-scoped dataset context into system prompt
        chat_session_id = request.headers.get("X-Session-Id", "")
        dataset_info = await _get_active_datasets(context.user_id, chat_session_id, db_manager)
        if dataset_info:
            messages.append({"role": "system", "content": dataset_info})

        # Add chat history if provided (keep only the last 6 messages to avoid token bloat)
        recent_history = req.chat_history[-6:] if req.chat_history else []
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Truncate massive assistant tables from previous turns so they don't blow up the context
            if role == "assistant" and len(content) > 3000:
                content = content[:3000] + "\n\n... [Data truncated to save context window] ..."
                
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": content})

        # Add current message
        messages.append({"role": "user", "content": req.message})

        tracer = get_tracer()
        run_config = {}
        langfuse_cb = None
        if tracer:
            from app.agent.tracer import CustomLangfuseCallbackHandler
            session_id = request.headers.get("X-Session-Id", "unknown")
            cb = CustomLangfuseCallbackHandler(
                tracer=tracer,
                user_id=context.user_id,
                session_id=session_id,
                user_prompt=req.message,
                metadata={"role": user_context.user_role, "teams": user_context.team_names}
            )
            langfuse_cb = cb
            run_config["callbacks"] = [cb]

        t_start = __import__("time").monotonic()
        try:
            # Temporary logging to trace token explosion
            try:
                import json
                msg_dump = json.dumps(messages, default=str)
                logger.info("agent_invoke_start", num_messages=len(messages), payload_len=len(msg_dump))
                if len(msg_dump) > 500000:
                    logger.warning("massive_payload", preview=msg_dump[:500] + "..." + msg_dump[-500:])
                    with open("storage/massive_payload.json", "w", encoding="utf-8") as f:
                        f.write(msg_dump)
            except Exception as e:
                pass
                
            result = await agent.ainvoke(
                {"messages": messages},
                config={**run_config, "recursion_limit": 150},
            )
        except asyncio.CancelledError:
            logger.warning("agent_cancelled_by_client", user=context.user_id)
            raise
        # Extract the last AI message from the response
        response_messages = result.get("messages", [])
        reply = ""
        for msg in reversed(response_messages):
            if hasattr(msg, "content") and hasattr(msg, "type") and msg.type == "ai":
                raw = msg.content
                # Gemini 2.5 thinking models return content as a list of parts
                # e.g. [{'type': 'text', 'text': '...'}, ...]
                if isinstance(raw, list):
                    reply = "\n".join(
                        part.get("text", "") for part in raw
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                else:
                    reply = raw
                break

        if not reply:
            reply = "I'm sorry, I couldn't generate a response."

        latency_ms = (__import__("time").monotonic() - t_start) * 1000
        logger.info("chat_response", user=context.user_id, reply_length=len(reply), latency_ms=round(latency_ms))

        # Flush Langfuse events in background (fire-and-forget, never blocks response)
        if langfuse_cb:
            asyncio.create_task(langfuse_cb.flush(reply))
        return {
            "reply": reply,
            "user": {
                "display_name": context.display_name,
                "role": user_context.user_role,
                "teams": user_context.team_names,
                "is_admin": user_context.is_admin,
            }
        }
    except Exception as e:
        import traceback
        err_str = traceback.format_exc()
        # Gemini rate limit — return a friendly message so the UI can display it
        if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
            logger.warning("rate_limited", user=context.user_id, error=err_str[:200])
            return {
                "reply": (
                    "⏳ I'm temporarily rate-limited by the AI service (free tier quota). "
                    "Please wait **30–60 seconds** and try again. "
                    "For production use, a paid API key removes this restriction."
                ),
                "user": {
                    "display_name": context.display_name,
                    "role": user_context.user_role,
                    "teams": user_context.team_names,
                    "is_admin": user_context.is_admin,
                }
            }
        logger.error("agent_execution_failed", user=context.user_id, error=err_str, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Insight Engine Error: {err_str}")
# SSE Streaming Endpoint — live progress updates to frontend
# ----------------------------------------------------------------

@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    context: SecurityContext = Depends(get_security_context),
    db_manager: DatabaseManager = Depends(_get_db_manager),
    role_cache: RoleCache = Depends(_get_role_cache),
):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).

    Architecture:
    - Agent runs in a background Task with a CancellationEvent.
    - On client disconnect the event is set and the task is cancelled
      immediately — no orphaned SP calls continue running.
    - The final reply is streamed token-by-token so stopping mid-stream
      cleanly discards remaining characters (not a full dump).
    - Keepalives are sent every 2 s only while the agent is still running.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Resolve context
    try:
        user_context = await resolve_user_context(context, db_manager, role_cache)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to resolve user context.")

    try:
        checkpointer = get_checkpointer()
        agent = create_agent_executor(
            context, db_manager, user_context,
            model_override=req.model,
            checkpointer=checkpointer,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to initialize the Insight Engine.")

    # Load session context for multi-turn resolution
    session_ctx_cache = _get_session_ctx_cache(request)
    chat_session_id = request.headers.get("X-Session-Id", "")
    # Per-request state
    q: asyncio.Queue = asyncio.Queue()
    progress_bus.set_queue(q)

    # Per-request DB cancellation event — set on client disconnect to abort pyodbc threads
    _db_cancel = threading.Event()
    db_set_cancel_event(_db_cancel)

    async def run_agent():
        """
        Streams tokens in real-time from the LangGraph agent via astream_events v2.

        Architecture:
        - Uses astream_events(version='v2') which yields tokens as Gemini generates them.
        - Tokens are batched into ~50-char chunks before being enqueued to prevent
          the frontend React renderer from re-rendering+re-parsing markdown 500×/sec.
        - A canonical 'done' event containing the full reply is sent at the end so
          the frontend can replace the streaming buffer with the authoritative text.
        - Progress messages (tool calls, SP execution) are sent as 'status' events.
        """
        try:
            messages = []
            # Inject session-scoped dataset context into system prompt
            chat_session_id = request.headers.get("X-Session-Id", "")
            dataset_info = await _get_active_datasets(context.user_id, chat_session_id, db_manager)
            if dataset_info:
                messages.append({"role": "system", "content": dataset_info})

            # Add chat history if provided (keep only the last 6 messages to avoid token bloat)
            recent_history = req.chat_history[-6:] if req.chat_history else []
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                # Truncate massive assistant tables from previous turns so they don't blow up the context
                if role == "assistant" and len(content) > 3000:
                    content = content[:3000] + "\n\n... [Data truncated to save context window] ..."
                    
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": req.message})

            # --- Multi-turn context resolution ---
            if session_ctx_cache and chat_session_id:
                session_ctx = await session_ctx_cache.get(chat_session_id)

                # Inject rolling summary for long conversations
                if session_ctx.summary and needs_summarization(session_ctx.message_count):
                    messages = inject_summary_into_messages(messages, session_ctx.summary)

                # Inject context preamble for vague references
                if has_vague_references(req.message) and session_ctx.resolved_entities:
                    preamble = build_context_preamble(session_ctx)
                    if preamble:
                        messages.insert(0, {"role": "system", "content": preamble})
                        logger.debug("context_preamble_injected", session_id=chat_session_id)

            tracer = get_tracer()
            run_config = {}
            langfuse_cb = None
            if tracer:
                from app.agent.tracer import CustomLangfuseCallbackHandler
                from app.agent.langfuse_context import current_tracer_cb
                session_id = request.headers.get("X-Session-Id", "unknown")
                cb = CustomLangfuseCallbackHandler(
                    tracer=tracer,
                    user_id=context.user_id,
                    session_id=session_id,
                    user_prompt=req.message,
                    metadata={"role": user_context.user_role, "teams": user_context.team_names}
                )
                langfuse_cb = cb
                run_config["callbacks"] = [cb]
                current_tracer_cb.set(cb)

            # Send user metadata first so the UI can set up the header
            meta = {
                "type": "meta",
                "user": {
                    "display_name": context.display_name,
                    "role": user_context.user_role,
                    "teams": user_context.team_names,
                    "is_admin": user_context.is_admin,
                }
            }
            await q.put(meta)

            t_start = __import__("time").monotonic()
            full_reply = []
            token_buffer = []
            BATCH_CHARS = 50  # flush a chunk every ~50 chars
            _first_token_at: float | None = None

            # Thread ID for checkpointer — uses session ID for per-conversation persistence
            _thread_config = {}
            if chat_session_id:
                _thread_config["configurable"] = {"thread_id": chat_session_id}

            async for event in agent.astream_events(
                {"messages": messages},
                config={**run_config, **_thread_config, "recursion_limit": 150},
                version="v2",
            ):
                kind = event.get("event", "")

                # Real LLM token from the final AI response node
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue
                    # LangChain AIMessageChunk: content may be str or list-of-parts
                    raw = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(raw, list):
                        text = "".join(
                            p.get("text", "") for p in raw
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    else:
                        text = str(raw) if raw else ""

                    if not text:
                        continue

                    if _first_token_at is None:
                        _first_token_at = __import__("time").monotonic()
                        ttft_ms = (_first_token_at - t_start) * 1000
                        logger.info("chat_ttft", user=context.user_id,
                                    ttft_ms=round(ttft_ms),
                                    model=req.model or "(env-default)")

                    full_reply.append(text)
                    token_buffer.append(text)

                    # Flush a partial update when batch threshold reached.
                    # EXCEPTION: For vertex-maas (Llama 4 Scout), skip partial_done
                    # entirely — Llama narrates its reasoning as plain text during
                    # generation, so streaming partial chunks would show thinking
                    # steps to the user before the final cleanup pass runs.
                    _is_vertex = req.model == "llama-4-scout"
                    if not _is_vertex and sum(len(t) for t in token_buffer) >= BATCH_CHARS:
                        token_buffer.clear()
                        await q.put({"type": "partial_done", "reply": "".join(full_reply), "user": meta["user"]})

                # Tool call start (e.g. "Fetching customer sales data...")
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    await q.put({"type": "status", "message": f"Running {tool_name}..."})

            # Flush any remaining buffered tokens (skip partial_done for vertex-maas — see above)
            _is_vertex = req.model == "llama-4-scout"
            if token_buffer and not _is_vertex:
                await q.put({"type": "partial_done", "reply": "".join(full_reply), "user": meta["user"]})

            reply = "".join(full_reply)

            # ── Thinking / reasoning strip ────────────────────────────────────
            # Applied ONLY to models known to leak reasoning into the output.
            # Llama 4 Scout concatenates Step blocks INLINE (not at line starts),
            # so line-anchored regex fails. Use a more aggressive approach.
            import re

            _narrating_models = {"llama-4-scout"}  # extend as needed
            if req.model in _narrating_models:
                # Strip XML think blocks
                reply = re.sub(r"<think>.*?</think>\s*", "", reply, flags=re.DOTALL)

                # Strip all "Step N:" blocks — handles both inline and line-start.
                # Match "Step <number>:" or "Step <number>." followed by text,
                # up to the next Step header or a content marker.
                reply = re.sub(
                    r"Step\s+\d+\s*[:\.].*?(?=Step\s+\d+\s*[:\.]|```|---\s*\n|\|[\s\-]|## |$)",
                    "",
                    reply,
                    flags=re.DOTALL,
                )

                # Strip "Let's assume" fabrication blocks
                reply = re.sub(r"Let's assume.*?\n\n", "", reply, flags=re.DOTALL)

                # Strip "Simulated Response/Output" markers
                reply = re.sub(r"Simulated\s+(Response|Output|Answer)\s*\n?", "", reply)

                # Strip "However, to strictly follow..." preamble
                reply = re.sub(
                    r"However,\s+to\s+strictly\s+follow.*?\n\n",
                    "",
                    reply,
                    flags=re.DOTALL,
                )

                # Strip "Now, let's execute..." bridge sentences
                reply = re.sub(r"Now,?\s+let'?s\s+execute.*?\n", "", reply)

                # Fix malformed chart-json: Llama often omits the closing ```
                # Pattern: ```chart-json{...} at end without closing ```
                if "```chart-json" in reply and reply.rstrip().endswith("}"):
                    # Find the last ```chart-json and ensure it has closing ```
                    last_chart = reply.rfind("```chart-json")
                    if last_chart != -1:
                        after_chart = reply[last_chart:]
                        if after_chart.count("```") == 1:  # only opening, no closing
                            reply = reply + "\n```"

                # Fix chart-json on same line as opening fence
                # e.g. ```chart-json{"type":...} → ```chart-json\n{"type":...}
                reply = re.sub(
                    r"```chart-json\s*(\{)",
                    "```chart-json\n\\1",
                    reply,
                )

                # Collapse 3+ consecutive blank lines down to 2
                reply = re.sub(r"\n{3,}", "\n\n", reply)
                reply = reply.strip()
            else:
                # For all other models just strip bare <think> tags as a safety net
                reply = re.sub(r"<think>.*?</think>\s*", "", reply, flags=re.DOTALL)

            latency_ms = (__import__("time").monotonic() - t_start) * 1000
            logger.info("chat_stream_response", user=context.user_id,
                        reply_length=len(reply), latency_ms=round(latency_ms))

            if langfuse_cb:
                asyncio.create_task(langfuse_cb.flush(reply))

            # Send canonical full reply so frontend replaces the stream buffer
            # with the authoritative text (avoids any off-by-one token issues)
            await q.put({"type": "done", "reply": reply, "user": meta["user"]})

            # --- Post-turn context update ---
            if session_ctx_cache and chat_session_id:
                try:
                    # Extract entities from the agent's tool calls
                    response_messages = []
                    async for state in agent.aget_state_history(
                        config={**_thread_config},
                    ):
                        response_messages = state.values.get("messages", [])
                        break  # only need the latest state

                    entities = extract_entities_from_tool_calls(response_messages)
                    intent = infer_intent(req.message)
                    target = infer_target_system(req.message)

                    await session_ctx_cache.update_after_turn(
                        session_id=chat_session_id,
                        intent=intent,
                        target_system=target,
                        entities=entities,
                    )
                    logger.debug("session_context_updated",
                                 session_id=chat_session_id, intent=intent,
                                 entities=list(entities.keys()))
                except Exception as e:
                    logger.warning("session_context_update_failed", error=str(e))

        except asyncio.CancelledError:
            logger.info("agent_task_cancelled", user=context.user_id)
            _db_cancel.set()
            await q.put({"type": "cancelled"})

        except Exception as e:
            import traceback, httpx
            tb = traceback.format_exc()
            err_str = str(e)

            # ── Transient network drop (Gemini stream interrupted mid-flight) ──
            if isinstance(e, (httpx.ReadError, httpx.RemoteProtocolError)) or \
               "ReadError" in tb or "RemoteProtocolError" in tb:
                logger.warning("gemini_stream_dropped", user=context.user_id,
                               had_partial=bool(full_reply))
                if full_reply:
                    # Send whatever was received before the drop
                    partial = "".join(full_reply)
                    note = (
                        "\n\n---\n"
                        "*⚠️ The AI connection was interrupted. "
                        "The response above may be incomplete — please re-ask if you need more detail.*"
                    )
                    await q.put({"type": "done", "reply": partial + note, "user": meta["user"]})
                else:
                    await q.put({"type": "error", "reply": (
                        "🔌 The connection to the AI service was interrupted before a response arrived. "
                        "This is a temporary network issue — please **try again**."
                    )})
                return

            logger.error("agent_stream_failed", user=context.user_id, error=tb)

            err_lower = err_str.lower()
            if "resource_exhausted" in err_str or "429" in err_str:
                err_reply = "⏳ I'm temporarily rate-limited. Please wait 30–60 seconds and try again."
            elif "timeout" in err_lower or "deadline" in err_lower or \
                 "timed out" in err_lower or "deadlineexceeded" in err_lower:
                err_reply = (
                    "⏱️ This query took too long and was terminated by the database server.\n\n"
                    "**Try one of these to speed it up:**\n"
                    "- Filter by a specific team or product\n"
                    "- Use a shorter date range\n"
                    "- Ask for a summary by month instead of full detail"
                )
            else:
                err_reply = f"An error occurred: {err_str[:200]}"
            await q.put({"type": "error", "reply": err_reply})


    async def event_generator() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(run_agent())

        yield f"data: {json.dumps({'type': 'status', 'message': 'Thinking...'})}\n\n"

        keepalive_counter = 0
        prompt_shown = False
        start_time = __import__("time").monotonic()

        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                keepalive_counter += 1
                if keepalive_counter >= 150:  # ~15s keepalive cadence
                    keepalive_counter = 0
                    yield ": keepalive\n\n"
                    
                elapsed = __import__("time").monotonic() - start_time
                if elapsed >= 600 and not prompt_shown:  # 10 mins
                    prompt_shown = True
                    timeout_msg = "⏳ This is taking longer than 10 minutes. Would you like to **continue waiting** or **cancel the request**?\n\n*(The query is still running — click the stop button to cancel at any time.)*"
                    # Send as a status ticker AND as a visible chat message so the user actually sees it
                    yield f"data: {json.dumps({'type': 'status', 'message': '⏳ Still running (10 min+)...'})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'reply': timeout_msg, 'user': {}})}\n\n"
                    
                continue

            if isinstance(item, str):
                yield f"data: {json.dumps({'type': 'status', 'message': item})}\n\n"

            elif isinstance(item, dict):
                event_type = item.get("type")

                if event_type == "meta":
                    yield f"data: {json.dumps(item)}\n\n"

                elif event_type == "partial_done":
                    # Send a fake 'done' event so the frontend progressively renders
                    msg = {"type": "done", "reply": item.get("reply"), "user": item.get("user")}
                    yield f"data: {json.dumps(msg)}\n\n"

                elif event_type == "chunk":
                    # Real-time token chunk — frontend appends this to the message buffer
                    yield f"data: {json.dumps(item)}\n\n"

                elif event_type == "status":
                    yield f"data: {json.dumps(item)}\n\n"

                elif event_type == "cancelled":
                    yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                    break

                elif event_type == "error":
                    yield f"data: {json.dumps(item)}\n\n"
                    break

                elif event_type == "done":
                    # Canonical full reply — closes the stream
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    yield f"data: {json.dumps(item)}\n\n"
                    break

        progress_bus.set_queue(asyncio.Queue())

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
