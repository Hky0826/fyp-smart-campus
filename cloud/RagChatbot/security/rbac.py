"""
RBAC (Role-Based Access Control) for the RAG Chatbot.

Resolves a user's roles from the database and maps them to the
document access levels they are permitted to view. Role information
is NEVER taken from the request body — it is always resolved from
the trusted JWT and the backend database.
"""

from __future__ import annotations

import logging
from typing import List, Set

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Mapping from role_name (as stored in roles table) to the document
# access_level values the role is allowed to read.
# The hierarchy is cumulative: higher roles include all lower levels.
_ROLE_ACCESS_MAP: dict[str, List[str]] = {
    "STUDENT":  ["PUBLIC", "STUDENT"],
    "LECTURER": ["PUBLIC", "STUDENT", "LECTURER"],
    "STAFF":    ["PUBLIC", "STUDENT", "LECTURER"],
    "ADMIN":    ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"],
    "VISITOR":  ["PUBLIC"],
    # SUPER_ADMIN / SYSTEM_ADMIN / CONTENT_ADMIN are admin-portal roles;
    # they map to ADMIN tier document access.
    "SUPER_ADMIN":    ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"],
    "SYSTEM_ADMIN":   ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"],
    "CONTENT_ADMIN":  ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"],
}

# When a user has no recognized role, they get public-only access.
_DEFAULT_ACCESS: List[str] = ["PUBLIC"]


ROLE_PRIORITY_ORDER: List[str] = [
    "SUPER_ADMIN",
    "SYSTEM_ADMIN",
    "CONTENT_ADMIN",
    "ADMIN",
    "LECTURER",
    "STAFF",
    "STUDENT",
    "VISITOR",
]


def get_highest_role(roles: List[str]) -> str:
    """
    Find the highest role from a list/tuple of roles based on hierarchy.
    """
    if not roles:
        return "VISITOR"
    roles_upper = {role.upper() for role in roles}
    for role_name in ROLE_PRIORITY_ORDER:
        if role_name in roles_upper:
            return role_name
    return sorted(list(roles_upper))[0]


def get_user_roles(user_id: int, db: Session) -> List[str]:
    """
    Query the database to retrieve all role_names assigned to a user.

    Args:
        user_id: The authenticated user's ID (from the JWT payload).
        db: An active SQLAlchemy database session.

    Returns:
        A list of role_name strings (e.g. ["STUDENT"]).
    """
    # Import here to avoid circular import at module level
    from app.models.models import User

    user = db.query(User).filter_by(user_id=user_id, is_active=True).first()
    if not user:
        logger.warning("RBAC: user_id=%d not found or inactive.", user_id)
        return []

    roles = [role.role_name for role in user.roles]
    logger.debug("RBAC: user_id=%d has roles=%s", user_id, roles)
    return roles


def resolve_allowed_access_levels(roles: List[str]) -> List[str]:
    """
    Determine which document access_level values a user may view,
    given their list of role names.

    Args:
        roles: List of role names (e.g. ["STUDENT", "VISITOR"]).

    Returns:
        A deduplicated, sorted list of allowed access_level strings.
    """
    allowed: Set[str] = set()
    if roles:
        highest_role = get_highest_role(roles)
        levels = _ROLE_ACCESS_MAP.get(highest_role, [])
        allowed.update(levels)

    if not allowed:
        # Fall back to public-only access for unknown roles
        allowed.update(_DEFAULT_ACCESS)

    # Canonical ordering matches the DB ENUM ordering
    order = ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"]
    result = [level for level in order if level in allowed]
    logger.debug("RBAC: resolved access levels=%s for roles=%s", result, roles)
    return result



def get_allowed_access_levels_for_user(user_id: int, db: Session) -> List[str]:
    """
    Convenience function: resolves user roles from DB and returns allowed
    document access levels in one call.

    Args:
        user_id: Authenticated user ID from JWT.
        db: Active DB session.

    Returns:
        List of allowed access_level strings.
    """
    roles = get_user_roles(user_id, db)
    return resolve_allowed_access_levels(roles)
