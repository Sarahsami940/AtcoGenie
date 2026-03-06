"""
AtcoGenie AI Engine — Rate Limiting Middleware

Implements a Redis-backed rolling-window rate limiter per user.
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as aioredis
import time

from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)

class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.settings = settings
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis: aioredis.Redis | None = None

    async def _get_redis(self):
        if not self.redis:
            self.redis = aioredis.from_url(
                self.settings.redis_url,
                password=self.settings.redis_password or None,
                decode_responses=True,
            )
        return self.redis

    async def dispatch(self, request: Request, call_next):
        # Allow health checks and unauthenticated endpoints
        if request.url.path.startswith("/api/v1/health") or request.url.path.startswith("/api/v1/auth"):
            return await call_next(request)

        # Attempt to get user identity from Authorization header
        auth_header = request.headers.get("Authorization")
        client_ip = request.client.host if request.client else "unknown"
        
        # We group by user if auth header exists, else IP
        identity = client_ip
        if auth_header and auth_header.startswith("Bearer "):
            # For rate limiting purposes, extract token to hash or take first N chars
            token = auth_header.split(" ")[1]
            identity = token[-10:] # Last 10 chars as unique identity proxy 

        key = f"atcogenie:ratelimit:{identity}"
        
        try:
            redis_client = await self._get_redis()
            current_time = int(time.time())
            
            # Redis Pipeline for atomic ops
            async with redis_client.pipeline(transaction=True) as pipe:
                # Add current request timestamp
                pipe.zadd(key, {str(current_time): current_time})
                # Remove requests older than window
                pipe.zremrangebyscore(key, 0, current_time - self.window_seconds)
                # Count remaining requests
                pipe.zcard(key)
                # Set TTL to clean up old keys
                pipe.expire(key, self.window_seconds)
                
                _, _, request_count, _ = await pipe.execute()

            if request_count > self.max_requests:
                logger.warning("rate_limit_exceeded", identity=identity, count=request_count)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."},
                    headers={"Retry-After": str(self.window_seconds)}
                )

        except Exception as e:
            # Fail open if Redis is down
            logger.error("rate_limit_error", error=str(e))
        
        return await call_next(request)
