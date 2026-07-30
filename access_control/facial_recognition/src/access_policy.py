"""Fail-closed local authorization for physical access decisions.

The edge must be able to decide access without asking the cloud.  This module
keeps that decision deliberately small and deterministic so it can also be
tested without camera/model dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional


MAX_POLICY_AGE_SECONDS = 300


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    node_id: Optional[int]
    policy_version: Optional[str]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_access(
    *,
    user_id: int | str | None,
    is_active: bool,
    user_role_ids: Iterable[int | str] | None,
    allowed_role_ids: Iterable[int | str] | None,
    node_id: int | None,
    policy_version: str | None,
    policy_synced_at: datetime | None,
    now: datetime | None = None,
    visitor_start: datetime | None = None,
    visitor_expiry: datetime | None = None,
    max_age_seconds: int = MAX_POLICY_AGE_SECONDS,
) -> AccessDecision:
    """Evaluate a local policy snapshot and return an auditable decision.

    Missing or malformed policy data is never interpreted as an allow.  A
    visitor window is optional for ordinary users, but if either boundary is
    present both must be valid and the current time must be inside the window.
    """

    if user_id is None or not is_active:
        return AccessDecision(False, "inactive_or_unknown_user", node_id, policy_version)
    if node_id is None or not policy_version or not policy_version.strip():
        return AccessDecision(False, "missing_policy_identity", node_id, policy_version)
    if policy_synced_at is None:
        return AccessDecision(False, "missing_policy_timestamp", node_id, policy_version)
    try:
        current = _utc(now or datetime.now(timezone.utc))
        synced = _utc(policy_synced_at)
        age = (current - synced).total_seconds()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return AccessDecision(False, "malformed_policy_timestamp", node_id, policy_version)
    if age < 0 or age > max(1, int(max_age_seconds)):
        return AccessDecision(False, "stale_policy", node_id, policy_version)

    try:
        user_roles = {int(role) for role in (user_role_ids or ())}
        allowed_roles = {int(role) for role in (allowed_role_ids or ())}
    except (TypeError, ValueError):
        return AccessDecision(False, "malformed_role_assignment", node_id, policy_version)
    if not user_roles or not allowed_roles or not user_roles.intersection(allowed_roles):
        return AccessDecision(False, "no_explicit_node_permission", node_id, policy_version)

    if visitor_start is not None or visitor_expiry is not None:
        if visitor_start is None or visitor_expiry is None:
            return AccessDecision(False, "malformed_visitor_window", node_id, policy_version)
        try:
            start = _utc(visitor_start)
            expiry = _utc(visitor_expiry)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return AccessDecision(False, "malformed_visitor_window", node_id, policy_version)
        if expiry <= start:
            return AccessDecision(False, "malformed_visitor_window", node_id, policy_version)
        if current < start:
            return AccessDecision(False, "visitor_window_not_started", node_id, policy_version)
        if current >= expiry:
            return AccessDecision(False, "visitor_window_expired", node_id, policy_version)

    return AccessDecision(True, "explicit_node_permission", node_id, policy_version)


class AccessPolicyEvaluator:
    """Compatibility wrapper for callers that prefer an object evaluator."""

    def __init__(self, max_age_seconds: int = MAX_POLICY_AGE_SECONDS):
        self.max_age_seconds = max_age_seconds

    def evaluate(self, **kwargs) -> AccessDecision:
        kwargs.setdefault("max_age_seconds", self.max_age_seconds)
        return evaluate_access(**kwargs)
