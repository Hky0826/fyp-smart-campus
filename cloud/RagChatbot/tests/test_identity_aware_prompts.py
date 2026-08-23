import pytest
from unittest.mock import MagicMock, patch

from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.generation.prompt_builder import (
    build_prompt,
    build_user_identity_block,
    _SYSTEM_PROMPT,
)
from RagChatbot.retrieval.ranking import RankedChunk


def test_build_user_identity_block_for_student():
    ctx = AuthenticatedChatContext(
        user_id=2,
        session_id=10,
        roles=("STUDENT", "VISITOR"),
        student_id="QIU-202407-000001",
        program="Bachelor of Computer Science",
        faculty="Faculty of Computing and Information Technology",
        given_name="Kah Yuen",
        full_name="Kah Yuen Ho",
        device_label="Ground Floor Kiosk",
        authenticated=True,
    )
    block = build_user_identity_block(ctx)

    assert "Full Name: Kah Yuen Ho" in block
    assert "Given Name: Kah Yuen" in block
    assert "Student ID: QIU-202407-000001" in block
    assert "Programme of Study: Bachelor of Computer Science" in block
    assert "Faculty: Faculty of Computing and Information Technology" in block
    assert "Current Interaction Location: Ground Floor Kiosk" in block
    assert "Address the student warmly" in block
    assert "student academic regulations" in block


def test_build_user_identity_block_for_lecturer():
    ctx = AuthenticatedChatContext(
        user_id=3,
        session_id=11,
        roles=("LECTURER", "STAFF"),
        lecturer_id="LEC-000001",
        position_desc="Associate Professor",
        faculty="Faculty of Medicine",
        given_name="Kah Wai",
        full_name="Kah Wai Ho",
        authenticated=True,
    )
    block = build_user_identity_block(ctx)

    assert "Full Name: Kah Wai Ho" in block
    assert "Lecturer ID: LEC-000001" in block
    assert "Position / Designation: Associate Professor" in block
    assert "Faculty: Faculty of Medicine" in block
    assert "Prof./Dr./Lecturer" in block
    assert "academic faculty" in block


def test_build_user_identity_block_for_staff():
    ctx = AuthenticatedChatContext(
        user_id=4,
        session_id=12,
        roles=("STAFF",),
        staff_id="STF-000002",
        department="IT Operations",
        position_desc="Senior Network Engineer",
        full_name="Kelvin Goh",
        authenticated=True,
    )
    block = build_user_identity_block(ctx)

    assert "Full Name: Kelvin Goh" in block
    assert "Staff ID: STF-000002" in block
    assert "Department: IT Operations" in block
    assert "Position / Designation: Senior Network Engineer" in block
    assert "professionally" in block


def test_build_user_identity_block_for_admin():
    ctx = AuthenticatedChatContext(
        user_id=1,
        session_id=1,
        roles=("ADMIN",),
        admin_id="ADM-000001",
        admin_type="SUPER_ADMIN",
        full_name="Lam Hong Lee",
        authenticated=True,
    )
    block = build_user_identity_block(ctx)

    assert "Full Name: Lam Hong Lee" in block
    assert "Administrator Authority: ADM-000001 (SUPER_ADMIN)" in block
    assert "governance, and institutional policy clarity" in block


def test_build_user_identity_block_for_visitor():
    ctx = AuthenticatedChatContext(
        user_id=None,
        session_id=None,
        roles=("VISITOR",),
        authenticated=False,
    )
    block = build_user_identity_block(ctx)

    assert "Unauthenticated Visitor / Guest" in block
    assert "Roles: VISITOR" in block
    assert "welcoming campus host" in block
    assert "Student ID" not in block
    assert "Staff ID" not in block


def test_build_prompt_includes_identity_in_system_prompt():
    ctx = AuthenticatedChatContext(
        user_id=2,
        session_id=10,
        roles=("STUDENT",),
        student_id="QIU-202407-000001",
        program="Computer Science",
        given_name="Kah Yuen",
        full_name="Kah Yuen Ho",
        authenticated=True,
    )
    chunks = [
        RankedChunk(
            chunk_id=101,
            document_id=10,
            document_title="Academic Calendar",
            chunk_index=0,
            chunk_text="All final year projects must be submitted by Week 14.",
            access_level="STUDENT",
            similarity_score=0.92,
            section_path="Project Deadlines",
            chunk_type="DETAIL",
        )
    ]
    system_prompt, user_message = build_prompt(
        query="When is my FYP submission?",
        chunks=chunks,
        user_context=ctx,
    )

    assert "Kah Yuen Ho" in system_prompt
    assert "QIU-202407-000001" in system_prompt
    assert "Computer Science" in system_prompt
    assert "Context documents:" in user_message
    assert "When is my FYP submission?" in user_message
    assert "All final year projects must be submitted by Week 14." in user_message
