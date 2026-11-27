"""Shared RBAC resolution service for Access Groups, Roles, and Individual Users.

Provides a single source of truth for resolving effective access policies on
campus Nodes (locations) and Edge Devices across:
- Cloud-to-edge sync payloads
- RBAC policy matrix and device detail APIs
- User effective-access calculation
- Campus wayfinding and floorplan visualization
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, TypedDict

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.models import (
    AccessGroup,
    AccessGroupRole,
    AccessGroupUser,
    DeviceAccessGroup,
    DeviceRBAC,
    DeviceUserAccess,
    NodeAccessGroup,
    NodeRBAC,
    NodeUserAccess,
)


class NodePolicy(TypedDict):
    group_ids: List[int]
    direct_role_ids: Set[int]
    group_role_ids: Set[int]
    effective_role_ids: Set[int]
    direct_user_ids: Set[int]
    group_user_ids: Set[int]
    effective_user_ids: Set[int]


class DevicePolicy(TypedDict):
    group_ids: List[int]
    direct_role_ids: Set[int]
    group_role_ids: Set[int]
    effective_role_ids: Set[int]
    direct_user_ids: Set[int]
    group_user_ids: Set[int]
    effective_user_ids: Set[int]
    uses_override: bool


def _safe_query_all(db: Session, model):
    """Query all rows, gracefully returning [] if a newly added table does not exist yet (e.g. partial test DBs)."""
    try:
        return db.query(model).all()
    except (OperationalError, ProgrammingError):
        db.rollback()
        return []


def _load_group_memberships(db: Session) -> tuple[Dict[int, Set[int]], Dict[int, Set[int]], Dict[int, str]]:
    group_roles: Dict[int, Set[int]] = {}
    group_users: Dict[int, Set[int]] = {}
    group_names: Dict[int, str] = {}

    for grp in _safe_query_all(db, AccessGroup):
        group_names[grp.group_id] = grp.group_name
    for gr in _safe_query_all(db, AccessGroupRole):
        group_roles.setdefault(gr.group_id, set()).add(gr.role_id)
    for gu in _safe_query_all(db, AccessGroupUser):
        group_users.setdefault(gu.group_id, set()).add(gu.user_id)

    return group_roles, group_users, group_names


def resolve_all_node_policies(db: Session) -> Dict[int, NodePolicy]:
    """Resolve direct, group-derived, and effective role/user policies for every node with any rule."""
    group_roles, group_users, _ = _load_group_memberships(db)

    node_groups: Dict[int, Set[int]] = {}
    for ng in _safe_query_all(db, NodeAccessGroup):
        node_groups.setdefault(ng.node_id, set()).add(ng.group_id)

    node_direct_roles: Dict[int, Set[int]] = {}
    for nr in _safe_query_all(db, NodeRBAC):
        node_direct_roles.setdefault(nr.node_id, set()).add(nr.role_id)

    node_direct_users: Dict[int, Set[int]] = {}
    for nu in _safe_query_all(db, NodeUserAccess):
        node_direct_users.setdefault(nu.node_id, set()).add(nu.user_id)

    all_node_ids = set(node_groups.keys()) | set(node_direct_roles.keys()) | set(node_direct_users.keys())
    policies: Dict[int, NodePolicy] = {}

    for node_id in all_node_ids:
        gids = sorted(node_groups.get(node_id, set()))
        d_roles = set(node_direct_roles.get(node_id, set()))
        d_users = set(node_direct_users.get(node_id, set()))

        g_roles: Set[int] = set()
        g_users: Set[int] = set()
        for gid in gids:
            g_roles.update(group_roles.get(gid, set()))
            g_users.update(group_users.get(gid, set()))

        policies[node_id] = NodePolicy(
            group_ids=gids,
            direct_role_ids=d_roles,
            group_role_ids=g_roles,
            effective_role_ids=d_roles | g_roles,
            direct_user_ids=d_users,
            group_user_ids=g_users,
            effective_user_ids=d_users | g_users,
        )

    return policies


def resolve_all_device_policies(db: Session) -> Dict[str, DevicePolicy]:
    """Resolve direct, group-derived, and effective role/user policies for every device with any rule."""
    group_roles, group_users, _ = _load_group_memberships(db)

    dev_groups: Dict[str, Set[int]] = {}
    for dg in _safe_query_all(db, DeviceAccessGroup):
        dev_groups.setdefault(dg.device_id, set()).add(dg.group_id)

    dev_direct_roles: Dict[str, Set[int]] = {}
    for dr in _safe_query_all(db, DeviceRBAC):
        dev_direct_roles.setdefault(dr.device_id, set()).add(dr.role_id)

    dev_direct_users: Dict[str, Set[int]] = {}
    for du in _safe_query_all(db, DeviceUserAccess):
        dev_direct_users.setdefault(du.device_id, set()).add(du.user_id)

    all_device_ids = set(dev_groups.keys()) | set(dev_direct_roles.keys()) | set(dev_direct_users.keys())
    policies: Dict[str, DevicePolicy] = {}

    for device_id in all_device_ids:
        gids = sorted(dev_groups.get(device_id, set()))
        d_roles = set(dev_direct_roles.get(device_id, set()))
        d_users = set(dev_direct_users.get(device_id, set()))

        g_roles: Set[int] = set()
        g_users: Set[int] = set()
        for gid in gids:
            g_roles.update(group_roles.get(gid, set()))
            g_users.update(group_users.get(gid, set()))

        uses_override = bool(gids or d_roles or d_users)
        policies[device_id] = DevicePolicy(
            group_ids=gids,
            direct_role_ids=d_roles,
            group_role_ids=g_roles,
            effective_role_ids=d_roles | g_roles,
            direct_user_ids=d_users,
            group_user_ids=g_users,
            effective_user_ids=d_users | g_users,
            uses_override=uses_override,
        )

    return policies


def resolve_node_effective_roles(db: Session, node_ids: Optional[Iterable[int]] = None) -> Dict[int, List[int]]:
    """Return sorted effective role_ids per node_id (direct NodeRBAC union NodeAccessGroup roles)."""
    policies = resolve_all_node_policies(db)
    if node_ids is not None:
        allowed = set(node_ids)
        return {nid: sorted(pol["effective_role_ids"]) for nid, pol in policies.items() if nid in allowed}
    return {nid: sorted(pol["effective_role_ids"]) for nid, pol in policies.items()}


def explain_user_access_for_target(
    *,
    user_id: int,
    user_role_ids: Set[int],
    role_name_map: Dict[int, str],
    group_ids: List[int],
    group_roles: Dict[int, Set[int]],
    group_users: Dict[int, Set[int]],
    group_names: Dict[int, str],
    direct_role_ids: Set[int],
    direct_user_ids: Set[int],
    scope_label: str,
) -> tuple[bool, Optional[str]]:
    """Return (granted, human_readable_reason) for a user against a resolved node or device target."""
    reasons: List[str] = []

    if user_id in direct_user_ids:
        reasons.append(f"direct user access ({scope_label})")

    direct_role_matches = sorted(user_role_ids & direct_role_ids)
    if direct_role_matches:
        names = ", ".join(role_name_map.get(rid, str(rid)) for rid in direct_role_matches)
        reasons.append(f"role {names} ({scope_label})")

    for gid in group_ids:
        gname = group_names.get(gid, f"Group #{gid}")
        g_user_match = user_id in group_users.get(gid, set())
        g_role_matches = sorted(user_role_ids & group_roles.get(gid, set()))
        if g_user_match:
            reasons.append(f"group '{gname}' (direct user, {scope_label})")
        if g_role_matches:
            names = ", ".join(role_name_map.get(rid, str(rid)) for rid in g_role_matches)
            reasons.append(f"group '{gname}' (role {names}, {scope_label})")

    if reasons:
        return True, "Allowed via " + "; ".join(reasons)
    return False, None
