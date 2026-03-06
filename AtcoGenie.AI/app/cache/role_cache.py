"""
AtcoGenie AI Engine — Role Profile Cache (Redis)

Caches CompositeRoleProfile in Redis to avoid re-querying
all 3 databases on every request. TTL: 15 minutes.
"""

import json
import redis.asyncio as aioredis
from app.config import Settings
from app.logging_config import get_logger
from app.security.context import CompositeRoleProfile

logger = get_logger(__name__)


class RoleCache:
    def __init__(self, settings: Settings):
        self.redis: aioredis.Redis | None = None
        self.ttl = settings.redis_role_cache_ttl
        self.settings = settings

    async def connect(self):
        if not self.redis:
            self.redis = aioredis.from_url(
                self.settings.redis_url,
                password=self.settings.redis_password or None,
                decode_responses=True,
            )

    async def close(self):
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    def _key(self, session_id: str) -> str:
        """The key format written by the .NET backend."""
        return f"atcogenie:session:{session_id}"

    async def get_profile_by_session(self, session_id: str) -> CompositeRoleProfile | None:
        """Retrieve cached profile using the session token. Returns None if expired or missing."""
        await self.connect()
        key = self._key(session_id)
        data = await self.redis.get(key)
        if not data:
            logger.info("role_cache_miss", session_id=session_id)
            return None

        logger.info("role_cache_hit", session_id=session_id)
        return CompositeRoleProfile.from_cache_dict(json.loads(data))

