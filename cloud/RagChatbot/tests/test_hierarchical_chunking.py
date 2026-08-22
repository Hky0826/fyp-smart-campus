"""Unit tests for Hierarchical Parent-Child Chunking."""

import pytest
from RagChatbot.services.ingestion_service import _build_hierarchical_chunks


def test_build_hierarchical_chunks():
    sample_md = """# Faculty of Science and Technology

## Bachelor of Computer Science (Hons)

The Bachelor of Computer Science is a 3-year full-time undergraduate programme.
Course codes include BCS204 and BCS3114.

### Tuition Fees
| Programme | Total Fee | Duration |
|---|---|---|
| BCS | RM 45,000 | 3 Years |
| BIT | RM 42,000 | 3 Years |

### Contact Information
Please contact Dr. Sharanjit Kaur for academic inquiries at Room B-2-04.
"""
    parents = _build_hierarchical_chunks(sample_md, doc_title="Programmes")
    assert len(parents) >= 2  # Overview + sections
    
    # Check Document Overview
    overview = [p for p in parents if p.chunk_type == "SUMMARY"]
    assert len(overview) >= 1
    assert "Overview" in overview[0].section_path
    
    # Check Parent section containing tables
    fee_parents = [p for p in parents if "Tuition Fees" in p.section_path or "Computer Science" in p.section_path]
    assert len(fee_parents) >= 1
    
    # Verify child chunks
    all_children = [c for p in parents for c in p.children]
    table_children = [c for c in all_children if c.chunk_type == "TABLE"]
    assert len(table_children) >= 1
    assert any("BCS" in c.text and "45,000" in c.text for c in table_children)
    
    # Verify entity tags in child chunks
    detail_children = [c for c in all_children if any(t.get("entity_code") == "BCS204" for t in c.entity_tags)]
    assert len(detail_children) >= 1
