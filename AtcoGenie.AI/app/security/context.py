"""
AtcoGenie AI Engine — Security Context & Role Models

Immutable dataclasses representing user identity, per-system roles,
and the composite role profile assembled during login.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AccessLevel(str, Enum):
    NO_ACCESS = "no_access"
    VIEWER = "viewer"
    MANAGER = "manager"
    ADMIN = "admin"


@dataclass(frozen=True)
class SystemRole:
    """Role for a single target system (Pharma, SAP, or Third-Party)."""
    system: str
    access_level: AccessLevel
    scope_id: str                       # employee_id, ad_username, etc.
    scope_column: str                   # Column name used for WHERE injection
    allowed_tables: tuple[str, ...] = ()
    company_codes: tuple[str, ...] = () # For multi-company filtering


@dataclass(frozen=True)
class CompositeRoleProfile:
    """
    Assembled from parallel role queries across all 3 databases.
    Cached in Redis with 15-min TTL. Referenced by JWT via cache key.
    """
    ad_user_id: str
    employee_id: str
    email: str
    display_name: str
    department: str
    roles: dict[str, SystemRole] = field(default_factory=dict)
    # Keys: "pharma", "sap", "thirdparty"

    @property
    def accessible_systems(self) -> list[str]:
        return [
            sys for sys, role in self.roles.items()
            if role.access_level != AccessLevel.NO_ACCESS
        ]

    def get_role(self, system: str) -> Optional[SystemRole]:
        return self.roles.get(system)

    def has_access(self, system: str) -> bool:
        role = self.roles.get(system)
        return role is not None and role.access_level != AccessLevel.NO_ACCESS

    def to_cache_dict(self) -> dict:
        return {
            "ad_user_id": self.ad_user_id,
            "employee_id": self.employee_id,
            "email": self.email,
            "display_name": self.display_name,
            "department": self.department,
            "roles": {
                sys: {
                    "system": role.system,
                    "access_level": role.access_level.value,
                    "scope_id": role.scope_id,
                    "scope_column": role.scope_column,
                    "allowed_tables": list(role.allowed_tables),
                    "company_codes": list(role.company_codes),
                }
                for sys, role in self.roles.items()
            },
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "CompositeRoleProfile":
        roles = {}
        for sys, rd in data.get("roles", {}).items():
            roles[sys] = SystemRole(
                system=rd["system"],
                access_level=AccessLevel(rd["access_level"]),
                scope_id=rd["scope_id"],
                scope_column=rd["scope_column"],
                allowed_tables=tuple(rd.get("allowed_tables", [])),
                company_codes=tuple(rd.get("company_codes", [])),
            )
        return cls(
            ad_user_id=data["ad_user_id"],
            employee_id=data["employee_id"],
            email=data["email"],
            display_name=data["display_name"],
            department=data["department"],
            roles=roles,
        )


@dataclass(frozen=True)
class SecurityContext:
    """
    Per-request security context injected into the LangChain agent.
    Built from JWT claims + cached CompositeRoleProfile.
    """
    user_id: str                        # AD username (e.g., "sarah.sami")
    employee_id: str                    # HCMS employee ID
    email: str
    display_name: str
    department: str
    role_profile: CompositeRoleProfile
    request_id: str = ""

    @property
    def accessible_systems(self) -> list[str]:
        return self.role_profile.accessible_systems

    def has_access(self, system: str) -> bool:
        return self.role_profile.has_access(system)

    def get_scope_id(self, system: str) -> Optional[str]:
        role = self.role_profile.get_role(system)
        return role.scope_id if role else None

    def get_scope_column(self, system: str) -> Optional[str]:
        role = self.role_profile.get_role(system)
        return role.scope_column if role else None
