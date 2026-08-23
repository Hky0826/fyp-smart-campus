"""
Multi-format document extractor for RAG knowledge ingestion.

Supports:
- Plain Text & Markdown: .txt, .md
- Tabular CSV: .csv (converted to Markdown tables)
- Adobe PDF: .pdf (page-by-page structured extraction with pypdf and multimodal fallback)
- Microsoft Word: .docx, .doc (paragraphs, headings, lists, and tables with python-docx)
"""

from __future__ import annotations

import csv
import io
import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".csv",
    ".pdf",
    ".docx", ".doc",
}


def is_supported_document_extension(ext: str) -> bool:
    """Return True if the file extension is supported for ingestion."""
    if not ext:
        return False
    clean_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
    return clean_ext in SUPPORTED_EXTENSIONS


def _extract_from_plain_text(file_path: str) -> str:
    """Extract content from plain text (.txt) and Markdown (.md) files."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _extract_from_csv(file_path: str) -> str:
    """Extract CSV file and format into a structured Markdown table."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return ""

    headers = [col.strip() for col in rows[0]]
    if not headers or all(h == "" for h in headers):
        headers = [f"Column {i + 1}" for i in range(len(rows[0]))]

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows[1:]:
        if not any(col.strip() for col in row):
            continue
        padded = [row[i].strip() if i < len(row) else "" for i in range(len(headers))]
        # Escape any pipe characters inside table cells
        escaped = [col.replace("|", "\\|").replace("\n", " ") for col in padded]
        lines.append("| " + " | ".join(escaped) + " |")

    return "\n".join(lines)


def _extract_from_pdf(file_path: str) -> str:
    """Extract text from PDF documents page by page using pypdf."""
    try:
        import pypdf
    except ImportError:
        raise RuntimeError("pypdf is required for PDF ingestion. Please install pypdf.")

    page_texts = []
    has_scanned_pages = False
    scanned_page_indices = []

    with open(file_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        total_pages = len(reader.pages)

        for i, page in enumerate(reader.pages):
            page_num = i + 1
            extracted = (page.extract_text() or "").strip()
            # Clean null bytes and non-printable control characters
            extracted = extracted.replace("\x00", "").strip()

            if extracted and len(extracted) >= 40:
                page_texts.append(f"## Page {page_num}\n\n{extracted}")
            else:
                has_scanned_pages = True
                scanned_page_indices.append(i)

    # If the PDF is entirely or mostly scanned without selectable text, attempt multimodal fallback
    if (not page_texts or len("".join(page_texts).strip()) < 100) and has_scanned_pages:
        logger.info("PDF '%s' appears to be scanned or contains sparse text; attempting multimodal vision extraction...", file_path)
        try:
            from RagChatbot.gemini_client import get_gemini_client
            from google.genai import types

            client = get_gemini_client()
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()

            part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
            prompt = (
                "Extract and transcribe all text, headings, policies, schedules, and tables from this PDF document "
                "into clean, structured Markdown text. Preserve all numbers, dates, terms, and requirements accurately."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[part, prompt],
            )
            if response and response.text and len(response.text.strip()) > 50:
                logger.info("Successfully extracted scanned PDF via Gemini Vision (%d chars).", len(response.text))
                return response.text.strip()
        except Exception as exc:
            logger.warning("Multimodal PDF fallback failed: %s; falling back to extracted text.", exc)

    return "\n\n".join(page_texts)


def _extract_from_docx(file_path: str) -> str:
    """Extract paragraphs, headings, bullet lists, and tables from Word documents (.docx)."""
    try:
        import docx
    except ImportError:
        raise RuntimeError("python-docx is required for Word document ingestion. Please install python-docx.")

    doc = docx.Document(file_path)
    output_parts = []

    # 1. Extract paragraphs and headings
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = (para.style.name or "").lower()
        if "heading 1" in style_name or style_name == "title":
            output_parts.append(f"# {text}")
        elif "heading 2" in style_name:
            output_parts.append(f"## {text}")
        elif "heading 3" in style_name:
            output_parts.append(f"### {text}")
        elif "heading" in style_name:
            output_parts.append(f"#### {text}")
        elif "list" in style_name or "bullet" in style_name:
            output_parts.append(f"* {text}")
        else:
            output_parts.append(text)

    # 2. Extract tables and convert to Markdown format
    for table in doc.tables:
        table_rows = []
        for row in table.rows:
            row_cells = [cell.text.replace("\n", " ").replace("|", "\\|").strip() for cell in row.cells]
            # De-duplicate consecutive identical cells from merged columns
            deduped = []
            for c in row_cells:
                if not deduped or c != deduped[-1]:
                    deduped.append(c)
                else:
                    deduped.append("")
            if any(cell for cell in deduped):
                table_rows.append(deduped)

        if not table_rows:
            continue

        # Normalize column counts across rows
        max_cols = max(len(r) for r in table_rows)
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in table_rows]

        headers = normalized_rows[0]
        if all(h == "" for h in headers):
            headers = [f"Column {i + 1}" for i in range(max_cols)]

        table_md = []
        table_md.append("| " + " | ".join(headers) + " |")
        table_md.append("| " + " | ".join(["---"] * max_cols) + " |")

        for row in normalized_rows[1:]:
            table_md.append("| " + " | ".join(row) + " |")

        output_parts.append("\n".join(table_md))

    return "\n\n".join(output_parts)


def extract_text_from_file(file_path: str) -> str:
    """
    Dispatcher to extract text and structure from a supported file.

    Args:
        file_path: Path to the target document file.

    Returns:
        Extracted content formatted as Markdown.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is unsupported or content is empty.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found at '{file_path}'.")

    ext = Path(file_path).suffix.lower()
    if not is_supported_document_extension(ext):
        supported_str = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{ext}'. Supported formats: {supported_str}.")

    logger.info("Extracting document content from '%s' (format: %s)...", file_path, ext)

    if ext in (".txt", ".md"):
        content = _extract_from_plain_text(file_path)
    elif ext == ".csv":
        content = _extract_from_csv(file_path)
    elif ext == ".pdf":
        content = _extract_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        content = _extract_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported file extension '{ext}'.")

    content = content.strip()
    if not content:
        raise ValueError(f"No extractable text content found in '{os.path.basename(file_path)}'.")

    return content
