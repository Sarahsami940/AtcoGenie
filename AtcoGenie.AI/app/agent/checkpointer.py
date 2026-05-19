"""
AtcoGenie AI Engine — Conversation Checkpointer

Provides a singleton PostgresSaver for LangGraph conversation persistence.
Checkpoint tables are auto-created on first startup.

Uses the SYNC PostgresSaver to avoid Windows ProactorEventLoop issues with
psycopg's async implementation. Since LangGraph's astream_events requires
an async checkpointer (aget_tuple, etc.), we monkey-patch the sync checkpointer
to run its synchronous methods inside asyncio.to_thread.
"""

import asyncio
from psycopg import Connection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_checkpointer: PostgresSaver | None = None
_conn: Connection | None = None


# --- Monkey-patch for async support ---
async def _aget_tuple(self, config):
    return await asyncio.to_thread(self.get_tuple, config)

async def _aput(self, config, checkpoint, metadata, new_versions):
    return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

async def _aput_writes(self, config, writes, task_id):
    return await asyncio.to_thread(self.put_writes, config, writes, task_id)

async def _alist(self, config, filter=None, before=None, limit=None):
    # alist returns an iterator, we need to convert it to a list in the thread
    def _get_list():
        return list(self.list(config, filter=filter, before=before, limit=limit))
    items = await asyncio.to_thread(_get_list)
    for item in items:
        yield item

PostgresSaver.aget_tuple = _aget_tuple
PostgresSaver.aput = _aput
PostgresSaver.aput_writes = _aput_writes
PostgresSaver.alist = _alist
# --------------------------------------


async def init_checkpointer(settings: Settings) -> PostgresSaver:
    """Initialize the PostgresSaver singleton. Idempotent — safe to call multiple times."""
    global _checkpointer, _conn
    if _checkpointer is not None:
        return _checkpointer

    dsn = settings.postgres_dsn
    logger.info("checkpointer_init_start", dsn=dsn.split("@")[-1])

    # Connect synchronously
    def _connect():
        return Connection.connect(
            dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
    conn = await asyncio.to_thread(_connect)
    _conn = conn

    saver = PostgresSaver(conn)
    await asyncio.to_thread(saver.setup)  # creates checkpoint tables if they don't exist

    _checkpointer = saver
    logger.info("checkpointer_init_success")
    return saver


def get_checkpointer() -> PostgresSaver | None:
    """Returns the initialized checkpointer, or None if not yet initialized."""
    return _checkpointer


async def close_checkpointer():
    """Graceful shutdown — close the checkpointer connection."""
    global _checkpointer, _conn
    if _conn is not None:
        try:
            await asyncio.to_thread(_conn.close)
        except Exception as e:
            logger.warning("checkpointer_close_error", error=str(e))
        _conn = None
    _checkpointer = None
    logger.info("checkpointer_closed")
