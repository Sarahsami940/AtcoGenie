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

from app.security.context import SecurityContext
from app.middleware.auth import get_security_context
from app.database.manager import DatabaseManager
from app.cache.role_cache import RoleCache
from app.agent.user_context import resolve_user_context
from app.agent.engine import create_agent_executor
from app.logging_config import get_logger
from app.agent import progress as progress_bus
from app.agent.tracer import get_tracer

logger = get_logger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    chat_history: List[Dict[str, str]] = []


def _get_db_manager(request: Request) -> DatabaseManager:
    if not hasattr(request.app.state, "db_manager"):
        raise HTTPException(status_code=500, detail="Database Manager not initialized.")
    return request.app.state.db_manager


def _get_role_cache(request: Request) -> RoleCache:
    if not hasattr(request.app.state, "role_cache"):
        raise HTTPException(status_code=500, detail="Role Cache not initialized.")
    return request.app.state.role_cache


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

        # Add chat history if provided
        for msg in req.chat_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
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
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": messages}, config=run_config),
                timeout=300  # 300s (5 min) — SP ~25s + thinking LLM ~90s + buffer
            )
        except asyncio.TimeoutError:
            logger.warning("agent_timeout", user=context.user_id, timeout_s=300)
            return {
                "reply": (
                    "⏳ This analysis is taking longer than expected (>5 minutes). "
                    "This can happen with very large datasets or complex queries. Try a **shorter date range** "
                    "or a **more specific filter** (e.g., a single team or product)."
                ),
                "user": {
                    "display_name": context.display_name,
                    "role": user_context.user_role,
                    "teams": user_context.team_names,
                    "is_admin": user_context.is_admin,
                }
            }
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
        agent = create_agent_executor(context, db_manager, user_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to initialize the Insight Engine.")

    # Per-request state
    q: asyncio.Queue = asyncio.Queue()
    progress_bus.set_queue(q)

    async def run_agent():
        """Runs the LangChain agent using astream_events for real-time text generation."""
        try:
            messages = []
            for msg in req.chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
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

            # -------------------------------------------------------------------
            # Reliable streaming: ainvoke guarantees the COMPLETE response, then
            # we stream it to the frontend in small text chunks for the typewriter
            # effect. Gemini+LangGraph buffers internally until LLM generation is
            # complete before yielding, so astream gives no advantage here.
            # -------------------------------------------------------------------

            # Send user metadata early so frontend can set up the UI
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

            result = await agent.ainvoke({"messages": messages}, config=run_config)

            # Extract the last AI message
            reply = ""
            for msg in reversed(result.get("messages", [])):
                if hasattr(msg, "type") and msg.type == "ai":
                    raw = msg.content
                    if isinstance(raw, list):
                        reply = "".join(
                            p.get("text", "") for p in raw
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    else:
                        reply = str(raw) if raw else ""
                    break


            latency_ms = (__import__("time").monotonic() - t_start) * 1000
            logger.info("chat_stream_response", user=context.user_id,
                        reply_length=len(reply), latency_ms=round(latency_ms))

            if langfuse_cb:
                asyncio.create_task(langfuse_cb.flush(reply))

            # -----------------------------------------------------------------
            # Send the COMPLETE reply in a single atomic SSE event.
            #
            # WHY: Chunked streaming (even large chunks) triggers Chrome's
            # background tab throttle — any repeated message handler fires at
            # most 1Hz when the tab is hidden, causing the response to pause.
            #
            # A SINGLE event is not subject to throttling: the browser delivers
            # it the moment the TCP packet arrives regardless of tab visibility.
            # The UI typewriter animation (if any) runs client-side on the
            # already-received full text, avoiding all background issues and
            # making table rendering instant (one DOM paint instead of hundreds).
            # -----------------------------------------------------------------
            await q.put({"type": "done", "reply": reply, "user": meta["user"]})

        except asyncio.CancelledError:
            logger.info("agent_task_cancelled", user=context.user_id)
            await q.put({"type": "cancelled"})
        except Exception as e:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                err_reply = "⏳ I'm temporarily rate-limited. Please wait 30–60 seconds and try again."
            else:
                err_reply = f"An error occurred: {err_str[:200]}"
            await q.put({"type": "error", "reply": err_reply})

    async def event_generator() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(run_agent())

        yield f"data: {json.dumps({'type': 'status', 'message': 'Thinking...'})}\n\n"

        keepalive_counter = 0

        while True:
            try:
                # Poll with 100ms timeout — fast enough to detect events,
                # not busy-wait overhead while the LLM is thinking
                item = await asyncio.wait_for(q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                keepalive_counter += 1
                # Every ~15s (150 × 100ms) — keeps TCP alive during LLM thinking
                if keepalive_counter >= 150:
                    keepalive_counter = 0
                    yield ": keepalive\n\n"
                continue

            if isinstance(item, str):
                yield f"data: {json.dumps({'type': 'status', 'message': item})}\n\n"

            elif isinstance(item, dict):
                event_type = item.get("type")

                if event_type == "meta":
                    # User context sent early so the UI can set up the header
                    yield f"data: {json.dumps(item)}\n\n"

                elif event_type == "cancelled":
                    yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                    break

                elif event_type == "error":
                    yield f"data: {json.dumps(item)}\n\n"
                    break

                elif event_type == "done":
                    # Single atomic event — background-tab safe, instant render
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    yield f"data: {json.dumps(item)}\n\n"
                    break

        # Cleanup
        progress_bus.set_queue(asyncio.Queue())
        # We do NOT cancel the background task here anymore.
        # This fixes the bug where mobile Chrome/Safari sleeping a tab 
        # caused FastAPI to throttle and erroneously terminate the task.
        # The background task will just finish cleanly and its output to `q` gets GC'd.

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
