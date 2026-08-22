"""
RBAC (Role-Based Access Control) for the RAG Chatbot.

Resolves a user's roles from the database and maps them to the
document allowed roles they are permitted to view. Role information
is NEVER taken from the request body — it is always resolved from
the trusted JWT and the backend database.
"""

from __future__ import annotations

import logging
from typing import List, Set

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ALL_CANONICAL_ROLES: List[str] = [
    "VISITOR",
    "STUDENT",
    "LECTURER",
    "STAFF",
    "ADMIN",
]

ADMIN_ROLES: Set[str] = {
    "ADMIN",
    "SUPER_ADMIN",
    "SYSTEM_ADMIN",
    "CONTENT_ADMIN",
}

# Base access when unauthenticated
VISITOR_ACCESS_LEVELS: List[str] = ["VISITOR"]


def get_user_roles(user_id: int | None, db: Session) -> List[str]:
    """
    Query the database to retrieve all role_names assigned to a user,
    always including 'VISITOR' baseline access.
    """
    if user_id is None:
        return list(VISITOR_ACCESS_LEVELS)

    from app.models.models import User

    user = db.query(User).filter_by(user_id=user_id, is_active=True).first()
    if not user:
        logger.warning("RBAC: user_id=%s not found or inactive; defaulting to VISITOR.", user_id)
        return list(VISITOR_ACCESS_LEVELS)

    user_roles = {str(role.role_name).upper() for role in user.roles}
    user_roles.add("VISITOR")

    # If user is any type of admin, grant full role set
    if user_roles & ADMIN_ROLES:
        user_roles.update(ALL_CANONICAL_ROLES)

    roles_list = sorted(list(user_roles))
    logger.debug("RBAC: user_id=%d resolved roles=%s", user_id, roles_list)
    return roles_list


def resolve_allowed_access_levels(roles: List[str]) -> List[str]:
    """
    Determine which document roles a user may view, given their list of role names.
    """
    roles_set = {str(r).upper() for r in (roles or [])}
    roles_set.add("VISITOR")

    if roles_set & ADMIN_ROLES:
        roles_set.update(ALL_CANONICAL_ROLES)

    return sorted(list(roles_set))


def get_allowed_access_levels_for_user(user_id: int | None, db: Session) -> List[str]:
    """
    Convenience function: resolves user roles from DB and returns allowed
    document access roles in one call.
    """
    return get_user_roles(user_id, db)
