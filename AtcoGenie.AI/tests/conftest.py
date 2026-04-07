"""
AtcoGenie AI Engine — Test Fixtures
Shared fixtures for all test modules.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Override settings for testing — no real DB connections."""
    return Settings(
        app_env="testing",
        app_debug=True,
        llm_provider="openai",
        openai_api_key="test-key",
        pharma_db_host="",
        thirdparty_db_host="",
        redis_url="redis://localhost:6379/1",
        postgres_host="localhost",
        postgres_db="atcogenie_test",
        ad_server="",
        jwt_secret_key="test-secret-key-for-testing-only",
    )


@pytest.fixture
def app():
    """Create a fresh FastAPI app for each test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
