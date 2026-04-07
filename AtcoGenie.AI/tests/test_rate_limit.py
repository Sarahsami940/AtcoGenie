"""
AtcoGenie AI Engine — Rate Limiter Middleware Tests
"""
import pytest
from httpx import AsyncClient
import time

@pytest.mark.asyncio
async def test_rate_limiter_allows_requests(client: AsyncClient):
    # health endpoint is excluded from rate limiter
    response = await client.get("/api/v1/health")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_rate_limiter_blocks_excessive_requests(client: AsyncClient, monkeypatch):
    import fakeredis
    
    # Mock the aioredis.from_url to return a fakeredis instance
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr("app.middleware.rate_limit.aioredis.from_url", lambda *args, **kwargs: fake_redis)

    status_codes = []
    
    # Send 105 requests (limit is 100)
    for _ in range(105):
        response = await client.post("/chat") # missing endpoint, but it's okay because middleware intercepts
        status_codes.append(response.status_code)
        
    assert 429 in status_codes
    assert status_codes.count(429) >= 4 # at least the last few should be blocked
