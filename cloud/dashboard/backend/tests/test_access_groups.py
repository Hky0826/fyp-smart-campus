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
    Building,
    Device,
    Edge,
    Floorplan,
    Node,
    Role,
    User,
    UserFaceEmbedding,
)
from app.routers import iam, infrastructure
from app.schemas import schemas
from app.services.mapping.navigation_engine import run_navigation
from app.services.rbac_resolver import resolve_all_device_policies, resolve_all_node_policies


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _seed_env(db):
    r_admin = Role(role_id=1, role_name="ADMIN", description="Admin")
    r_staff = Role(role_id=2, role_name="STAFF", description="Staff")
    r_lecturer = Role(role_id=3, role_name="LECTURER", description="Lecturer")
    r_student = Role(role_id=4, role_name="STUDENT", description="Student")
    db.add_all([r_admin, r_staff, r_lecturer, r_student])

    bldg = Building(building_id=1, building_name="Block A")
    fp = Floorplan(floorplan_id=1, building_id=1, floor_level="L1", image_path="/static/uploads/l1.png", scale_ratio=1.0)
    n_lobby = Node(node_id=1, floorplan_id=1, coord_x=0.0, coord_y=0.0, node_type="ENTRANCE", room_label="Main Lobby")
    n_lab = Node(node_id=2, floorplan_id=1, coord_x=10.0, coord_y=0.0, node_type="LABORATORY", room_label="AI Lab")
    n_server = Node(node_id=3, floorplan_id=1, coord_x=20.0, coord_y=0.0, node_type="OFFICE", room_label="Server Room")
    db.add_all([bldg, fp, n_lobby, n_lab, n_server])
    db.flush()

    db.add_all([
        Edge(edge_id=1, source_node_id=1, destination_node_id=2, weight_distance=10.0, is_accessible="ALLOW", is_bidirectional=True),
        Edge(edge_id=2, source_node_id=2, destination_node_id=3, weight_distance=10.0, is_accessible="ALLOW", is_bidirectional=True),
    ])

    dev_lab = Device(device_id="DEV-LAB", device_name="AI Lab Door", node_id=2, device_type="CLASSROOM", is_active=True)
    dev_srv = Device(device_id="DEV-SRV", device_name="Server Door", node_id=3, device_type="OFFICE", is_active=True)
    db.add_all([dev_lab, dev_srv])

    u_admin = User(user_id=1, given_name="Super", family_name="Admin", email="admin@campus.edu", is_active=True)
    u_admin.roles = [r_admin]

    u_staff = User(user_id=2, given_name="Sam", family_name="Staff", email="sam@campus.edu", is_active=True)
    u_staff.roles = [r_staff]

    u_student = User(user_id=3, given_name="Alice", family_name="Student", email="alice@campus.edu", is_active=True)
    u_student.roles = [r_student]

    u_student_2 = User(user_id=4, given_name="Bob", family_name="Student", email="bob@campus.edu", is_active=True)
    u_student_2.roles = [r_student]

    db.add_all([u_admin, u_staff, u_student, u_student_2])
    db.flush()

    for uid in (1, 2, 3, 4):
        db.add(UserFaceEmbedding(user_id=uid, template_name="front", model_name="arcface_r50", embedding=b"\x01" * 16))

    db.commit()
    return SimpleNamespace(user_id=1)


def test_access_group_crud_and_validation():
    db = _make_session()
    admin = _seed_env(db)
    bg = BackgroundTasks()

    # Create mixed group (multiple roles + individual user)
    created = iam.create_access_group(
        schemas.AccessGroupCreate(
            group_name="AI Lab Authorized",
            description="Staff, lecturers, and Alice",
            role_ids=[2, 3],
            user_ids=[3],
        ),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    assert created.group_name == "AI Lab Authorized"
    assert sorted(r.role_id for r in created.roles) == [2, 3]
    assert [u.user_id for u in created.users] == [3]

    # Duplicate name rejected (case-insensitive)
    with pytest.raises(HTTPException) as exc:
        iam.create_access_group(
            schemas.AccessGroupCreate(group_name="ai lab authorized"),
            background_tasks=bg,
            db=db,
            current_admin=admin,
        )
    assert exc.value.status_code == 400

    # Create user-only group (no roles)
    user_only = iam.create_access_group(
        schemas.AccessGroupCreate(
            group_name="Server Room Team",
            role_ids=[],
            user_ids=[4],
        ),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    assert user_only.roles == []
    assert [u.user_id for u in user_only.users] == [4]

    # Update group membership
    updated = iam.update_access_group(
        created.group_id,
        schemas.AccessGroupUpdate(role_ids=[2], user_ids=[3, 4]),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    assert [r.role_id for r in updated.roles] == [2]
    assert sorted(u.user_id for u in updated.users) == [3, 4]

    # List & Delete
    listed = iam.list_access_groups(db=db, current_admin=admin)
    assert len(listed) == 2
    iam.delete_access_group(user_only.group_id, background_tasks=bg, db=db, current_admin=admin)
    assert len(iam.list_access_groups(db=db, current_admin=admin)) == 1


def test_node_and_device_group_plus_individual_user_resolution():
    db = _make_session()
    admin = _seed_env(db)
    bg = BackgroundTasks()

    # Group 1: Staff + Lecturer + Alice (student user_id=3)
    grp_lab = iam.create_access_group(
        schemas.AccessGroupCreate(group_name="Lab Access", role_ids=[2, 3], user_ids=[3]),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    # Group 2: User-only group with Bob (user_id=4)
    grp_srv = iam.create_access_group(
        schemas.AccessGroupCreate(group_name="Server Team", role_ids=[], user_ids=[4]),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )

    # Assign Lab Access group to node 2 (AI Lab)
    infrastructure.toggle_rbac_matrix_group(
        infrastructure.RbacMatrixToggleGroupRequest(target_type="node", target_id="2", group_id=grp_lab.group_id, allowed=True),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    # Assign Lab Access to node 3 (Server Room), then override DEV-SRV with Server Team group (user-only!)
    infrastructure.toggle_rbac_matrix_group(
        infrastructure.RbacMatrixToggleGroupRequest(target_type="node", target_id="3", group_id=grp_lab.group_id, allowed=True),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    infrastructure.toggle_rbac_matrix_group(
        infrastructure.RbacMatrixToggleGroupRequest(target_type="device", target_id="DEV-SRV", group_id=grp_srv.group_id, allowed=True),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )

    # Also grant direct individual user access to Bob on node 2
    infrastructure.toggle_rbac_matrix_user(
        infrastructure.RbacMatrixToggleUserRequest(target_type="node", target_id="2", user_id=4, allowed=True),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )

    node_policies = resolve_all_node_policies(db)
    device_policies = resolve_all_device_policies(db)

    assert node_policies[2]["effective_role_ids"] == {2, 3}
    assert node_policies[2]["effective_user_ids"] == {3, 4}
    assert device_policies["DEV-SRV"]["uses_override"] is True
    assert device_policies["DEV-SRV"]["effective_role_ids"] == set()
    assert device_policies["DEV-SRV"]["effective_user_ids"] == {4}

    # Check effective access for Sam (STAFF):
    # - DEV-LAB inherits node 2 -> allowed via group 'Lab Access' (role STAFF)
    # - DEV-SRV is overridden by 'Server Team' (user 4 only) -> DENIED for Sam!
    sam_access = iam.get_user_effective_access(2, db=db, current_admin=admin)
    sam_doors = {d["device_id"]: d for d in sam_access["doors"]}
    assert sam_doors["DEV-LAB"]["can_unlock"] is True
    assert "Lab Access" in sam_doors["DEV-LAB"]["reason"]
    assert sam_doors["DEV-SRV"]["can_unlock"] is False

    # Check effective access for Alice (STUDENT, in Lab Access group as direct user):
    alice_access = iam.get_user_effective_access(3, db=db, current_admin=admin)
    alice_doors = {d["device_id"]: d for d in alice_access["doors"]}
    assert alice_doors["DEV-LAB"]["can_unlock"] is True
    assert "direct user" in alice_doors["DEV-LAB"]["reason"]
    assert alice_doors["DEV-SRV"]["can_unlock"] is False

    # Check effective access for Bob (STUDENT, direct user on node 2 + in Server Team group on DEV-SRV):
    bob_access = iam.get_user_effective_access(4, db=db, current_admin=admin)
    bob_doors = {d["device_id"]: d for d in bob_access["doors"]}
    assert bob_doors["DEV-LAB"]["can_unlock"] is True
    assert "direct user access" in bob_doors["DEV-LAB"]["reason"]
    assert bob_doors["DEV-SRV"]["can_unlock"] is True
    assert "Server Team" in bob_doors["DEV-SRV"]["reason"]

    # Check RBAC matrix response includes groups and direct users
    matrix = infrastructure.get_rbac_matrix(db=db, current_admin=admin)
    assert len(matrix["groups"]) == 2
    node2 = next(n for n in matrix["nodes"] if n["node_id"] == 2)
    assert grp_lab.group_id in node2["group_ids"]
    assert 4 in node2["user_ids"]
    dev_srv = next(d for d in matrix["devices"] if d["device_id"] == "DEV-SRV")
    assert dev_srv["uses_device_override"] is True
    assert grp_srv.group_id in dev_srv["group_ids"]

    # Check Device Detail reflects override and groups
    detail = infrastructure.get_device_detail("DEV-SRV", db=db, current_admin=admin)
    assert detail["device"]["uses_device_override"] is True
    assert detail["device"]["assigned_group_ids"] == [grp_srv.group_id]


def test_navigation_engine_respects_node_access_group_roles():
    db = _make_session()
    admin = _seed_env(db)
    bg = BackgroundTasks()

    # Lobby (node 1) and AI Lab (node 2) both get "Staff Group" (role_id=2)
    grp = iam.create_access_group(
        schemas.AccessGroupCreate(group_name="Staff Only", role_ids=[2], user_ids=[]),
        background_tasks=bg,
        db=db,
        current_admin=admin,
    )
    for nid in ("1", "2"):
        infrastructure.toggle_rbac_matrix_group(
            infrastructure.RbacMatrixToggleGroupRequest(target_type="node", target_id=nid, group_id=grp.group_id, allowed=True),
            background_tasks=bg,
            db=db,
            current_admin=admin,
        )

    route = run_navigation(db, current_location=1, destination_node=2, rbac_role=2)
    assert [n["node_id"] for n in route["path"]] == [1, 2]
