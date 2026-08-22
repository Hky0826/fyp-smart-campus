"""Unit tests for Table Processor & Semantic Row Expansion."""

import pytest
from RagChatbot.services.table_processor import (
    extract_tables_from_markdown,
    expand_row_to_statement,
    is_table_line,
)


def test_is_table_line():
    assert is_table_line("| Col 1 | Col 2 |") is True
    assert is_table_line("|---|---|") is True
    assert is_table_line("Regular text line") is False
    assert is_table_line("| Single pipe only") is False


def test_expand_row_to_statement():
    headers = ["Qualification", "Academic Requirement", "Scholarship"]
    row = ["UEC", "7As", "50%"]
    stmt = expand_row_to_statement(headers, row, caption="QIU Undergraduate Scholarship")
    assert "Under QIU Undergraduate Scholarship:" in stmt
    assert "Qualification is UEC" in stmt or "UEC" in stmt
    assert "Academic Requirement is 7As" in stmt
    assert "Scholarship is 50%" in stmt


def test_extract_tables_from_markdown():
    md_content = """# Fees and Scholarships

### QIU Undergraduate Scholarship
| Qualification | Academic Requirement | Scholarship |
|---|---|---|
| UEC | 7As | 50% |
| STPM | CGPA 3.80 | 50% |

Some text after table.
"""
    tables = extract_tables_from_markdown(md_content)
    assert len(tables) == 1
    t = tables[0]
    assert t.caption == "QIU Undergraduate Scholarship"
    assert t.headers == ["Qualification", "Academic Requirement", "Scholarship"]
    assert len(t.rows) == 2
    assert len(t.semantic_rows) == 2
    assert "7As" in t.semantic_rows[0]
    assert "STPM" in t.semantic_rows[1]
