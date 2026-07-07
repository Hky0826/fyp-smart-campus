"""
Document service – high-level helpers for managing uploaded documents.

Provides read operations that respect the caller's context. This
service is used by the ingestion pipeline and any endpoint that needs
to list or inspect documents without going through the admin dashboard router.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_active_document(document_id: int, db: Session):
    """
    Retrieve a single active, non-deleted UploadedDocument by ID.

    Args:
        document_id: Primary key of the document.
        db: Active SQLAlchemy session.

    Returns:
        UploadedDocument ORM instance, or None if not found.
    """
    from app.models.models import UploadedDocument

    return (
        db.query(UploadedDocument)
        .filter_by(document_id=document_id, is_active=True)
        .first()
    )


def get_all_active_documents(db: Session) -> List:
    """
    Return all active documents (is_active=True).

    Used by the ingestion service to list documents pending indexing.
    """
    from app.models.models import UploadedDocument

    return db.query(UploadedDocument).filter_by(is_active=True).all()


def document_has_embeddings(document_id: int, db: Session) -> bool:
    """
    Check whether a document already has at least one embedding vector.

    Args:
        document_id: The document to check.
        db: Active session.

    Returns:
        True if any non-outdated chunks with embeddings exist.
    """
    from app.models.models import DocumentChunk, EmbeddingVector

    count = (
        db.query(EmbeddingVector)
        .join(DocumentChunk, EmbeddingVector.chunk_id == DocumentChunk.chunk_id)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.is_outdated.is_(False),
        )
        .count()
    )
    return count > 0
