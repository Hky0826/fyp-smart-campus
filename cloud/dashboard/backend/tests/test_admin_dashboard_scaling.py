import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.models import (
    Base,
    Role,
    User,
    Student,
    Faculty,
    Programme,
    UserFaceEmbedding,
    Device,
    Building,
    Floorplan,
    Node,
    AuthenticationLog,
    JWTSession,
    Course,
    CourseEnrollment,
)
from app.routers import iam, infrastructure
from app.schemas import schemas


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _seed_directory(db):
    r_admin = Role(role_id=1, role_name="ADMIN", description="Admin")
    r_student = Role(role_id=4, role_name="STUDENT", description="Student")
    r_visitor = Role(role_id=5, role_name="VISITOR", description="Visitor")
    db.add_all([r_admin, r_student, r_visitor])

    fac = Faculty(faculty_id="FAC-CS", faculty_name="Computing", dean_id="STF-00001")
    prog = Programme(programme_id="PRG-CS", programme_name="Computer Science", faculty_id="FAC-CS", hop_id="STF-00001")
    db.add_all([fac, prog])

    bldg = Building(building_id=1, building_name="Block A")
    fp = Floorplan(floorplan_id=1, building_id=1, floor_level="L1", image_path="/static/uploads/l1.png")
    node = Node(node_id=1, floorplan_id=1, coord_x=10.0, coord_y=20.0, node_type="ENTRANCE", room_label="Main Gate")
    db.add_all([bldg, fp, node])
    db.flush()

    now = datetime.datetime.utcnow()
    dev_online = Device(
        device_id="GATE-01",
        device_name="Main Gate",
        node_id=1,
        device_type="ENTRY_GATE",
        is_active=True,
        last_heartbeat=now,
    )
    dev_offline = Device(
        device_id="GATE-02",
        device_name="Side Gate",
        node_id=1,
        device_type="ENTRY_GATE",
        is_active=True,
        last_heartbeat=now - datetime.timedelta(hours=2),
    )
    db.add_all([dev_online, dev_offline])

    admin_user = User(
        given_name="Super",
        family_name="Admin",
        email="super.admin@qiu.edu.my",
        is_active=True,
        roles=[r_admin],
    )
    users = [admin_user]
    for i in range(1, 31):
        u = User(
            given_name=f"Alice{i:02d}",
            family_name=f"Student{i:02d}",
            email=f"alice{i:02d}@qiu.edu.my",
            is_active=(i % 5 != 0),
            last_known_location=1 if i == 1 else None,
            roles=[r_student],
        )
        users.append(u)
    db.add_all(users)
    db.flush()

    st1 = Student(
        student_id="QIU-202407-000001",
        user_id=users[1].user_id,
        programme_id="PRG-CS",
        faculty_id="FAC-CS",
        intake=202407,
        enrolled_since=datetime.date(2024, 7, 1),
    )
    db.add(st1)

    emb = UserFaceEmbedding(
        user_id=users[1].user_id,
        template_name="front",
        model_name="openvc_sface",
        embedding=b"\x00\x00\x80\x3f" * 16,
    )
    db.add(emb)

    course = Course(
        course_code="CS101",
        course_name="Algorithms",
        credit_hours=3,
        programme_id="PRG-CS",
        course_level="UNDERGRADUATE",
        is_active=True,
    )
    db.add(course)
    db.flush()

    db.add(
        CourseEnrollment(
            student_id=st1.student_id,
            course_id=course.course_id,
            semester=202607,
            academic_year="2025/2026",
            status="ENROLLED",
        )
    )
    db.add(
        AuthenticationLog(
            sync_key="sync-001",
            user_id=users[1].user_id,
            device_id="GATE-01",
            node_id=1,
            auth_status="SUCCESS",
            confidence_score=0.94,
            timestamp=now,
        )
    )
    db.add(
        AuthenticationLog(
            sync_key="sync-002",
            user_id=users[1].user_id,
            device_id="GATE-01",
            node_id=1,
            auth_status="FAILED",
            reason="Low confidence",
            timestamp=now - datetime.timedelta(minutes=5),
        )
    )
    db.add(
        JWTSession(
            user_id=users[1].user_id,
            token_hash="hash-123",
            issued_at=now,
            expires_at=now + datetime.timedelta(hours=2),
            device_id="GATE-01",
            is_revoked=False,
            principal_type="USER",
        )
    )
    db.commit()
    return admin_user, users[1:]


def test_paginated_users_search_filter_sort_and_summary():
    db = _make_session()
    try:
        admin_user, students = _seed_directory(db)
        actor = SimpleNamespace(user_id=admin_user.user_id, admin_type="SUPER_ADMIN")

        page1 = iam.list_users_paginated(
            page=1,
            page_size=10,
            q="",
            role_id=None,
            status_filter="ALL",
            face_status="ALL",
            faculty_id=None,
            department_id=None,
            sort_by="user_id",
            sort_order="asc",
            db=db,
            current_admin=actor,
        )
        assert page1.total == 31
        assert len(page1.items) == 10
        assert page1.total_pages == 4
        assert page1.summary.total_users == 31
        assert page1.summary.face_enrolled_users == 1
        assert page1.summary.inactive_users == 6

        by_student_id = iam.list_users_paginated(
            page=1,
            page_size=10,
            q="QIU-202407-000001",
            role_id=4,
            status_filter="ACTIVE",
            face_status="ENROLLED",
            faculty_id="FAC-CS",
            department_id=None,
            sort_by="name",
            sort_order="asc",
            db=db,
            current_admin=actor,
        )
        assert by_student_id.total == 1
        assert by_student_id.items[0].user_id == students[0].user_id
        assert by_student_id.items[0].face_enrolled is True
        assert by_student_id.items[0].enrolled_poses == ["front"]
    finally:
        db.close()


def test_user_detail_and_bulk_operations_with_self_protection():
    db = _make_session()
    try:
        admin_user, students = _seed_directory(db)
        actor = SimpleNamespace(user_id=admin_user.user_id, admin_type="SUPER_ADMIN")

        detail = iam.get_user_detail(user_id=students[0].user_id, db=db, current_admin=actor)
        assert detail["user"]["email"] == "alice01@qiu.edu.my"
        assert detail["biometrics"]["enrolled"] is True
        assert detail["biometrics"]["poses"][0]["pose"] == "front"
        assert len(detail["recent_auth_logs"]) == 2
        assert len(detail["active_sessions"]) == 1
        assert len(detail["enrollments"]) == 1
        assert detail["enrollments"][0]["course_code"] == "CS101"

        # Self-deactivation guard
        with pytest.raises(HTTPException) as exc:
            iam.bulk_update_user_status(
                schemas.BulkUserStatusRequest(user_ids=[admin_user.user_id, students[0].user_id], is_active=False),
                BackgroundTasks(),
                db=db,
                current_admin=actor,
            )
        assert exc.value.status_code == 400

        # Bulk status update
        res = iam.bulk_update_user_status(
            schemas.BulkUserStatusRequest(user_ids=[students[0].user_id, students[1].user_id], is_active=False),
            BackgroundTasks(),
            db=db,
            current_admin=actor,
        )
        assert res["affected"] == 2
        db.refresh(students[0])
        db.refresh(students[1])
        assert students[0].is_active is False
        assert students[1].is_active is False

        # Bulk role assign
        res_role = iam.bulk_assign_user_role(
            schemas.BulkUserRoleRequest(user_ids=[students[2].user_id], role_id=5, mode="add"),
            BackgroundTasks(),
            db=db,
            current_admin=actor,
        )
        assert res_role["affected"] == 1
        db.refresh(students[2])
        assert {r.role_id for r in students[2].roles} == {4, 5}

        # Self-delete guard
        with pytest.raises(HTTPException) as exc_del:
            iam.bulk_delete_users(
                schemas.BulkUserDeleteRequest(user_ids=[admin_user.user_id]),
                BackgroundTasks(),
                db=db,
                current_admin=actor,
            )
        assert exc_del.value.status_code == 400

        # Bulk delete valid target
        res_del = iam.bulk_delete_users(
            schemas.BulkUserDeleteRequest(user_ids=[students[3].user_id, students[4].user_id]),
            BackgroundTasks(),
            db=db,
            current_admin=actor,
        )
        assert res_del["affected"] == 2
        assert db.query(User).filter(User.user_id == students[3].user_id).first() is None
    finally:
        db.close()


def test_dashboard_stats_returns_live_telemetry():
    db = _make_session()
    try:
        admin_user, _students = _seed_directory(db)
        actor = SimpleNamespace(user_id=admin_user.user_id, admin_type="SUPER_ADMIN")
        stats = infrastructure.get_dashboard_stats(db=db, current_admin=actor)
        assert stats["users"] == 31
        assert stats["active_users"] == 25
        assert stats["inactive_users"] == 6
        assert stats["face_enrolled_users"] == 1
        assert stats["devices"] == 2
        assert stats["online_devices"] == 1
        assert stats["offline_devices"] == 1
        assert stats["active_sessions"] == 1
        assert stats["auth_attempts_24h"] == 2
        assert stats["auth_failures_24h"] == 1
        assert stats["db_latency_ms"] >= 0.0
    finally:
        db.close()


def test_csv_import_all_roles_effective_access_rbac_matrix_and_paginated_logs():
    import asyncio
    import io
    from fastapi import UploadFile
    from app.models.models import Department, Role, NodeRBAC

    db = _make_session()
    try:
        admin_user, students = _seed_directory(db)
        db.add_all([
            Role(role_id=2, role_name="STAFF", description="Staff"),
            Role(role_id=3, role_name="LECTURER", description="Lecturer"),
            Department(department_id="DEP-IT", department_name="IT Department", manager_id="STF-00001"),
            NodeRBAC(node_id=1, role_id=4),
        ])
        db.commit()
        actor = SimpleNamespace(user_id=admin_user.user_id, admin_type="SUPER_ADMIN")

        # 1. Effective access check
        eff = iam.get_user_effective_access(user_id=students[0].user_id, db=db, current_admin=actor)
        assert eff["total_devices"] == 2
        assert eff["allowed_devices"] == 2
        assert eff["doors"][0]["can_unlock"] is True

        # 2. CSV Import validate + commit across STUDENT, LECTURER, STAFF, VISITOR + 1 invalid row
        csv_body = (
            "role,given_name,family_name,email,intake,programme_id,faculty_id,department_id,position,staff_type,id_number,organization\n"
            "STUDENT,John,Tan,john.tan@qiu.edu.my,202407,PRG-CS,FAC-CS,,,,,\n"
            "LECTURER,Dr,Lim,dr.lim@qiu.edu.my,,,FAC-CS,DEP-IT,Senior Lecturer,,,\n"
            "STAFF,Mei,Ling,mei.ling@qiu.edu.my,,,,DEP-IT,Coordinator,ADMINISTRATIVE,,\n"
            "VISITOR,Alex,Guest,alex.guest@example.com,,,,,,,IC998877,Acme Corp\n"
            "STUDENT,Bad,Row,bad.row@qiu.edu.my,BAD,PRG-CS,FAC-CS,,,,,\n"
        ).encode("utf-8")

        preview = asyncio.run(iam.validate_users_csv_import(
            file=UploadFile(filename="users.csv", file=io.BytesIO(csv_body)),
            db=db,
            current_admin=actor,
        ))
        assert preview["total_rows"] == 5
        assert preview["valid_count"] == 4
        assert preview["error_count"] == 1

        commit_res = asyncio.run(iam.commit_users_csv_import(
            background_tasks=BackgroundTasks(),
            file=UploadFile(filename="users.csv", file=io.BytesIO(csv_body)),
            skip_invalid=True,
            db=db,
            current_admin=actor,
        ))
        assert commit_res["created"] == 4
        assert commit_res["skipped"] == 1

        # 3. Overview exceptions + device detail + RBAC matrix + paginated logs & audit events
        exc_data = infrastructure.get_overview_exceptions(db=db, current_admin=actor)
        assert len(exc_data["auth_series_7d"]) == 7
        assert any(a["id"] == "offline-devices" for a in exc_data["alerts"])

        dev_detail = infrastructure.get_device_detail(device_id="GATE-01", db=db, current_admin=actor)
        assert dev_detail["device"]["is_online"] is True
        assert dev_detail["metrics_24h"]["attempts"] == 2

        matrix = infrastructure.get_rbac_matrix(db=db, current_admin=actor)
        assert len(matrix["roles"]) >= 4
        toggle = infrastructure.toggle_rbac_matrix(
            infrastructure.RbacMatrixToggleRequest(target_type="device", target_id="GATE-01", role_id=5, allowed=True),
            BackgroundTasks(),
            db=db,
            current_admin=actor,
        )
        assert toggle["ok"] is True

        logs_page = infrastructure.list_auth_logs_paginated(
            page=1, page_size=10, q="", auth_status="FAILED", device_id=None, user_id=None, date_from=None, date_to=None, db=db, current_admin=actor
        )
        assert logs_page["total"] == 1

        audit_page = infrastructure.list_audit_events_paginated(
            page=1, page_size=10, q="", target_type="ALL", result="ALL", db=db, current_admin=actor
        )
        assert audit_page["total"] >= 2
    finally:
        db.close()
