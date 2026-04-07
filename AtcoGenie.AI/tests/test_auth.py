"""
AtcoGenie AI Engine — Auth Middleware Tests
Tests for SecurityContext, CompositeRoleProfile, and Redis session retrieval.
"""

import pytest
from httpx import AsyncClient
import json

from app.security.context import (
    CompositeRoleProfile,
    SecurityContext,
    UserFormRight,
)
from app.cache.role_cache import RoleCache
from app.config import Settings


# --- Helpers ---

def _make_profile() -> CompositeRoleProfile:
    """Build a test profile with specific form rights."""
    return CompositeRoleProfile(
        ad_user_id="sarah.sami",
        employee_id="EMP001",
        email="sarah.sami@atco.com",
        display_name="Sarah Sami",
        department="IT",
        form_rights=[
            UserFormRight(
                security_user_id=101,
                ccode="C001",
                application_code="PharmaCRM",
                form_id="usp_GetDoctorVisits",
                add_mode=False,
                edit_mode=False,
                view_mode=True,
                delete_mode=False
            ),
            UserFormRight(
                security_user_id=101,
                ccode="C001",
                application_code="PharmaCRM",
                form_id="usp_GetSalesData",
                add_mode=False,
                edit_mode=False,
                view_mode=False,
                delete_mode=False
            ),
        ],
    )


# --- SecurityContext & CompositeRoleProfile ---

def test_has_report_access():
    profile = _make_profile()
    # Should have access since view_mode is True
    assert profile.has_report_access("PharmaCRM", "usp_GetDoctorVisits") is True
    # Should not have access since view_mode is False
    assert profile.has_report_access("PharmaCRM", "usp_GetSalesData") is False
    # Should not have access to unknown app/form
    assert profile.has_report_access("UnknownApp", "usp_GetDoctorVisits") is False


def test_profile_cache_roundtrip():
    """CompositeRoleProfile should survive serialization to/from Redis dict."""
    original = _make_profile()
    cache_dict = original.to_cache_dict()
    restored = CompositeRoleProfile.from_cache_dict(cache_dict)

    assert restored.ad_user_id == original.ad_user_id
    assert restored.employee_id == original.employee_id
    assert len(restored.form_rights) == 2
    assert restored.form_rights[0].form_id == "usp_GetDoctorVisits"
    assert restored.form_rights[0].view_mode is True

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
        assert retrieved.has_report_access("PharmaCRM", "usp_GetDoctorVisits") is True
        
        # Test cache miss
        miss = await cache.get_profile_by_session("bad-session")
        assert miss is None

