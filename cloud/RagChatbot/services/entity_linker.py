"""
Relational Campus Entity Linker for RAG Document Chunks.

Extracts and binds structured entity references from text chunks to relational database entities:
1. Room / Facility / Location -> nodes.node_id
2. Staff / Lecturer / Coordinator -> users.user_id, lecturers.office_node_id
3. Course Code -> courses.course_id, courses.course_code
4. Policy Identifiers -> policy reference strings
"""

from __future__ import annotations

import re
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Precompiled regex patterns for campus identifiers
_ROOM_CODE_PATTERN = re.compile(r"\b([A-Z]-\d{1,2}-\d{1,2}|Room\s+\d{2,4}|Block\s+[A-Z])\b", re.IGNORECASE)
_COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{3,4}\s*\d{3,4}[A-Z]?)\b")
_POLICY_CODE_PATTERN = re.compile(r"\b(POL-[A-Z0-9\-]+|JPT/[A-Z0-9\(\)/]+|MQA/[A-Z0-9/]+)\b", re.IGNORECASE)

# Standard campus room and facility aliases mapped to known room labels
_KNOWN_FACILITY_LABELS = [
    "Reception",
    "Admissions and Records Department",
    "Student Recruitment Division",
    "International Student Office",
    "Career and Professional Development",
    "Student Life Division",
    "Cashier",
    "Bursary Office",
    "Administration and Maintenance Division",
    "Digital Communications Department",
    "Conference Room",
    "Boardroom 1",
    "La Place Cafe",
    "Library",
    "ATM",
    "Unisex Washroom",
]

# Standard known coordinators and faculty members mentioned in official documents
_KNOWN_STAFF_MAP = {
    "sharanjit kaur": {"name": "Dr. Sharanjit Kaur", "role": "Programme Coordinator (Computer Science)"},
    "cheang kah wai": {"name": "Mr. Cheang Kah Wai, Alvin", "role": "Programme Coordinator (IT)"},
    "mad helmi": {"name": "Dr. Mad Helmi Bin. Ab. Majid", "role": "Programme Coordinator (Mechatronics)"},
    "muthulumar": {"name": "Mr. Muthulumar Vellaisamy", "role": "Programme Coordinator (Electronics)"},
    "kamariah hasan": {"name": "Dr. Kamariah Hasan", "role": "Programme Coordinator (Biotechnology)"},
    "annie poh": {"name": "Dr. Annie Poh Woon Cheng", "role": "Programme Coordinator (Biomedical Sciences)"},
    "li rui": {"name": "Ms Li Rui", "role": "Student Recruitment Division"},
}


def _fetch_node_catalog(db: Optional[Session]) -> List[Dict[str, Any]]:
    """Query nodes table for known navigable locations."""
    if db is None:
        return []
    try:
        from app.models.models import Node
        nodes = db.query(Node.node_id, Node.room_label, Node.node_type).filter(Node.room_label.isnot(None)).all()
        return [{"node_id": n.node_id, "room_label": n.room_label, "node_type": str(n.node_type)} for n in nodes]
    except Exception as exc:
        logger.debug("Failed to fetch node catalog from DB: %s", exc)
        return []


def _fetch_user_catalog(db: Optional[Session]) -> List[Dict[str, Any]]:
    """Query users and lecturers for known academic personnel."""
    if db is None:
        return []
    try:
        from app.models.models import User, Lecturer
        lecturers = db.query(
            User.user_id,
            User.given_name,
            User.family_name,
            Lecturer.office_node_id,
            Lecturer.position
        ).outerjoin(Lecturer, User.user_id == Lecturer.user_id).all()
        
        results = []
        for l in lecturers:
            full_name = f"{l.given_name} {l.family_name}".strip()
            results.append({
                "user_id": l.user_id,
                "full_name": full_name,
                "office_node_id": l.office_node_id,
                "position": l.position,
            })
        return results
    except Exception as exc:
        logger.debug("Failed to fetch user catalog from DB: %s", exc)
        return []


def extract_entity_tags(text_content: str, db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Scan text content and return a deduplicated list of structured entity tag dictionaries.
    """
    if not text_content:
        return []

    tags: List[Dict[str, Any]] = []
    seen_keys = set()

    # 1. Course Code Extraction
    for match in _COURSE_CODE_PATTERN.finditer(text_content):
        code = match.group(1).replace(" ", "").upper()
        key = f"course:{code}"
        if key not in seen_keys:
            seen_keys.add(key)
            tags.append({
                "entity_type": "COURSE",
                "entity_code": code,
            })

    # 2. Room Code Regex Extraction
    for match in _ROOM_CODE_PATTERN.finditer(text_content):
        room_str = match.group(1).strip()
        key = f"room_str:{room_str.upper()}"
        if key not in seen_keys:
            seen_keys.add(key)
            tags.append({
                "entity_type": "ROOM_LABEL",
                "label": room_str,
            })

    # 3. Policy Code Regex Extraction
    for match in _POLICY_CODE_PATTERN.finditer(text_content):
        pol = match.group(1).strip()
        key = f"policy:{pol.upper()}"
        if key not in seen_keys:
            seen_keys.add(key)
            tags.append({
                "entity_type": "POLICY",
                "policy_code": pol,
            })

    # 4. Facility and Room Name Matching
    node_catalog = _fetch_node_catalog(db)
    if node_catalog:
        text_lower = text_content.lower()
        for node in node_catalog:
            label = (node.get("room_label") or "").strip()
            if len(label) >= 4 and label.lower() in text_lower:
                key = f"node:{node['node_id']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    tags.append({
                        "entity_type": "NODE",
                        "node_id": node["node_id"],
                        "label": label,
                        "node_type": node.get("node_type"),
                    })
    else:
        # Fallback to standard facility labels if DB not provided
        text_lower = text_content.lower()
        for label in _KNOWN_FACILITY_LABELS:
            if label.lower() in text_lower:
                key = f"facility:{label.lower()}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    tags.append({
                        "entity_type": "FACILITY",
                        "label": label,
                    })

    # 5. Staff and Lecturer Matching
    user_catalog = _fetch_user_catalog(db)
    text_lower = text_content.lower()
    if user_catalog:
        for u in user_catalog:
            fn = u["full_name"].lower()
            if len(fn) >= 4 and fn in text_lower:
                key = f"user:{u['user_id']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    tags.append({
                        "entity_type": "STAFF",
                        "user_id": u["user_id"],
                        "name": u["full_name"],
                        "office_node_id": u.get("office_node_id"),
                        "position": u.get("position"),
                    })
    
    # Also check known faculty aliases
    for alias, info in _KNOWN_STAFF_MAP.items():
        if alias in text_lower:
            key = f"staff_alias:{alias}"
            if key not in seen_keys:
                seen_keys.add(key)
                tags.append({
                    "entity_type": "STAFF",
                    "name": info["name"],
                    "role": info["role"],
                })

    return tags
