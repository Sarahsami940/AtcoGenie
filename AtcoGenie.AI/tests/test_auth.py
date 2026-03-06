"""
AtcoGenie AI Engine — Auth Middleware Tests
Tests for SecurityContext, CompositeRoleProfile, and Redis session retrieval.
"""

import pytest
from httpx import AsyncClient
import json

from app.security.context import (
    AccessLevel,
    CompositeRoleProfile,
    SecurityContext,
    SystemRole,
)
from app.cache.role_cache import RoleCache
from app.config import Settings


# --- Helpers ---

def _make_profile() -> CompositeRoleProfile:
    """Build a test profile with pharma and thirdparty access."""
    return CompositeRoleProfile(
        ad_user_id="sarah.sami",
        employee_id="EMP001",
        email="sarah.sami@atco.com",
        display_name="Sarah Sami",
        department="IT",
        roles={
            "pharma": SystemRole(
                system="pharma",
                access_level=AccessLevel.VIEWER,
                scope_id="EMP001",
                scope_column="HcmsEmployeeId",
            ),
            "thirdparty": SystemRole(
                system="thirdparty",
                access_level=AccessLevel.VIEWER,
                scope_id="EMP001",
                scope_column="employee_id",
            ),
        },
    )


# --- SecurityContext & CompositeRoleProfile ---

def test_accessible_systems():
    profile = _make_profile()
    accessible = profile.accessible_systems
    assert "pharma" in accessible
    assert "thirdparty" in accessible
    assert len(accessible) == 2


def test_has_access():
    profile = _make_profile()
    assert profile.has_access("pharma") is True
    assert profile.has_access("thirdparty") is True
    assert profile.has_access("sap") is False
    assert profile.has_access("nonexistent") is False


def test_get_scope_id():
    ctx = SecurityContext(
        user_id="sarah.sami",
        employee_id="EMP001",
        email="sarah.sami@atco.com",
        display_name="Sarah Sami",
        department="IT",
        role_profile=_make_profile(),
    )
    assert ctx.get_scope_id("pharma") == "EMP001"
    assert ctx.get_scope_column("pharma") == "HcmsEmployeeId"
    assert ctx.get_scope_id("sap") is None


def test_profile_cache_roundtrip():
    """CompositeRoleProfile should survive serialization to/from Redis dict."""
    original = _make_profile()
    cache_dict = original.to_cache_dict()
    restored = CompositeRoleProfile.from_cache_dict(cache_dict)

    assert restored.ad_user_id == original.ad_user_id
    assert restored.employee_id == original.employee_id
    assert restored.accessible_systems == original.accessible_systems
    assert restored.roles["pharma"].access_level == AccessLevel.VIEWER
    assert restored.roles["pharma"].scope_column == "HcmsEmployeeId"

@pytest.mark.asyncio
async def test_redis_session_lookup(test_settings: Settings):
    """Test that the role cache behaves correctly via Redis (mock or real) using the session token."""
    cache = RoleCache(test_settings)
    profile = _make_profile()
    
    # Store directly simulating the .NET backend action
    await cache.connect()
    if cache.redis:
        key = cache._key("test-session-123")
        await cache.redis.setex(key, 60, json.dumps(profile.to_cache_dict()))
        
        # Test retrieval
        retrieved = await cache.get_profile_by_session("test-session-123")
        assert retrieved is not None
        assert retrieved.employee_id == "EMP001"
        assert retrieved.has_access("thirdparty")
        
        # Test cache miss
        miss = await cache.get_profile_by_session("bad-session")
        assert miss is None
