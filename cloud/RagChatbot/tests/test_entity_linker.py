"""Unit tests for Relational Campus Entity Linker."""

import pytest
from RagChatbot.services.entity_linker import extract_entity_tags


def test_extract_course_and_room_entities():
    text = "Students enrolled in BCS204 and BCS3114 must attend lecture in Room B-2-04 near Block A."
    tags = extract_entity_tags(text, db=None)
    course_codes = [t["entity_code"] for t in tags if t.get("entity_type") == "COURSE"]
    assert "BCS204" in course_codes
    assert "BCS3114" in course_codes
    
    room_labels = [t["label"] for t in tags if t.get("entity_type") == "ROOM_LABEL"]
    assert any("B-2-04" in lbl for lbl in room_labels)


def test_extract_staff_and_facility_entities():
    text = "For Bachelor of Computer Science inquiries, contact Dr. Sharanjit Kaur at the Admissions and Records Department or Cashier."
    tags = extract_entity_tags(text, db=None)
    staff_names = [t.get("name") for t in tags if t.get("entity_type") == "STAFF"]
    assert any("Sharanjit Kaur" in str(name) for name in staff_names)
    
    facilities = [t.get("label") for t in tags if t.get("entity_type") in ("FACILITY", "NODE")]
    assert "Admissions and Records Department" in facilities
    assert "Cashier" in facilities
