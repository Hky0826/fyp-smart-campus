from datetime import datetime, timedelta, timezone

from access_control.facial_recognition.src.access_policy import evaluate_access


def test_policy_requires_explicit_role_and_fresh_snapshot():
    now = datetime.now(timezone.utc)
    allowed = evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now, now=now,
    )
    assert allowed.allowed
    assert not evaluate_access(
        user_id=7, is_active=True, user_role_ids=[3], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now, now=now,
    ).allowed
    assert not evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now - timedelta(seconds=301), now=now,
    ).allowed


def test_policy_enforces_visitor_window():
    now = datetime.now(timezone.utc)
    decision = evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now, now=now,
        visitor_start=now + timedelta(minutes=1), visitor_expiry=now + timedelta(hours=1),
    )
    assert decision.reason == "visitor_window_not_started"
