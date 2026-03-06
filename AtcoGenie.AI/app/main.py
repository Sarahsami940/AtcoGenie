"""
AtcoGenie AI Engine — FastAPI Application Entry Point

This is the main application file. It:
- Configures CORS for React frontend communication
- Sets up structured logging with correlation IDs
- Manages lifespan events (startup/shutdown for DB pools, Redis, Agent)
- Registers API routers
- Injects request-scoped correlation IDs via middleware
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.rate_limit import RateLimiterMiddleware

from app.config import get_settings
from app.logging_config import setup_logging, get_logger, generate_request_id, request_id_var
from app.api import health


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Startup: Initialize DB pools, Redis, LangChain agent.
    Shutdown: Close all connections gracefully.
    """
    settings = get_settings()
    logger.info(
        "atcogenie_ai_starting",
        environment=settings.app_env,
        host=settings.app_host,
        port=settings.app_port,
        llm_provider=settings.llm_provider,
    )

    # --- STARTUP ---
    # 1. Initialize Database Manager (Pools)
    from app.database.manager import get_db_manager
    db_manager = get_db_manager(settings)
    await db_manager.initialize()
    app.state.db_manager = db_manager

    # 2. Redis Connection (for caching)
    from app.cache.role_cache import RoleCache
    role_cache = RoleCache(settings)
    await role_cache.connect()
    app.state.role_cache = role_cache

    logger.info("atcogenie_ai_ready", status="all_services_initialized")

    yield  # Application runs here

    # --- SHUTDOWN ---
    logger.info("atcogenie_ai_shutdown", status="graceful")

    # Close DB pools
    if hasattr(app.state, "db_manager"):
        await app.state.db_manager.close()

    # Close Redis
    if hasattr(app.state, "role_cache"):
        await app.state.role_cache.close()

    logger.info("atcogenie_ai_shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    setup_logging(
        log_level=settings.app_log_level,
        json_format=settings.is_production,
    )

    app = FastAPI(
        title="AtcoGenie AI Engine",
        description="Multi-database enterprise chatbot powered by LangChain 1.0",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Rate Limiting ---
    app.add_middleware(
        RateLimiterMiddleware,
        settings=settings,
        max_requests=100,
        window_seconds=60,
    )

    # --- Request ID Middleware ---
    @app.middleware("http")
    async def add_request_id_middleware(request: Request, call_next):
        req_id = generate_request_id()
        request_id_var.set(req_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    # --- Routers ---
    app.include_router(health.router)
    # TODO [Module 9]: app.include_router(chat.router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
        log_level=settings.app_log_level.lower(),
    )
