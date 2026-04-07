"""
AtcoGenie AI Engine — Database Pool Integration Tests
"""
import pytest
from app.database.manager import DatabaseManager
from app.config import Settings
import asyncio

@pytest.fixture
def mock_settings():
    return Settings(
        app_env="testing",
        pharma_db_host="mock_pharma_host",
        pharma_odbc_dsn="Driver={ODBC Driver 18 for SQL Server};Server=mock;Database=pharma;UID=test;PWD=test;Encrypt=No;",
        thirdparty_db_host="mock_tp_host",
        thirdparty_odbc_dsn="Driver={ODBC Driver 18 for SQL Server};Server=mock;Database=tp;UID=test;PWD=test;Encrypt=No;",
        postgres_host="mock_pg_host",
        postgres_dsn="postgresql://test:test@mock_pg_host:5432/test",
    )

@pytest.mark.asyncio
async def test_db_manager_initialization_failure_is_caught(mock_settings, monkeypatch):
    """Test that connection failures during async init are caught gracefully."""
    # We don't have a real database at 'mock_pharma_host', so initialization will throw an Exception.
    # The manager should log it rather than crashing the application startup!
    manager = DatabaseManager(mock_settings)
    
    # We patch aioodbc and asyncpg to raise Mock exceptions
    async def mock_fail(*args, **kwargs):
        raise ConnectionError("Mock Connection Failed")
    
    monkeypatch.setattr("aioodbc.create_pool", mock_fail)
    monkeypatch.setattr("asyncpg.create_pool", mock_fail)

    await manager.initialize()
    
    assert manager._is_initialized is True
    # The pools dict should be empty because everything failed
    assert len(manager._pools) == 0

