"""
AtcoGenie AI Engine — Database Connection Manager

Manages lifecycle of parallel connection pools for:
1. Pharma CRM (MS SQL via aioodbc)
2. Third-Party (MS SQL via aioodbc)
3. IMD / Checkpointer (Postgres via asyncpg)
4. SAP HANA (sync connections wrapped in threads)
"""

import asyncio
from typing import Dict, Any, Optional
import aioodbc
import asyncpg
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)

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
                if hasattr(pool, 'close'):
                    pool.close()
                    await pool.wait_closed()
                elif hasattr(pool, 'terminate'):
                    await pool.terminate()
                logger.info("db_pool_closed", name=name)
            except Exception as e:
                logger.error("db_pool_close_error", name=name, error=str(e))
        
        self._pools.clear()
        self._is_initialized = False
        logger.info("db_manager_closed")

# Singleton instance access
_db_manager: Optional[DatabaseManager] = None

def get_db_manager(settings: Settings) -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(settings)
    return _db_manager
