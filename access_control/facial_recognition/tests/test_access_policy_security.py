from datetime import datetime, timedelta, timezone

from access_control.facial_recognition.src.access_policy import evaluate_access


def test_policy_requires_explicit_role_and_fresh_snapshot(monkeypatch):
    monkeypatch.delenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", raising=False)
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
    stale = evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now - timedelta(seconds=301), now=now,
    )
    assert not stale.allowed
    assert stale.reason == "stale_policy"

    monkeypatch.setenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", "600")
    assert evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now - timedelta(seconds=301), now=now,
    ).allowed

    for invalid_limit in ("not-a-number", "0", "-1"):
        monkeypatch.setenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", invalid_limit)
        invalid = evaluate_access(
            user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
            node_id=11, policy_version="v3", policy_synced_at=now, now=now,
        )
        assert not invalid.allowed
        assert invalid.reason == "invalid_policy_age_limit"


def test_policy_enforces_visitor_window():
    now = datetime.now(timezone.utc)
    decision = evaluate_access(
        user_id=7, is_active=True, user_role_ids=[2], allowed_role_ids=[2],
        node_id=11, policy_version="v3", policy_synced_at=now, now=now,
        visitor_start=now + timedelta(minutes=1), visitor_expiry=now + timedelta(hours=1),
    )
    assert decision.reason == "visitor_window_not_started"


def test_device_rbac_repository_evaluation(monkeypatch):
    import tempfile
    from pathlib import Path
    from access_control.facial_recognition.src.face.database import DeviceUserRepository
    from access_control.facial_recognition.src.sync import SQLiteEdgeDB

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_edge.db"
        edge_db = SQLiteEdgeDB(db_path=db_path)

        # 1. Setup user 10 (Role 2) and user 20 (Role 3)
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        edge_db.save_users_delta([
            {"user_id": 10, "is_active": 1, "face_vector_b64": "AAAA"},
            {"user_id": 20, "is_active": 1, "face_vector_b64": "BBBB"},
        ])
        edge_db.save_authorization_snapshot(
            roles=[{"role_id": 1, "role_name": "ADMIN"}, {"role_id": 2, "role_name": "STAFF"}, {"role_id": 3, "role_name": "STUDENT"}],
            user_roles=[{"user_id": 10, "role_id": 2}, {"user_id": 20, "role_id": 3}],
        )
        edge_db.save_policy_metadata(node_id=100, policy_version="v1", synced_at=now_iso, device_id="gate-01")

        # 2. Test fallback to device_node_rbac when device_rbac is empty
        edge_db.save_rbac_delta([{"node_id": 100, "role_id": 2}])
        repo = DeviceUserRepository(db_path)
        
        # User 10 (STAFF) should be allowed at node 100
        decision = repo.evaluate_access(user_id=10, node_id=100, now=now, device_id="gate-01")
        assert decision.allowed

        # The repository uses the same secure 300-second default as the evaluator.
        edge_db.save_policy_metadata(
            node_id=100, policy_version="v1",
            synced_at=(now - timedelta(seconds=301)).isoformat(), device_id="gate-01",
        )
        stale = repo.evaluate_access(user_id=10, node_id=100, now=now, device_id="gate-01")
        assert not stale.allowed
        assert stale.reason == "stale_policy"

        # Deployments can deliberately choose a longer positive limit.
        monkeypatch.setenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", "600")
        assert repo.evaluate_access(user_id=10, node_id=100, now=now, device_id="gate-01").allowed

        # Invalid or nonpositive overrides fail closed rather than disabling the age check.
        for invalid_limit in ("not-a-number", "0", "-1"):
            monkeypatch.setenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS", invalid_limit)
            invalid = repo.evaluate_access(user_id=10, node_id=100, now=now, device_id="gate-01")
            assert not invalid.allowed
            assert invalid.reason == "invalid_policy_age_limit"

        monkeypatch.delenv("EDGE_ACCESS_MAX_POLICY_AGE_SECONDS")
        edge_db.save_policy_metadata(node_id=100, policy_version="v1", synced_at=now_iso, device_id="gate-01")

        # User 20 (STUDENT) should be denied at node 100
        decision = repo.evaluate_access(user_id=20, node_id=100, now=now, device_id="gate-01")
        assert not decision.allowed

        # 3. Now set device_rbac explicitly for gate-01 to only allow Role 3 (STUDENT)
        edge_db.save_device_rbac_delta([{"device_id": "gate-01", "role_id": 3}])

        # User 10 (STAFF) was allowed by node_rbac, but gate-01 only allows STUDENT -> DENIED
        decision_staff = repo.evaluate_access(user_id=10, node_id=100, now=now, device_id="gate-01")
        assert not decision_staff.allowed
        assert decision_staff.reason == "no_explicit_node_permission"

        # User 20 (STUDENT) is allowed on gate-01
        decision_student = repo.evaluate_access(user_id=20, node_id=100, now=now, device_id="gate-01")
        assert decision_student.allowed

        # Gate-02 has NO roles in device_rbac -> fail-closed DENIED
        decision_gate2 = repo.evaluate_access(user_id=20, node_id=100, now=now, device_id="gate-02")
        assert not decision_gate2.allowed

