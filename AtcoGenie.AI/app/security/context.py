"""
AtcoGenie AI Engine — Security Context & Role Models

Immutable dataclasses representing user identity, per-system roles,
and the composite role profile assembled during login.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass(frozen=True)
class UserFormRight:
    """A single row from imd_userformrights mapping to an application's form/report."""
    security_user_id: Optional[int]
    ccode: Optional[str]
    application_code: Optional[str]
    form_id: Optional[str]
    add_mode: Optional[bool]
    edit_mode: Optional[bool]
    view_mode: Optional[bool]
    delete_mode: Optional[bool]

@dataclass(frozen=True)
class CompositeRoleProfile:
    """
    Stored directly by the .NET Authentication endpoint into Redis.
    Contains all raw rights from the IMD DB so the AI can filter report access.
    """
    ad_user_id: str
    employee_id: str
    email: str
    display_name: str
    department: str
    form_rights: List[UserFormRight] = field(default_factory=list)

    def has_report_access(self, application_code: str, report_sp_name: str) -> bool:
        """
        Check if the user has 'ReportsMode' or 'ViewMode' for a specific stored procedure report.
        For Phase 1, the `form_id` usually matches the report name or SP alias.
        """
        for right in self.form_rights:
            if right.application_code and right.application_code.lower() == application_code.lower():
                # Compare form_id against the exact SP being called to verify access
                # Adjust string matching logic based on exact IMD mapping vs SP names
                if right.form_id and right.form_id.lower() == report_sp_name.lower():
                    # We assume true access if they have ViewMode
                    return right.view_mode is True
        return False

    def to_cache_dict(self) -> dict:
        return {
            "ad_user_id": self.ad_user_id,
            "employee_id": self.employee_id,
            "email": self.email,
            "display_name": self.display_name,
            "department": self.department,
            "form_rights": [
                {
                    "security_user_id": r.security_user_id,
                    "ccode": r.ccode,
                    "application_code": r.application_code,
                    "form_id": r.form_id,
                    "add_mode": r.add_mode,
                    "edit_mode": r.edit_mode,
                    "view_mode": r.view_mode,
                    "delete_mode": r.delete_mode
                } for r in self.form_rights
            ]
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "CompositeRoleProfile":
        rights = []
        for rd in data.get("form_rights", []):
            rights.append(UserFormRight(
                security_user_id=rd.get("security_user_id"),
                ccode=rd.get("ccode"),
                application_code=rd.get("application_code"),
                form_id=rd.get("form_id"),
                add_mode=rd.get("add_mode"),
                edit_mode=rd.get("edit_mode"),
                view_mode=rd.get("view_mode"),
                delete_mode=rd.get("delete_mode")
            ))
            
        return cls(
            ad_user_id=data.get("ad_user_id", ""),
            employee_id=data.get("employee_id", ""),
            email=data.get("email", ""),
            display_name=data.get("display_name", ""),
            department=data.get("department", "N/A"),
            form_rights=rights
        )

@dataclass(frozen=True)
class SecurityContext:
    """Per-request Context for LangChain filters."""
    user_id: str
    employee_id: str
    email: str
    display_name: str
    department: str
    role_profile: CompositeRoleProfile
    request_id: str = ""

    def has_report_access(self, application_code: str, report_sp_name: str) -> bool:
        return self.role_profile.has_report_access(application_code, report_sp_name)

