"""
AtcoGenie AI Engine — Authentication Middleware

Reads the session ID from the Authorization header provided by the frontend.
Queries Redis to load the CompositeRoleProfile written by the .NET backend.
Hydrates the SecurityContext per request.
"""

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.security.context import SecurityContext
from app.cache.role_cache import RoleCache

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

# Module-level singletons
_role_cache: RoleCache | None = None

def _get_role_cache(settings: Settings) -> RoleCache:
    global _role_cache
    if not _role_cache:
        _role_cache = RoleCache(settings)
    return _role_cache

async def get_security_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> SecurityContext:
    """
    FastAPI dependency that extracts the session token,
    and hydrates the full SecurityContext directly from Redis.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_id = credentials.credentials
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Load full profile directly from Redis
    role_cache = _get_role_cache(settings)
    profile = await role_cache.get_profile_by_session(session_id)

    if not profile:
        logger.warning("invalid_or_expired_session", session_id=session_id)
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    from app.logging_config import request_id_var

    return SecurityContext(
        user_id=profile.ad_user_id,
        employee_id=profile.employee_id,
        email=profile.email,
        display_name=profile.display_name,
        department=profile.department,
        role_profile=profile,
        request_id=request_id_var.get(""),
    )
