"""
AtcoGenie AI Engine — Database Connection Manager

Manages lifecycle of parallel connection pools for:
1. Pharma CRM (MS SQL via aioodbc)
2. Third-Party (MS SQL via aioodbc)
3. IMD / Checkpointer (Postgres via asyncpg)
4. SAP HANA (sync connections wrapped in threads)
"""

import asyncio
import threading
from contextvars import ContextVar
from typing import Dict, Any, Optional
import aioodbc
import asyncpg
import pyodbc
from app.config import Settings
from app.logging_config import get_logger
logger = get_logger(__name__)

# Per-request cancellation signal — set this threading.Event to abort the
# running execute_sp_sync thread without waiting for the full query to finish.
_cancel_event: ContextVar[threading.Event | None] = ContextVar("db_cancel_event", default=None)


def set_cancel_event(evt: threading.Event) -> None:
    """Bind a cancel event to the current async context (call once per request)."""
    _cancel_event.set(evt)


def get_cancel_event() -> threading.Event | None:
    return _cancel_event.get()

class DatabaseManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pools: Dict[str, Any] = {}
        self._is_initialized = False

    async def initialize(self):
        """Initialize all configured database pools in parallel."""
        if self._is_initialized:
            return

        logger.info("db_manager_initializing")
        
        tasks = []
        
        # 1. Pharma CRM Pool
        if self.settings.pharma_db_host:
            tasks.append(self._init_odbc_pool("pharma", self.settings.pharma_odbc_dsn, 
                                            self.settings.pharma_pool_min, self.settings.pharma_pool_max))
        
        # 2. Third-Party Pool
        if self.settings.thirdparty_db_host:
            tasks.append(self._init_odbc_pool("thirdparty", self.settings.thirdparty_odbc_dsn,
                                            self.settings.thirdparty_pool_min, self.settings.thirdparty_pool_max))
        
        # 3. IMD / Checkpointer Pool
        if self.settings.postgres_host:
            tasks.append(self._init_postgres_pool("postgres", self.settings.postgres_dsn))

        # Run all initializations
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, Exception):
                logger.error("db_pool_init_failed", error=str(res))

        self._is_initialized = True
        logger.info("db_manager_initialized", active_pools=list(self._pools.keys()))

    async def _init_odbc_pool(self, name: str, dsn: str, min_size: int, max_size: int):
        """Initialize an aioodbc connection pool."""
        try:
            logger.info("init_odbc_pool_start", name=name)
            # aioodbc creates a pool of connections
            pool = await aioodbc.create_pool(
                dsn=dsn,
                minsize=min_size,
                maxsize=max_size,
                autocommit=True
            )
            self._pools[name] = pool
            logger.info("init_odbc_pool_success", name=name)
        except Exception as e:
            logger.error("init_odbc_pool_error", name=name, error=str(e))
            raise

    async def _init_postgres_pool(self, name: str, dsn: str):
        """Initialize an asyncpg connection pool."""
        try:
            logger.info("init_postgres_pool_start", name=name)
            pool = await asyncpg.create_pool(dsn=dsn)
            self._pools[name] = pool
            logger.info("init_postgres_pool_success", name=name)
        except Exception as e:
            logger.error("init_postgres_pool_error", name=name, error=str(e))
            raise

    def get_pool(self, name: str):
        """Get a specific connection pool by name."""
        return self._pools.get(name)

    async def close(self):
        """Gracefully close all connection pools."""
        logger.info("db_manager_closing")
        
        for name, pool in self._pools.items():
            try:
                # Close depending on pool type
                if hasattr(pool, 'close'):
                    pool.close() # asyncpg
                    await pool.wait_closed()
                elif hasattr(pool, 'terminate'):
                    await pool.terminate() # aioodbc handles terminate internally? wait
                logger.info("db_pool_closed", name=name)
            except Exception as e:
                logger.error("db_pool_close_error", name=name, error=str(e))
        
        self._pools.clear()
        self._is_initialized = False
        logger.info("db_manager_closed")

    async def execute_sp(self, pool_name: str, sp_name: str, *args) -> list[dict]:
        """
        Executes a stored procedure securely via parameterized inputs.
        Returns a list of dictionaries mapping column name -> value.
        
        Handles multi-result-set SPs by navigating through result sets
        and returning the first one that contains actual row data.
        """
        pool = self._pools.get(pool_name)
        if not pool:
            raise ValueError(f"Database pool '{pool_name}' is not initialized.")

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                placeholders = ", ".join(["?"] * len(args))
                # SET NOCOUNT ON suppresses intermediate row-count messages
                # that can cause "No results" errors with pyodbc
                query = f"SET NOCOUNT ON; EXEC {sp_name} {placeholders}"
                
                logger.debug("executing_sp", sp=sp_name, args=args)
                await cur.execute(query, *args)
                
                # Navigate through result sets to find one with actual data
                MAX_ROWS = 100_000  # Safety cap — increased to 100k, avoids OOM on 2M+ row queries
                while True:
                    if cur.description:
                        columns = [column[0] for column in cur.description]
                        rows = await cur.fetchmany(MAX_ROWS)
                        if rows:
                            truncated = len(rows) == MAX_ROWS
                            logger.info(
                                "sp_result", sp=sp_name,
                                row_count=len(rows), columns=len(columns),
                                truncated=truncated
                            )
                            result = [dict(zip(columns, row)) for row in rows]
                            if truncated:
                                # Append a sentinel so the summarizer can note the cap
                                result.append({"__truncated__": True, "__cap__": MAX_ROWS})
                            return result

                    # Try next result set
                    has_next = await cur.nextset()
                    if not has_next:
                        break

                return []

    async def execute_sp_sync(self, pool_name: str, sp_name: str, *args,
                              batch_size: int = 10_000) -> tuple[list[str], list[tuple]]:
        """
        Executes a stored procedure using SYNC pyodbc in a thread.
        Returns (columns, all_rows) as a tuple.

        Uses a two-step approach:
        1. SET NOCOUNT ON (separate execute)
        2. EXEC sp_name args
        This prevents the ODBC driver from hanging on intermediate
        row-count messages generated by INSERT INTO #temp inside SPs.
        """
        settings = self.settings
        dsn = getattr(settings, f"{pool_name}_odbc_dsn", None)
        if not dsn:
            raise ValueError(f"No ODBC DSN configured for pool '{pool_name}'")

        def _run():
            from app.agent.langfuse_context import log_db_query_span, finish_db_query_span
            
            cancel_evt = get_cancel_event()  # thread-safe read from ContextVar copy
            conn = pyodbc.connect(dsn, timeout=60, autocommit=True)
            conn.timeout = 120  # 2-minute command timeout; prevents 8-min TCP hangs on heavy queries
            span_id = ""
            error_msg = None
            try:
                cur = conn.cursor()
                cur.timeout = 120  # 2-min query execution timeout (cursor-level, more reliable than conn.timeout)
                # Step 1: suppress intermediate row-count messages
                cur.execute("SET NOCOUNT ON")
                # Step 2: execute the SP with inline args (safe — values come from our code, not user input)
                arg_strs = []
                for a in args:
                    if isinstance(a, str):
                        arg_strs.append(f"'{a}'")
                    else:
                        arg_strs.append(str(a))
                sql = f"EXEC {sp_name} {', '.join(arg_strs)}"
                logger.info("execute_sp_sync_start", sp=sp_name, sql=sql[:200])
                
                # Create Langfuse span
                span_id = log_db_query_span(sp_name, sql, arg_strs)

                cur.execute(sql)

                # Collect all result sets; use the FIRST non-empty RS.
                # For Sp_PharmaCRM_SVT:
                #   RS0 = monthly totals (MonthYear | Units | Amount | PUnits | PAmount)
                #         12 rows, clear month-year labels e.g. "Sep 25" — best for revenue queries.
                #   RS1 = prior-period totals
                #   RS2 = cumulative totals
                #   RS3 = product-by-month pivot (Product | Jan | ... | Dec)
                #         Columns have NO year context; AI cannot distinguish Jan 2025 from Jan 2026.
                # NOTE: Customer Sales SP RS0 also contains the analytically relevant data.
                # We intentionally do NOT prefer product RS here — use first non-empty.
                fallback_columns: list[str] = []
                fallback_rows: list = []

                rs_index = 0
                while True:
                    if cancel_evt and cancel_evt.is_set():
                        logger.info("execute_sp_sync_cancelled", sp=sp_name, rows_so_far=len(fallback_rows))
                        try:
                            cur.cancel()
                        except Exception:
                            pass
                        raise asyncio.CancelledError("DB query cancelled by client disconnect")

                    if cur.description:
                        rs_cols = [c[0] for c in cur.description]
                        rs_rows = []
                        while True:
                            batch = cur.fetchmany(batch_size)
                            if not batch:
                                break
                            rs_rows.extend(batch)

                        # Keep the first non-empty RS
                        if not fallback_rows and rs_rows:
                            fallback_columns = rs_cols
                            fallback_rows = rs_rows
                            logger.debug("execute_sp_sync_selected_rs", rs=rs_index,
                                         cols=rs_cols, rows=len(rs_rows))

                    rs_index += 1
                    if not cur.nextset():
                        break

                columns = fallback_columns
                all_rows = fallback_rows

                logger.info("execute_sp_sync_done", sp=sp_name,
                            rows=len(all_rows), cols=len(columns),
                            selected_rs="rs0" if all_rows else "empty")

                if span_id:
                    finish_db_query_span(span_id, output_data={"rows_returned": len(all_rows), "columns": len(columns)})

                return columns, all_rows
            except Exception as e:
                error_msg = str(e)
                if span_id:
                    finish_db_query_span(span_id, error=error_msg)
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def execute_sp_stream(self, pool_name: str, sp_name: str, *args, chunk_size: int = 50000):
        """
        [LEGACY — kept for backward compat]
        Executes a stored procedure and yields chunks of data as raw tuples.
        WARNING: may hang on large result sets. Prefer execute_sp_sync.
        """
        pool = self._pools.get(pool_name)
        if not pool:
            raise ValueError(f"Database pool '{pool_name}' is not initialized.")

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                placeholders = ", ".join(["?"] * len(args))
                query = f"SET NOCOUNT ON; EXEC {sp_name} {placeholders}"
                
                logger.debug("executing_sp_stream", sp=sp_name, args=args)
                await cur.execute(query, *args)
                
                while True:
                    if cur.description:
                        columns = [column[0] for column in cur.description]
                        while True:
                            rows = await cur.fetchmany(chunk_size)
                            if not rows:
                                break
                            yield columns, rows
                        return

                    has_next = await cur.nextset()
                    if not has_next:
                        break

    async def execute_raw(self, pool_name: str, query: str, *args) -> list[dict]:
        """
        Executes a raw parameterized SELECT query.
        Returns a list of dicts mapping column name -> value.
        Used for simple lookups (e.g. product name search) that don't need SP handling.
        """
        pool = self._pools.get(pool_name)
        if not pool:
            raise ValueError(f"Database pool '{pool_name}' is not initialized.")

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, *args)
                if cur.description:
                    columns = [col[0] for col in cur.description]
                    rows = await cur.fetchall()
                    return [dict(zip(columns, row)) for row in rows]
                return []

# Singleton instance access
_db_manager: Optional[DatabaseManager] = None

def get_db_manager(settings: Settings) -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(settings)
    return _db_manager
