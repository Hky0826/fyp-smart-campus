"""Integration tests for the native Python Campus Mapping & Notification router and services."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.models.models import (
    Building,
    Edge,
    EdgeRBAC,
    Floorplan,
    KioskSession,
    Node,
    NodeRBAC,
    Notification,
    Role,
    User,
    UserRole,
)
from app.routers import mapping


@pytest.fixture()
def test_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PRIVATE_STORAGE_ROOT", tmp_path)
    monkeypatch.setenv("NAVIGATION_API_KEY", "test-kiosk-key")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Building.__table__,
        Floorplan.__table__,
        Node.__table__,
        Edge.__table__,
        Role.__table__,
        User.__table__,
        UserRole.__table__,
        NodeRBAC.__table__,
        EdgeRBAC.__table__,
        Notification.__table__,
        KioskSession.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()

    # Seed roles matching MySQL role IDs
    roles = [
        Role(role_id=1, role_name="ADMIN"),
        Role(role_id=2, role_name="STAFF"),
        Role(role_id=3, role_name="LECTURER"),
        Role(role_id=4, role_name="STUDENT"),
        Role(role_id=5, role_name="VISITOR"),
    ]
    db.add_all(roles)
    db.commit()

    # Seed a small floorplan image on disk
    fp_dir = tmp_path / "floorplans"
    fp_dir.mkdir(parents=True, exist_ok=True)
    img_path = fp_dir / "test_floor1.png"
    Image.new("RGB", (800, 600), (245, 247, 250)).save(img_path, format="PNG")

    bldg = Building(building_name="Block A")
    db.add(bldg)
    db.flush()

    fp1 = Floorplan(building_id=bldg.building_id, floor_level=1, image_path="/uploads/test_floor1.png", scale_ratio=0.1)
    fp2 = Floorplan(building_id=bldg.building_id, floor_level=2, image_path="/uploads/test_floor1.png", scale_ratio=0.1)
    db.add_all([fp1, fp2])
    db.flush()

    n_lobby = Node(floorplan_id=fp1.floorplan_id, coord_x=100, coord_y=100, room_label="Main Lobby", node_type="ENTRANCE", is_accessible="ALLOW")
    n_lift1 = Node(floorplan_id=fp1.floorplan_id, coord_x=300, coord_y=100, room_label="Lift A", node_type="ELEVATOR", is_accessible="ALLOW")
    n_lift2 = Node(floorplan_id=fp2.floorplan_id, coord_x=300, coord_y=100, room_label="Lift A", node_type="ELEVATOR", is_accessible="ALLOW")
    n_staff = Node(floorplan_id=fp2.floorplan_id, coord_x=500, coord_y=100, room_label="Staff Lounge", node_type="OFFICE", is_accessible="ALLOW")
    db.add_all([n_lobby, n_lift1, n_lift2, n_staff])
    db.flush()

    # Restrict Staff Lounge to STAFF (2) only
    db.add(NodeRBAC(node_id=n_staff.node_id, role_id=2))

    e1 = Edge(source_node_id=n_lobby.node_id, destination_node_id=n_lift1.node_id, weight_distance=20.0, is_bidirectional=True, is_accessible="ALLOW")
    e_cross = Edge(source_node_id=n_lift1.node_id, destination_node_id=n_lift2.node_id, weight_distance=10.0, is_bidirectional=True, is_accessible="ALLOW")
    e2 = Edge(source_node_id=n_lift2.node_id, destination_node_id=n_staff.node_id, weight_distance=20.0, is_bidirectional=True, is_accessible="ALLOW")
    db.add_all([e1, e_cross, e2])
    db.commit()

    app = FastAPI()
    app.include_router(mapping.router, prefix="/api/mapping")
    app.include_router(mapping.router, prefix="/api/mapping-notification")
    app.include_router(mapping.public_router)

    def override_db():
        yield db

    def fake_admin(request: Request):
        if request.headers.get("X-Test-Admin") != "1":
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        return SimpleNamespace(admin_type="SUPER_ADMIN", user=SimpleNamespace(email="admin@test.local"))

    app.dependency_overrides[get_db] = override_db
    # Wire fake_admin via dependency override on get_current_admin
    from app.core.security import get_current_admin
    app.dependency_overrides[get_current_admin] = fake_admin

    client = TestClient(app)
    yield SimpleNamespace(client=client, db=db, fp1=fp1, fp2=fp2, nodes=(n_lobby, n_lift1, n_lift2, n_staff))
    db.close()


def test_auth_enforcement_and_public_reads(test_env):
    c = test_env.client
    # Public reads succeed without admin
    assert c.get("/api/mapping/floorplans").status_code == 200
    assert c.get("/api/mapping/roles").status_code == 200
    assert c.get("/api/mapping-notification/api/floorplans").status_code == 200

    # Protected routes reject unauthenticated callers
    assert c.get("/api/mapping/global-nodes").status_code == 401
    assert c.get("/api/mapping/global-nodes", headers={"X-Test-Admin": "1"}).status_code == 200


def test_multifloor_navigation_rbac_and_kiosk_qr(test_env):
    c = test_env.client
    n_lobby, _, _, n_staff = test_env.nodes

    # Visitor (5) is denied route into Staff Lounge (role 2 only)
    denied = c.post(
        "/api/mapping/navigate/admin-test",
        headers={"X-Test-Admin": "1"},
        json={"current_location": n_lobby.node_id, "destination_node": n_staff.node_id, "rbac_role": 5},
    )
    assert denied.status_code == 404
    assert denied.json()["status"] == "no_route"

    # Lecturer (3) inherits Staff (2) access and gets a multi-floor route
    ok = c.post(
        "/api/mapping/navigate/admin-test",
        headers={"X-Test-Admin": "1"},
        json={"current_location": n_lobby.node_id, "destination_node": n_staff.node_id, "rbac_role": "lecturer"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["route_summary"]["floor_transitions"] == 1
    assert body["route_summary"]["total_distance_m"] == 50.0
    assert any(s["type"] == "transition" and s["action"] == "elevator" for s in body["instructions"])

    # Kiosk navigation generates Pillow visualisation PNG + QR session + mobile HTML page
    kiosk = c.post(
        "/api/mapping/kiosk/navigate",
        headers={"x-api-key": "test-kiosk-key"},
        json={"current_location": n_lobby.node_id, "destination_node": n_staff.node_id, "rbac_role": "staff"},
    )
    assert kiosk.status_code == 200
    kdata = kiosk.json()
    assert kdata["qr_session"]["qr_code_data_url"].startswith("data:image/png;base64,")
    assert len(kdata["visualisations"]) == 2

    token = kdata["qr_session"]["session_token"]
    mobile_html = c.get(f"/mobile-route/{token}")
    assert mobile_html.status_code == 200
    assert "Staff Lounge" in mobile_html.text

    # Visualisation PNG is served safely
    vis_filename = kdata["visualisations"][0]["filename"]
    png_resp = c.get(f"/uploads/visualisations/{vis_filename}")
    assert png_resp.status_code == 200
    assert png_resp.content[:4] == b"\x89PNG"


def test_map_data_atomic_save_and_transition_validation(test_env):
    c = test_env.client
    n_lobby, n_lift1, n_lift2, _ = test_env.nodes

    # Save existing floorplan preserving IDs and adding a new node
    resp = c.post(
        "/api/mapping/map-data",
        headers={"X-Test-Admin": "1"},
        json={
            "floorplan_id": test_env.fp1.floorplan_id,
            "nodes": [
                {"node_id": n_lobby.node_id, "x": 110, "y": 110, "room_label": "Main Lobby", "node_type": "ENTRANCE", "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5]},
                {"node_id": n_lift1.node_id, "x": 300, "y": 100, "room_label": "Lift A", "node_type": "ELEVATOR", "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5]},
                {"node_id": None, "x": 200, "y": 200, "room_label": "Info Desk", "node_type": "OFFICE", "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5]},
            ],
            "edges": [
                {"edge_id": None, "start": 0, "end": 2, "weight": 14.5, "is_bidirectional": True, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5]},
                {"edge_id": None, "start": 1, "is_cross_floor": True, "target_node_id": n_lift2.node_id, "weight": 10.0, "is_bidirectional": True, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5]},
            ],
        },
    )
    assert resp.status_code == 200

    loaded = c.get(f"/api/mapping/map-data/{test_env.fp1.floorplan_id}").json()
    labels = {n["room_label"] for n in loaded["nodes"]}
    assert "Info Desk" in labels
    assert any(n["node_id"] == n_lobby.node_id and n["coord_x"] == 110.0 for n in loaded["nodes"])


def test_floorplan_upload_update_and_delete(test_env):
    c = test_env.client
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(buf, format="PNG")
    buf.seek(0)

    up = c.post(
        "/api/mapping/floorplans",
        headers={"X-Test-Admin": "1"},
        files={"floorplanImage": ("new_floor.png", buf, "image/png")},
        data={"buildingName": "Block Z", "floorLevel": "3", "scaleRatio": "0.5"},
    )
    assert up.status_code == 200
    fp_id = up.json()["floorplan_id"]

    upd = c.put(
        f"/api/mapping/floorplans/{fp_id}",
        headers={"X-Test-Admin": "1"},
        json={"buildingName": "Block Z Renamed", "floorLevel": 4, "scaleRatio": 0.25},
    )
    assert upd.status_code == 200
    assert "old unused building removed" in upd.json()["message"]

    dele = c.delete(f"/api/mapping/floorplans/{fp_id}", headers={"X-Test-Admin": "1"})
    assert dele.status_code == 200
    assert "unused building deleted" in dele.json()["message"]


def test_notification_workflows_all_event_types_and_audit_trail(test_env, monkeypatch):
    from app.services.mapping import notification_service as ns

    c = test_env.client
    db = test_env.db
    n_lobby, _, _, n_staff = test_env.nodes

    # Seed host (Staff) & visitor (Visitor)
    host_user = User(given_name="Alice", family_name="Host", email="alice.host@campus.test", is_active=True)
    visitor_user = User(given_name="Bob", family_name="Visitor", email="bob.visitor@campus.test", is_active=True)
    db.add_all([host_user, visitor_user])
    db.flush()
    db.add_all([
        UserRole(user_id=host_user.user_id, role_id=2),
        UserRole(user_id=visitor_user.user_id, role_id=5),
    ])
    db.commit()

    # Bind notification background worker to the in-memory test DB session
    class _SessionProxy:
        def __init__(self, inner):
            self._inner = inner
        def __getattr__(self, name):
            return getattr(self._inner, name)
        def close(self):
            pass

    monkeypatch.setattr(ns, "SessionLocal", lambda: _SessionProxy(db))
    monkeypatch.setattr(ns, "_try_publish_rabbitmq", lambda payload: False)

    sent_emails = []

    def fake_send_smtp(*, to_email, subject, html_content, attachments=None, delivery_mode="ethereal", max_retries=3):
        sent_emails.append({
            "to": to_email,
            "subject": subject,
            "html": html_content,
            "attachments": list(attachments or []),
            "mode": delivery_mode,
        })
        return {"success": True, "previewUrl": "https://ethereal.email/message/TESTMSG12345"}

    monkeypatch.setattr(ns, "_send_email_smtp", fake_send_smtp)

    # 1. appointment_routing: Host gets alert (NO images), Visitor gets guide (WITH CID route PNGs)
    res1 = c.post(
        "/api/mapping/navigate/admin-test",
        headers={"X-Test-Admin": "1"},
        json={
            "current_location": n_lobby.node_id,
            "destination_node": n_staff.node_id,
            "rbac_role": "staff",
            "user_id": visitor_user.user_id,
            "event_type": "appointment_routing",
            "email_delivery_mode": "ethereal",
            "notification_trigger": {
                "target_host_id": host_user.user_id,
                "alert_message": "Bob is heading to Staff Lounge.",
            },
        },
    )
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["notification"]["host"]["status"] == "QUEUED"
    assert body1["notification"]["visitor"]["status"] == "QUEUED"
    assert len(sent_emails) == 2
    host_mail = next(m for m in sent_emails if m["to"] == "alice.host@campus.test")
    visitor_mail = next(m for m in sent_emails if m["to"] == "bob.visitor@campus.test")
    assert len(host_mail["attachments"]) == 0
    assert len(visitor_mail["attachments"]) == 2
    assert "cid:" in visitor_mail["html"]

    # 2. visitor_navigation: Visitor-only (no host required), WITH CID route PNGs
    sent_emails.clear()
    res2 = c.post(
        "/api/mapping/notifications/test",
        headers={"X-Test-Admin": "1"},
        json={
            "current_location": n_lobby.node_id,
            "destination_node": n_staff.node_id,
            "rbac_role": "staff",
            "user_id": visitor_user.user_id,
            "event_type": "visitor_navigation",
            "email_delivery_mode": "ethereal",
        },
    )
    assert res2.status_code == 200
    assert res2.json()["notification"]["host"] is None
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == "bob.visitor@campus.test"
    assert len(sent_emails[0]["attachments"]) == 2

    # 3. emergency_alert & visitor_arrival: both host & visitor notified, no route images
    for ev in ("emergency_alert", "visitor_arrival"):
        sent_emails.clear()
        r = c.post(
            "/api/mapping/navigate/admin-test",
            headers={"X-Test-Admin": "1"},
            json={
                "current_location": n_lobby.node_id,
                "destination_node": n_staff.node_id,
                "rbac_role": "staff",
                "user_id": visitor_user.user_id,
                "event_type": ev,
                "notification_trigger": {
                    "target_host_id": host_user.user_id,
                    "alert_message": f"Test {ev}",
                },
            },
        )
        assert r.status_code == 200
        assert len(sent_emails) == 2
        assert all(len(m["attachments"]) == 0 for m in sent_emails)

    # 4. Audit trail API returns SENT notifications with Ethereal Preview Link
    logs = c.get("/api/mapping/notifications", headers={"X-Test-Admin": "1"})
    assert logs.status_code == 200
    log_rows = logs.json()
    assert len(log_rows) >= 7
    assert all(row["status"] == "SENT" for row in log_rows)
    assert any("https://ethereal.email/message/TESTMSG12345" in (row["body"] or "") for row in log_rows)

    # 5. Notification users endpoint returns both seeded users
    users_resp = c.get("/api/mapping/notification-users", headers={"X-Test-Admin": "1"})
    assert users_resp.status_code == 200
    emails = {u["email"] for u in users_resp.json()}
    assert {"alice.host@campus.test", "bob.visitor@campus.test"}.issubset(emails)


def test_ai_auto_mapper_generates_nodes_edges_rbac_and_transitions(test_env, monkeypatch):
    from app.services.mapping import ai_auto_mapper

    c = test_env.client
    # Mock Gemini Vision response to verify deterministic full-graph synthesis + cross-floor matching
    fake_nodes = [
        {"temp_id": "g0", "room_label": "Biology Lab", "node_type": "CLASSROOM", "x": 150.0, "y": 150.0, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4], "ai_generated": True, "ai_confidence": 0.96, "ai_source": "gemini_vision", "review_status": "PENDING"},
        {"temp_id": "g1", "room_label": "Corridor", "node_type": "CORRIDOR", "x": 200.0, "y": 250.0, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5], "ai_generated": True, "ai_confidence": 0.92, "ai_source": "gemini_vision", "review_status": "PENDING"},
        {"temp_id": "g2", "room_label": "Corridor", "node_type": "CORRIDOR", "x": 300.0, "y": 250.0, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5], "ai_generated": True, "ai_confidence": 0.92, "ai_source": "gemini_vision", "review_status": "PENDING"},
        {"temp_id": "g3", "room_label": "Elevator 1", "node_type": "ELEVATOR", "x": 300.0, "y": 110.0, "is_accessible": "ALLOW", "allowed_roles": [1, 2, 3, 4, 5], "ai_generated": True, "ai_confidence": 0.95, "ai_source": "gemini_vision", "review_status": "PENDING"},
    ]
    monkeypatch.setattr(ai_auto_mapper, "_call_gemini_vision", lambda *a, **kw: [dict(n) for n in fake_nodes])

    res = c.post(
        "/api/mapping/analyze-floorplan",
        headers={"X-Test-Admin": "1"},
        json={"floorplan_id": test_env.fp1.floorplan_id},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["engine"] == "gemini_vision"
    assert len(data["nodes"]) >= 4
    # Every 90-degree turn is promoted to an explicit CORRIDOR turning node (no multi-point bent edges)
    same_floor_edges = [e for e in data["edges"] if not e.get("is_cross_floor")]
    assert all(len(e.get("pathPoints") or []) == 2 for e in same_floor_edges)
    # Same-floor edges (corridor spine + room/elevator spurs) + 1 cross-floor elevator link to fp2
    same_floor = [e for e in data["edges"] if not e.get("is_cross_floor")]
    cross_floor = [e for e in data["edges"] if e.get("is_cross_floor")]
    assert len(same_floor) == len(data["nodes"]) - 1
    assert len(cross_floor) == 1
    assert cross_floor[0]["target_node_id"] == test_env.nodes[2].node_id  # Lift A on fp2


