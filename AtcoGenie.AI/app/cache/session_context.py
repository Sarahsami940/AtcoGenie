"""
AtcoGenie AI Engine — Session Context Cache (Redis)

Stores active conversational context per chat session:
- last_intent: what the user was doing (e.g., "product_analysis", "team_comparison")
- last_target_system: which tool/SP was last routed to
- resolved_entities: extracted entities from tool results (team names, product names, date ranges)

TTL: 30 minutes (matches session inactivity timeout).
"""

import json
import redis.asyncio as aioredis
from typing import Optional
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class SessionContext:
    """Lightweight data class for per-session conversational context."""

    def __init__(
        self,
        last_intent: str = "",
        last_target_system: str = "",
        resolved_entities: dict | None = None,
        message_count: int = 0,
        summary: str = "",
    ):
        self.last_intent = last_intent
        self.last_target_system = last_target_system
        self.resolved_entities = resolved_entities or {}
        self.message_count = message_count
        self.summary = summary  # rolling summary for long sessions

    def to_dict(self) -> dict:
        return {
            "last_intent": self.last_intent,
            "last_target_system": self.last_target_system,
            "resolved_entities": self.resolved_entities,
            "message_count": self.message_count,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionContext":
        return cls(
            last_intent=data.get("last_intent", ""),
            last_target_system=data.get("last_target_system", ""),
            resolved_entities=data.get("resolved_entities", {}),
            message_count=data.get("message_count", 0),
            summary=data.get("summary", ""),
        )


class SessionContextCache:
    """Redis-backed per-session context store for multi-turn conversations."""

    def __init__(self, settings: Settings):
        self.redis: aioredis.Redis | None = None
        self.ttl = settings.redis_session_ttl  # 1800s = 30 min
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
        return f"atcogenie:ctx:{session_id}"

    async def get(self, session_id: str) -> SessionContext:
        """Load session context from Redis. Returns empty context if missing."""
        if not session_id:
            return SessionContext()
        try:
            await self.connect()
            data = await self.redis.get(self._key(session_id))
            if not data:
                return SessionContext()
            return SessionContext.from_dict(json.loads(data))
        except Exception as e:
            logger.warning("session_context_load_failed", session_id=session_id, error=str(e))
            return SessionContext()

    async def save(self, session_id: str, ctx: SessionContext):
        """Persist session context to Redis with TTL refresh."""
        if not session_id:
            return
        try:
            await self.connect()
            await self.redis.setex(
                self._key(session_id),
                self.ttl,
                json.dumps(ctx.to_dict()),
            )
        except Exception as e:
            logger.warning("session_context_save_failed", session_id=session_id, error=str(e))

    async def update_after_turn(
        self,
        session_id: str,
        intent: str = "",
        target_system: str = "",
        entities: dict | None = None,
        summary: str = "",
    ):
        """Update context after a completed turn. Merges entities additively."""
        ctx = await self.get(session_id)
        if intent:
            ctx.last_intent = intent
        if target_system:
            ctx.last_target_system = target_system
        if entities:
            ctx.resolved_entities.update(entities)
        if summary:
            ctx.summary = summary
        ctx.message_count += 1
        await self.save(session_id, ctx)

    async def delete(self, session_id: str):
        """Clear session context (on session delete)."""
        if not session_id:
            return
        try:
            await self.connect()
            await self.redis.delete(self._key(session_id))
        except Exception:
            pass
