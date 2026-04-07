"""
AtcoGenie AI Engine — User Context Resolver

Resolves runtime user details (TeamIDs, Role) from PharmaCRM 
via helper SPs and caches them in Redis for the session duration.
"""

import json
from typing import Optional, List, Dict
from dataclasses import dataclass, field

from app.database.manager import DatabaseManager
from app.cache.role_cache import RoleCache
from app.security.context import SecurityContext
from app.logging_config import get_logger

logger = get_logger(__name__)

CACHE_PREFIX = "atcogenie:userctx"
CACHE_TTL = 900  # 15 minutes


@dataclass
class UserTeam:
    team_id: str
    team_name: str


@dataclass
class ResolvedUserContext:
    """Runtime-resolved user context with teams and role."""
    employee_id: str
    user_role: str  # "Admin" or specific role
    teams: List[UserTeam] = field(default_factory=list)
    is_admin: bool = False

    @property
    def team_ids_csv(self) -> str:
        """Returns comma-separated team IDs for SP parameters."""
        return ",".join(t.team_id for t in self.teams)

    @property
    def team_names(self) -> List[str]:
        return [t.team_name for t in self.teams]

    def get_team_id_by_name(self, name: str) -> Optional[str]:
        """Fuzzy match a team name from user prompt to a TeamID."""
        name_lower = name.strip().lower()
        for t in self.teams:
            if t.team_name.strip().lower() == name_lower:
                return t.team_id
        # Partial match fallback
        for t in self.teams:
            if name_lower in t.team_name.strip().lower():
                return t.team_id
        return None

    def to_cache_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "user_role": self.user_role,
            "is_admin": self.is_admin,
            "teams": [{"team_id": t.team_id, "team_name": t.team_name} for t in self.teams]
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "ResolvedUserContext":
        teams = [UserTeam(team_id=t["team_id"], team_name=t["team_name"]) for t in data.get("teams", [])]
        return cls(
            employee_id=data.get("employee_id", ""),
            user_role=data.get("user_role", ""),
            is_admin=data.get("is_admin", False),
            teams=teams
        )


async def resolve_user_context(
    security_context: SecurityContext,
    db_manager: DatabaseManager,
    role_cache: Optional[RoleCache] = None,
) -> ResolvedUserContext:
    """
    Resolves TeamIDs and UserRole for the authenticated user.
    
    Flow:
    1. Check Redis cache for previously resolved context
    2. If miss, call Sp_GetEmployeeWiseTeam and SP_GetRole
    3. Cache the result and return
    """
    emp_id = security_context.employee_id
    cache_key = f"{CACHE_PREFIX}:{emp_id}"

    # 1. Try cache first
    if role_cache and role_cache.redis:
        try:
            cached = await role_cache.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.info("user_context_cache_hit", employee_id=emp_id)
                return ResolvedUserContext.from_cache_dict(data)
        except Exception as e:
            logger.warning("user_context_cache_read_error", error=str(e))

    # 2. Resolve from Database
    logger.info("user_context_resolving", employee_id=emp_id)

    # 2a. Get Teams
    teams: List[UserTeam] = []
    try:
        team_rows = await db_manager.execute_sp("pharma", "Sp_GetEmployeeWiseTeam", emp_id)
        for row in team_rows:
            tid = str(row.get("TeamID", row.get("teamid", row.get("TeamId", ""))))
            tname = str(row.get("TeamName", row.get("teamname", row.get("Team_Name", ""))))
            if tid:
                teams.append(UserTeam(team_id=tid, team_name=tname))
        logger.info("user_teams_resolved", employee_id=emp_id, team_count=len(teams))
    except Exception as e:
        logger.error("user_teams_resolve_error", employee_id=emp_id, error=str(e))

    # 2b. Get Role
    user_role = "Normal"
    ccode = "1"  # Default company code
    # Try to get CCode from form_rights
    if security_context.role_profile.form_rights:
        first_right = security_context.role_profile.form_rights[0]
        if first_right.ccode:
            ccode = first_right.ccode

    try:
        role_rows = await db_manager.execute_sp(
            "pharma", "SP_GetRole",
            int(ccode),                   # @CompanyId
            security_context.user_id,     # @UserId
            int(emp_id),                  # @EmpID
            0,                            # @DesgID (optional, skipped)
            ""                            # @DBName (unused)
        )
        if role_rows:
            # The SP should return a column with the role name
            first_row = role_rows[0]
            # Try common column names
            for col in ["UserRole", "userrole", "Role", "role", "RoleName", "rolename"]:
                if col in first_row:
                    user_role = str(first_row[col])
                    break
        logger.info("user_role_resolved", employee_id=emp_id, role=user_role, raw_rows=str(role_rows[:1] if role_rows else []))
    except Exception as e:
        logger.error("user_role_resolve_error", employee_id=emp_id, error=str(e))

    # Strict match — roles are system-configured, no ambiguity expected
    is_admin = user_role.strip().lower() == "admin"

    result = ResolvedUserContext(
        employee_id=emp_id,
        user_role=user_role,
        teams=teams,
        is_admin=is_admin
    )

    # 3. Cache the result
    if role_cache and role_cache.redis:
        try:
            await role_cache.redis.setex(cache_key, CACHE_TTL, json.dumps(result.to_cache_dict()))
            logger.info("user_context_cached", employee_id=emp_id)
        except Exception as e:
            logger.warning("user_context_cache_write_error", error=str(e))

    return result
