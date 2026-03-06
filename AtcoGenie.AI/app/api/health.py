"""
AtcoGenie AI Engine — Health Check Endpoint
Reports per-database and per-service connectivity status.
"""

from fastapi import APIRouter, Depends, Request
from app.config import Settings, get_settings
from app.logging_config import get_logger
import asyncio
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1", tags=["Health"])
logger = get_logger(__name__)


async def _check_redis(settings: Settings) -> dict:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        return {"status": "healthy", "latency_ms": 0}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_postgres(dsn: str, name: str) -> dict:
    try:
        import asyncpg

        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5.0)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_pharma(settings: Settings) -> dict:
    if not settings.pharma_db_host:
        return {"status": "not_configured"}
    try:
        import aioodbc

        conn = await asyncio.wait_for(
            aioodbc.connect(dsn=settings.pharma_odbc_dsn), timeout=5.0
        )
        cursor = await conn.cursor()
        await cursor.execute("SELECT 1")
        await cursor.close()
        await conn.close()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_sap(settings: Settings) -> dict:
    if not settings.sap_db_host:
        return {"status": "not_configured"}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from hdbcli import dbapi

        def _connect():
            conn = dbapi.connect(
                address=settings.sap_db_host,
                port=settings.sap_db_port,
                user=settings.sap_db_user,
                password=settings.sap_db_password,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM DUMMY")
            cursor.close()
            conn.close()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            await asyncio.wait_for(
                loop.run_in_executor(executor, _connect), timeout=5.0
            )
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_thirdparty(settings: Settings) -> dict:
    if not settings.thirdparty_db_host:
        return {"status": "not_configured"}
    try:
        import aioodbc

        conn = await asyncio.wait_for(
            aioodbc.connect(dsn=settings.thirdparty_odbc_dsn), timeout=5.0
        )
        cursor = await conn.cursor()
        await cursor.execute("SELECT 1")
        await cursor.close()
        await conn.close()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/health")
async def health_check(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """
    Comprehensive health check — reports status of every service dependency.
    Probes using app-level connection pools if available.
    """
    # 1. Redis check
    try:
        role_cache = getattr(request.app.state, "role_cache", None)
        if role_cache and role_cache.redis:
            await role_cache.redis.ping()
            redis_status = {"status": "healthy", "latency_ms": 0}
        else:
            redis_status = await _check_redis(settings)
    except Exception as e:
        redis_status = {"status": "unhealthy", "error": str(e)}

    # 2. Database manager checks
    db_manager = getattr(request.app.state, "db_manager", None)
    
    async def _probe_pool(name: str, fallback_dsn: str = "") -> dict:
        if db_manager:
            pool = db_manager.get_pool(name)
            if pool:
                try:
                    if name == "postgres":
                        async with pool.acquire() as conn:
                            await conn.fetchval("SELECT 1")
                    else:
                        async with pool.acquire() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute("SELECT 1")
                    return {"status": "healthy"}
                except Exception as e:
                    return {"status": "unhealthy", "error": f"Pool probe failed: {str(e)}"}
        
        # Fallback to manual check
        if name == "postgres":
            return await _check_postgres(fallback_dsn, name)
        elif name == "pharma":
            return await _check_pharma(settings)
        elif name == "thirdparty":
            return await _check_thirdparty(settings)
        return {"status": "unhealthy", "error": f"Unknown pool or service: {name}"}

    results = await asyncio.gather(
        _probe_pool("postgres", settings.postgres_dsn), # checkpointer
        _check_postgres(settings.imd_dsn, "imd"),       # imd (manual check is fine for now)
        _probe_pool("pharma"),
        _check_sap(settings),
        _probe_pool("thirdparty"),
        return_exceptions=True,
    )

    def _safe(result) -> dict:
        if isinstance(result, Exception):
            return {"status": "error", "error": str(result)}
        return result

    services = {
        "redis": redis_status,
        "postgres_checkpointer": _safe(results[0]),
        "postgres_imd": _safe(results[1]),
        "pharma_crm": _safe(results[2]),
        "sap_hana": _safe(results[3]),
        "thirdparty": _safe(results[4]),
    }

    all_healthy = all(
        s.get("status") in ("healthy", "not_configured") for s in services.values()
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "environment": settings.app_env,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }
