"""
AtcoGenie AI Engine — Live Progress Bus

A lightweight async queue that any tool or pipeline stage can write status
messages into. The SSE endpoint drains this queue and sends events to the
frontend in real-time, making long queries feel alive and interactive.
"""

import asyncio
from contextvars import ContextVar

# Per-request progress queue injected via context var
_progress_queue: ContextVar[asyncio.Queue | None] = ContextVar("progress_queue", default=None)


def get_queue() -> asyncio.Queue | None:
    return _progress_queue.get()


def set_queue(q: asyncio.Queue) -> None:
    _progress_queue.set(q)


async def emit(message: str) -> None:
    """Push a live status message from anywhere in the pipeline."""
    q = _progress_queue.get()
    if q is not None:
        await q.put(message)
