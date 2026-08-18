"""Transactional document chunking and embedding ingestion."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List

import numpy as np
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.embedding_utils import vector_to_mysql_string
from RagChatbot.embeddings.google_embedding_service import embed_document_chunk
from RagChatbot.services.document_service import get_active_document

logger = logging.getLogger(__name__)
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 150


@dataclass
class IngestionResult:
    document_id: int
    chunks_created: int
    embeddings_created: int
    skipped: int
    message: str
    status: str = "FAILED"


def _split_into_chunks(text: str, chunk_size: int, overlap: int) -> List[str]:
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
    if not os.path.isabs(file_path):
        from app.core.private_storage import safe_existing_path
        file_path = str(safe_existing_path("documents", file_path))
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".txt", ".md", ".csv"):
        raise ValueError(f"Unsupported file type '{ext}'. Supported: .txt, .md, .csv.")
    with open(file_path, "r", encoding="utf-8", errors="replace") as file:
        return file.read()


def _failed(document_id: int, message: str, skipped: int = 0) -> IngestionResult:
    return IngestionResult(document_id, 0, 0, skipped, message, status="FAILED")


def ingest_document(document_id: int, db: Session, force_reindex: bool = False) -> IngestionResult:
    from app.models.models import DocumentChunk, EmbeddingVector

    doc = get_active_document(document_id, db)
    if not doc:
        return _failed(document_id, f"Document ID {document_id} not found or is inactive.")

    try:
        text = _load_document_text(doc.file_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Ingestion failed for document_id=%d: %s", document_id, exc)
        return _failed(document_id, str(exc))

    text_chunks = _split_into_chunks(text, _CHUNK_SIZE, _CHUNK_OVERLAP)
    staged: list[tuple[int, str, object]] = []
    skipped = 0
    for idx, chunk_text in enumerate(text_chunks):
        try:
            vector = embed_document_chunk(chunk_text)
            array = np.asarray(vector, dtype=np.float32).reshape(-1)
            if array.size == 0 or not np.isfinite(array).all() or float(np.linalg.norm(array)) <= 1e-12:
                raise ValueError("embedding is empty, non-finite, or zero-norm")
            # Convert now, while the old index is still untouched.  This also
            # catches malformed provider output before any DB invalidation.
            vector_to_mysql_string(array.tolist())
            staged.append((idx, chunk_text, array.tolist()))
        except Exception as exc:
            skipped += 1
            logger.error("Embedding failed for chunk %d of document_id=%d: %s", idx, document_id, exc)

    if not staged:
        return _failed(document_id, f"No usable embeddings were produced for document '{doc.title}'.", skipped)

    new_vectors: list[tuple[int, str, list[float]]] = []
    try:
        # Invalidation happens only after at least one complete usable vector
        # has been staged.  A failed reindex therefore leaves old chunks live.
        for old_chunk in db.query(DocumentChunk).filter_by(document_id=document_id).all():
            old_chunk.is_outdated = True
        for chunk_index, chunk_text, vector in staged:
            chunk_record = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                char_count=len(chunk_text),
                # UploadedDocument.access_level is authoritative.  Chunks are
                # refreshed in the same transaction as the document's index.
                access_level=doc.access_level,
                is_outdated=False,
            )
            db.add(chunk_record)
            db.flush()
            db.add(EmbeddingVector(
                chunk_id=chunk_record.chunk_id,
                embedding=vector_to_mysql_string(vector),
                model_version=rag_settings.EMBEDDING_MODEL,
            ))
            new_vectors.append((chunk_record.chunk_id, doc.access_level, vector))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Ingestion DB commit failed for document_id=%d: %s", document_id, exc)
        return _failed(document_id, f"Database commit failed: {exc}", skipped + len(staged))

    from RagChatbot.retrieval.vector_store import vector_store
    if vector_store.is_loaded:
        vector_store.replace_document(document_id, new_vectors)

    from RagChatbot.embeddings.google_embedding_service import clear_embedding_cache
    from RagChatbot.services.chat_service import clear_rag_response_cache
    clear_embedding_cache()
    clear_rag_response_cache()

    return IngestionResult(
        document_id=document_id,
        chunks_created=len(staged),
        embeddings_created=len(staged),
        skipped=skipped,
        message=(f"Document '{doc.title}' ingested successfully: {len(staged)} chunks, "
                 f"{len(staged)} embeddings. {skipped} chunks skipped."),
        status="COMPLETED",
    )
