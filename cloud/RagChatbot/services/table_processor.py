"""
Table normalization and semantic expansion pipeline for RAG documents.

Preprocesses Markdown pipe tables into:
1. Pristine preserved Markdown table blocks for Parent Chunks (1500-2500 chars).
2. Natural language expanded statements for Child Chunks (250-400 chars, chunk_type='TABLE')
   that preserve spatial row-column semantics in dense vector space and BM25 token index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class TableBlock:
    """Represents a parsed Markdown table with raw and expanded representations."""
    raw_markdown: str
    caption: str = ""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    semantic_rows: List[str] = field(default_factory=list)
    start_pos: int = 0
    end_pos: int = 0


_TABLE_ROW_REGEX = re.compile(r"^\s*\|(.+)\|\s*$")
_ALIGNMENT_ROW_REGEX = re.compile(r"^\s*\|?\s*[-:]+[-| :]*\|\s*$")


def is_table_line(line: str) -> bool:
    """Check if a line looks like a markdown table row."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_alignment_row(line: str) -> bool:
    """Check if a table line is a markdown separator/alignment line (|---|---|)."""
    return bool(_ALIGNMENT_ROW_REGEX.match(line.strip()))


def split_table_cells(row_line: str) -> List[str]:
    """Split a markdown table row into trimmed cell values."""
    trimmed = row_line.strip()
    if trimmed.startswith("|"):
        trimmed = trimmed[1:]
    if trimmed.endswith("|"):
        trimmed = trimmed[:-1]
    return [cell.strip() for cell in trimmed.split("|")]


def expand_row_to_statement(headers: List[str], row_cells: List[str], caption: str = "") -> str:
    """
    Convert a single table row and its headers into an explicit natural language statement.
    Example:
      Headers: ['Qualification', 'Academic Requirement', 'Scholarship']
      Row: ['UEC', '7As', '50%']
      Caption: 'QIU Undergraduate Scholarship'
      -> 'Under QIU Undergraduate Scholarship: for Qualification "UEC", Academic Requirement is "7As", with Scholarship "50%".'
    """
    context_prefix = f"Under {caption}: " if caption.strip() else "Table entry: "
    pairs: List[str] = []

    for idx, cell in enumerate(row_cells):
        if not cell:
            continue
        header = headers[idx] if idx < len(headers) and headers[idx].strip() else f"Column {idx+1}"
        if header.lower() in cell.lower():
            pairs.append(cell)
        else:
            pairs.append(f"{header} is {cell}")

    if not pairs:
        return ""
    
    return context_prefix + ", ".join(pairs) + "."


def extract_tables_from_markdown(text: str, default_caption: str = "") -> List[TableBlock]:
    """
    Scan markdown text and parse all pipe tables into TableBlock instances with semantic expansions.
    """
    lines = text.splitlines()
    tables: List[TableBlock] = []
    
    current_table_lines: List[str] = []
    current_caption = default_caption
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Track heading or label directly above a table as caption
        if line.startswith("#"):
            current_caption = line.lstrip("#").strip()
            i += 1
            continue
        elif line.strip().endswith(":") and not is_table_line(line):
            current_caption = line.strip().rstrip(":")
            i += 1
            continue

        if is_table_line(line):
            current_table_lines = [line]
            i += 1
            while i < len(lines) and is_table_line(lines[i]):
                current_table_lines.append(lines[i])
                i += 1
            
            # Process table if it has at least 2 rows (header + at least 1 row/alignment)
            if len(current_table_lines) >= 2:
                raw_table = "\n".join(current_table_lines)
                
                # Parse headers from first row
                headers = split_table_cells(current_table_lines[0])
                
                # Process data rows
                rows: List[List[str]] = []
                semantic_statements: List[str] = []
                
                for r_line in current_table_lines[1:]:
                    if is_alignment_row(r_line):
                        continue
                    cells = split_table_cells(r_line)
                    if any(cells):
                        rows.append(cells)
                        statement = expand_row_to_statement(headers, cells, current_caption)
                        if statement:
                            semantic_statements.append(statement)
                
                tables.append(TableBlock(
                    raw_markdown=raw_table,
                    caption=current_caption,
                    headers=headers,
                    rows=rows,
                    semantic_rows=semantic_statements,
                ))
            current_table_lines = []
        else:
            i += 1

    return tables
