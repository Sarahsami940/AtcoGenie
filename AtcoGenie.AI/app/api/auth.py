from fastapi import APIRouter, Depends
from typing import Any, Dict

from app.security.context import SecurityContext
from app.middleware.auth import get_security_context

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.get("/test", response_model=Dict[str, Any])
async def test_auth_context(
    context: SecurityContext = Depends(get_security_context)
) -> Dict[str, Any]:
    """
    Test endpoint to verify that the .NET session token correctly hydrates
    the SecurityContext from Redis.
    """
    return {
        "status": "authenticated",
        "user_id": context.user_id,
        "employee_id": context.employee_id,
        "email": context.email,
        "display_name": context.display_name,
        "department": context.department,
        "form_rights": [
            {
                "application_code": r.application_code,
                "form_id": r.form_id,
                "view_mode": r.view_mode
            }
            for r in context.role_profile.form_rights
        ]
    }
