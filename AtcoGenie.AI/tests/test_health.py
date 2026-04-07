"""
AtcoGenie AI Engine — Health Endpoint Tests
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert "timestamp" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_health_reports_all_services(client: AsyncClient):
    response = await client.get("/api/v1/health")
    data = response.json()
    services = data["services"]
    expected_services = [
        "redis",
        "postgres_checkpointer",
        "postgres_imd",
        "pharma_crm",
        "thirdparty",
    ]
    for svc in expected_services:
        assert svc in services, f"Missing service: {svc}"
        assert "status" in services[svc]


@pytest.mark.asyncio
async def test_health_includes_request_id_header(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 8
