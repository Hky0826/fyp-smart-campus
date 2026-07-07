"""
Document ingestion service.

Handles the pipeline for processing a new or updated document into
the RAG knowledge base:

    1. Load document content from disk.
    2. Split text into overlapping chunks.
    3. Generate a Google AI embedding for each chunk.
    4. Persist DocumentChunk and EmbeddingVector rows to MySQL.

This service is intended to be called by the /api/chatbot/ingest endpoint
and can also be triggered manually from scripts.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.embedding_utils import vector_to_mysql_string
from RagChatbot.embeddings.google_embedding_service import embed_document_chunk
from RagChatbot.services.document_service import get_active_document

logger = logging.getLogger(__name__)

# Chunking parameters (can be moved to config in the future)
_CHUNK_SIZE = 800        # characters per chunk
_CHUNK_OVERLAP = 150     # overlap between consecutive chunks


@dataclass
class IngestionResult:
    document_id: int
    chunks_created: int
    embeddings_created: int
    skipped: int
    message: str


def _split_into_chunks(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Split a document text into overlapping fixed-size character chunks.

    Args:
        text: The full document text.
        chunk_size: Maximum characters per chunk.
        overlap: Number of characters shared between consecutive chunks.

    Returns:
        List of text chunk strings.
    """
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def _load_document_text(file_path: str) -> str:
    """
    Load plain text from a document file.
    Currently supports .txt and .md files.
    For PDF/DOCX, extend with appropriate libraries (e.g., pypdf, python-docx).

    Args:
        file_path: Absolute or relative path to the document file.

    Returns:
        The text content as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file type is unsupported.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".txt", ".md", ".csv"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            "Supported: .txt, .md, .csv. For PDF/DOCX, extend _load_document_text()."
        )


def ingest_document(
    document_id: int,
    db: Session,
    force_reindex: bool = False,
) -> IngestionResult:
    """
    Ingest or re-index a document into the RAG knowledge base.

    Args:
        document_id: ID of an existing UploadedDocument record.
        db: Active SQLAlchemy session.
        force_reindex: If True, existing chunks and embeddings are
                       marked outdated and regenerated.

    Returns:
        IngestionResult summarizing what was created.
    """
    from app.models.models import DocumentChunk, EmbeddingVector

    doc = get_active_document(document_id, db)
    if not doc:
        return IngestionResult(
            document_id=document_id,
            chunks_created=0,
            embeddings_created=0,
            skipped=0,
            message=f"Document ID {document_id} not found or is inactive.",
        )

    # Optionally mark existing chunks as outdated before reprocessing
    if force_reindex:
        existing_chunks = (
            db.query(DocumentChunk).filter_by(document_id=document_id).all()
        )
        for chunk in existing_chunks:
            chunk.is_outdated = True
        db.flush()
        logger.info(
            "Reindex: marked %d existing chunks as outdated for document_id=%d",
            len(existing_chunks),
            document_id,
        )

    # Load text content from disk
    try:
        text = _load_document_text(doc.file_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Ingestion failed for document_id=%d: %s", document_id, exc)
        return IngestionResult(
            document_id=document_id,
            chunks_created=0,
            embeddings_created=0,
            skipped=0,
            message=str(exc),
        )

    text_chunks = _split_into_chunks(text, _CHUNK_SIZE, _CHUNK_OVERLAP)
    logger.info(
        "Ingestion: document_id=%d '%s' -> %d chunks",
        document_id,
        doc.title,
        len(text_chunks),
    )

    chunks_created = 0
    embeddings_created = 0
    skipped = 0

    for idx, chunk_text in enumerate(text_chunks):
        # Create DocumentChunk row
        chunk_record = DocumentChunk(
            document_id=document_id,
            chunk_index=idx,
            chunk_text=chunk_text,
            char_count=len(chunk_text),
            access_level=doc.access_level,
            is_outdated=False,
        )
        db.add(chunk_record)
        db.flush()  # populate chunk_id before embedding

        # Generate embedding
        try:
            embedding_vec = embed_document_chunk(chunk_text)
        except RuntimeError as exc:
            logger.error(
                "Embedding failed for chunk %d of document_id=%d: %s",
                idx,
                document_id,
                exc,
            )
            skipped += 1
            continue

        # Persist EmbeddingVector
        vec_str = vector_to_mysql_string(embedding_vec)
        emb_record = EmbeddingVector(
            chunk_id=chunk_record.chunk_id,
            embedding=vec_str,
            model_version=rag_settings.EMBEDDING_MODEL,
        )
        db.add(emb_record)
        chunks_created += 1
        embeddings_created += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Ingestion DB commit failed for document_id=%d: %s", document_id, exc)
        return IngestionResult(
            document_id=document_id,
            chunks_created=0,
            embeddings_created=0,
            skipped=len(text_chunks),
            message=f"Database commit failed: {exc}",
        )

    return IngestionResult(
        document_id=document_id,
        chunks_created=chunks_created,
        embeddings_created=embeddings_created,
        skipped=skipped,
        message=(
            f"Document '{doc.title}' ingested successfully: "
            f"{chunks_created} chunks, {embeddings_created} embeddings. "
            f"{skipped} chunks skipped due to embedding errors."
        ),
    )
