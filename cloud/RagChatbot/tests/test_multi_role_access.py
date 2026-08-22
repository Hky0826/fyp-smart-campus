"""
Unit and integration tests for Multi-Role Document Authorization & RBAC Filtering.
Verifies that:
1. Canonical roles (VISITOR, STUDENT, LECTURER, STAFF, ADMIN) are supported.
2. Documents can have multiple roles (e.g. ["STAFF", "LECTURER"]).
3. Access filtering enforces intersection between caller roles and document allowed_roles.
4. Anonymous visitors only see documents tagged with VISITOR.
5. In-Memory Vector Store builds accurate boolean filter masks for multi-role queries.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

from RagChatbot.retrieval.access_filter import filter_chunks_by_access, _extract_chunk_roles
from RagChatbot.security.rbac import get_user_roles, resolve_allowed_access_levels
from RagChatbot.retrieval.vector_store import InMemoryVectorStore


class MockChunk:
    def __init__(self, chunk_id: int, allowed_roles: list, access_level: str = "VISITOR"):
        self.chunk_id = chunk_id
        self.allowed_roles = allowed_roles
        self.access_level = access_level


def test_extract_chunk_roles():
    # List format
    c1 = MockChunk(1, ["STAFF", "LECTURER"])
    assert _extract_chunk_roles(c1) == {"STAFF", "LECTURER"}

    # JSON string format
    c2 = MockChunk(2, '["STUDENT", "VISITOR"]')
    assert _extract_chunk_roles(c2) == {"STUDENT", "VISITOR"}

    # Fallback to access_level if allowed_roles is None
    c3 = MockChunk(3, None, access_level="STUDENT")
    assert _extract_chunk_roles(c3) == {"STUDENT"}

    # Fallback PUBLIC to VISITOR
    c4 = MockChunk(4, None, access_level="PUBLIC")
    assert _extract_chunk_roles(c4) == {"VISITOR"}


def test_filter_chunks_by_access_visitor():
    chunks = [
        MockChunk(1, ["VISITOR"]),
        MockChunk(2, ["STUDENT"]),
        MockChunk(3, ["STAFF", "LECTURER"]),
        MockChunk(4, ["ADMIN"]),
    ]
    # Visitor should only see VISITOR chunks
    allowed = filter_chunks_by_access(chunks, ["VISITOR"])
    chunk_ids = [c.chunk_id for c in allowed]
    assert chunk_ids == [1]


def test_filter_chunks_by_access_student():
    chunks = [
        MockChunk(1, ["VISITOR"]),
        MockChunk(2, ["STUDENT"]),
        MockChunk(3, ["STAFF", "LECTURER"]),
        MockChunk(4, ["ADMIN"]),
        MockChunk(5, ["STUDENT", "LECTURER"]),
    ]
    # Student has ["STUDENT", "VISITOR"]
    allowed = filter_chunks_by_access(chunks, ["STUDENT", "VISITOR"])
    chunk_ids = [c.chunk_id for c in allowed]
    assert chunk_ids == [1, 2, 5]


def test_filter_chunks_by_access_staff_and_lecturer():
    chunks = [
        MockChunk(1, ["VISITOR"]),
        MockChunk(2, ["STUDENT"]),
        MockChunk(3, ["STAFF", "LECTURER"]),
        MockChunk(4, ["ADMIN"]),
        MockChunk(5, ["STAFF"]),
    ]
    # Staff user has ["STAFF", "VISITOR"]
    staff_allowed = filter_chunks_by_access(chunks, ["STAFF", "VISITOR"])
    assert [c.chunk_id for c in staff_allowed] == [1, 3, 5]

    # Lecturer user has ["LECTURER", "VISITOR"]
    lecturer_allowed = filter_chunks_by_access(chunks, ["LECTURER", "VISITOR"])
    assert [c.chunk_id for c in lecturer_allowed] == [1, 3]


def test_filter_chunks_by_access_admin_bypass():
    chunks = [
        MockChunk(1, ["VISITOR"]),
        MockChunk(2, ["STUDENT"]),
        MockChunk(3, ["STAFF", "LECTURER"]),
        MockChunk(4, ["ADMIN"]),
    ]
    # Admin sees all chunks
    admin_allowed = filter_chunks_by_access(chunks, ["ADMIN", "VISITOR"])
    assert len(admin_allowed) == 4


def test_rbac_resolve_allowed_access_levels():
    # Anonymous / empty
    assert resolve_allowed_access_levels([]) == ["VISITOR"]

    # Student
    student_roles = resolve_allowed_access_levels(["STUDENT"])
    assert "STUDENT" in student_roles and "VISITOR" in student_roles

    # Admin expands to all canonical roles
    admin_roles = resolve_allowed_access_levels(["ADMIN"])
    assert set(admin_roles) >= {"VISITOR", "STUDENT", "LECTURER", "STAFF", "ADMIN"}


def test_vector_store_multi_role_mask():
    store = InMemoryVectorStore()
    store._reset_empty()

    # Add chunks with different multi-role assignments
    store.add_chunk(1, "VISITOR", [0.1, 0.2], allowed_roles=["VISITOR"])
    store.add_chunk(2, "VISITOR", [0.2, 0.3], allowed_roles=["STUDENT"])
    store.add_chunk(3, "VISITOR", [0.3, 0.4], allowed_roles=["STAFF", "LECTURER"])
    store.add_chunk(4, "VISITOR", [0.4, 0.5], allowed_roles=["ADMIN"])

    # 1. Visitor Mask
    vis_mask = store._build_filter_mask(["VISITOR"])
    assert np.array_equal(vis_mask, [True, False, False, False])

    # 2. Student Mask (inherits VISITOR)
    stud_mask = store._build_filter_mask(["STUDENT", "VISITOR"])
    assert np.array_equal(stud_mask, [True, True, False, False])

    # 3. Staff Mask (inherits VISITOR and matches multi-role chunk 3)
    staff_mask = store._build_filter_mask(["STAFF", "VISITOR"])
    assert np.array_equal(staff_mask, [True, False, True, False])

    # 4. Admin Mask (bypasses all)
    admin_mask = store._build_filter_mask(["ADMIN", "VISITOR"])
    assert np.array_equal(admin_mask, [True, True, True, True])
