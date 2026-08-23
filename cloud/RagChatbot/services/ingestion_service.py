"""
Transactional hierarchical document chunking and embedding ingestion service.

Implements Parent-Child (Hierarchical) Chunk Storage:
- Parent Chunks (1,500 – 2,500 chars): Preserves complete section context, unsevered policy conditions,
  and raw Markdown tables in MySQL.
- Child Chunks (250 – 400 chars): Fine-grained semantic units (narrative clauses, expanded table rows, FAQ items)
  indexed into native 3072-dim vector embeddings and BM25 token index.
- Section Summaries (chunk_type='SUMMARY'): Overarching document & section overviews for broad inquiries.
- Relational Entity Tags (entity_tags): JSON array linking text to nodes (rooms) and users (staff).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.embedding_utils import vector_to_mysql_string
from RagChatbot.embeddings.google_embedding_service import embed_document_chunk, embed_document_chunks_batch
from RagChatbot.services.document_service import get_active_document
from RagChatbot.services.document_loader import extract_text_from_file, is_supported_document_extension
from RagChatbot.services.table_processor import extract_tables_from_markdown, TableBlock
from RagChatbot.services.entity_linker import extract_entity_tags

logger = logging.getLogger(__name__)

_PARENT_CHUNK_TARGET = 2000
_PARENT_CHUNK_MAX = 2800
_CHILD_CHUNK_TARGET = 350
_CHILD_CHUNK_OVERLAP = 60


@dataclass
class ChildChunkItem:
    text: str
    chunk_type: str  # DETAIL, TABLE, FAQ, SUMMARY
    section_path: str
    entity_tags: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ParentChunkItem:
    text: str
    chunk_type: str  # PARENT, SUMMARY
    section_path: str
    entity_tags: List[Dict[str, Any]] = field(default_factory=list)
    children: List[ChildChunkItem] = field(default_factory=list)


@dataclass
class IngestionResult:
    document_id: int
    chunks_created: int
    embeddings_created: int
    skipped: int
    message: str
    status: str = "FAILED"


def _split_narrative_into_children(
    text: str,
    section_path: str,
    chunk_size: int = _CHILD_CHUNK_TARGET,
    overlap: int = _CHILD_CHUNK_OVERLAP,
    db: Optional[Session] = None,
) -> List[ChildChunkItem]:
    """Split narrative paragraphs into small, precise child chunks (250-400 chars)."""
    prefix = f"[{section_path}]\n" if section_path else ""
    paragraphs = re.split(r"\n{2,}", text)
    children: List[ChildChunkItem] = []
    
    accumulated: List[str] = []
    current_len = len(prefix)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Detect FAQ question/answer pattern
        is_faq = bool(re.match(r"^(Q:|Question:|FAQ|\d+\.)", para, re.IGNORECASE))
        c_type = "FAQ" if is_faq else "DETAIL"

        para_len = len(para) + 2
        if current_len + para_len > chunk_size and accumulated:
            body = "\n\n".join(accumulated).strip()
            full_text = f"{prefix}{body}".strip()
            tags = extract_entity_tags(full_text, db=db)
            children.append(ChildChunkItem(
                text=full_text,
                chunk_type=c_type,
                section_path=section_path,
                entity_tags=tags,
            ))
            
            last_p = accumulated[-1]
            if len(last_p) < overlap:
                accumulated = [last_p, para]
                current_len = len(prefix) + len(last_p) + para_len
            else:
                accumulated = [para]
                current_len = len(prefix) + para_len
        else:
            accumulated.append(para)
            current_len += para_len

    if accumulated:
        body = "\n\n".join(accumulated).strip()
        full_text = f"{prefix}{body}".strip()
        tags = extract_entity_tags(full_text, db=db)
        children.append(ChildChunkItem(
            text=full_text,
            chunk_type="DETAIL",
            section_path=section_path,
            entity_tags=tags,
        ))

    return [c for c in children if c.text.strip()]


def _build_hierarchical_chunks(
    text: str,
    doc_title: str = "",
    db: Optional[Session] = None,
) -> List[ParentChunkItem]:
    """
    Parse document into hierarchical structure:
    1. Overarching Document & Section Summary Chunks
    2. Parent Chunks (1,500 - 2,500 chars) with pristine tables & policy context
    3. Child Chunks (250 - 400 chars) with semantic row expansions & keyword tags
    """
    lines = text.splitlines()
    sections: List[Tuple[List[str], str]] = []  # (breadcrumb_list, content_block)

    current_h1 = ""
    current_h2 = ""
    current_h3 = ""
    current_block: List[str] = []

    def current_breadcrumbs() -> List[str]:
        crumbs = []
        if doc_title:
            crumbs.append(doc_title.strip())
        if current_h1:
            crumbs.append(current_h1)
        if current_h2:
            crumbs.append(current_h2)
        if current_h3:
            crumbs.append(current_h3)
        return crumbs

    for line in lines:
        h1_match = re.match(r"^#\s+(.+)$", line)
        h2_match = re.match(r"^##\s+(.+)$", line)
        h3_match = re.match(r"^###\s+(.+)$", line)

        if h1_match or h2_match or h3_match:
            if current_block:
                block_text = "\n".join(current_block).strip()
                if block_text:
                    sections.append((current_breadcrumbs(), block_text))
                current_block = []

            if h1_match:
                current_h1 = h1_match.group(1).strip()
                current_h2 = ""
                current_h3 = ""
            elif h2_match:
                current_h2 = h2_match.group(1).strip()
                current_h3 = ""
            elif h3_match:
                current_h3 = h3_match.group(1).strip()

            current_block.append(line)
        else:
            current_block.append(line)

    if current_block:
        block_text = "\n".join(current_block).strip()
        if block_text:
            sections.append((current_breadcrumbs(), block_text))

    if not sections:
        sections.append(([doc_title] if doc_title else [], text.strip()))

    parent_chunks: List[ParentChunkItem] = []

    # 1. Generate Document-Level Summary Chunk
    doc_headings = [re.sub(r"^#+\s*", "", l).strip() for l in lines if l.startswith("#")][:25]
    if doc_headings:
        overview_path = f"{doc_title} > Overview" if doc_title else "Overview"
        summary_body = f"Document Overview for '{doc_title}':\nKey Topics and Sections Covered:\n" + "\n".join(f"- {h}" for h in doc_headings)
        summary_tags = extract_entity_tags(summary_body, db=db)
        doc_summary_parent = ParentChunkItem(
            text=summary_body,
            chunk_type="SUMMARY",
            section_path=overview_path,
            entity_tags=summary_tags,
            children=[
                ChildChunkItem(
                    text=f"[{doc_title} Overview]\n{summary_body}",
                    chunk_type="SUMMARY",
                    section_path=overview_path,
                    entity_tags=summary_tags,
                )
            ]
        )
        parent_chunks.append(doc_summary_parent)

    # 2. Process Each Major Section
    for crumbs, content in sections:
        section_path = " > ".join(crumbs) if crumbs else doc_title
        tables = extract_tables_from_markdown(content, default_caption=crumbs[-1] if crumbs else "")

        # Form parent chunk text (full cohesive section up to ~2500 chars)
        parent_text = f"[{section_path}]\n{content}".strip()
        parent_tags = extract_entity_tags(parent_text, db=db)
        
        children: List[ChildChunkItem] = []

        # Process Table expansions into Child Chunks
        if tables:
            for table in tables:
                if table.semantic_rows:
                    # Group semantic statements into 250-400 char child chunks
                    table_prefix = f"[{section_path} > Table: {table.caption}]\n" if table.caption else f"[{section_path}]\n"
                    t_acc: List[str] = []
                    t_len = len(table_prefix)

                    for stmt in table.semantic_rows:
                        if t_len + len(stmt) > _CHILD_CHUNK_TARGET and t_acc:
                            t_chunk_text = table_prefix + " ".join(t_acc)
                            children.append(ChildChunkItem(
                                text=t_chunk_text,
                                chunk_type="TABLE",
                                section_path=section_path,
                                entity_tags=extract_entity_tags(t_chunk_text, db=db),
                            ))
                            t_acc = [stmt]
                            t_len = len(table_prefix) + len(stmt)
                        else:
                            t_acc.append(stmt)
                            t_len += len(stmt) + 1

                    if t_acc:
                        t_chunk_text = table_prefix + " ".join(t_acc)
                        children.append(ChildChunkItem(
                            text=t_chunk_text,
                            chunk_type="TABLE",
                            section_path=section_path,
                            entity_tags=extract_entity_tags(t_chunk_text, db=db),
                        ))

        # Split regular narrative parts into Child Chunks
        narrative_children = _split_narrative_into_children(content, section_path, db=db)
        children.extend(narrative_children)

        # Build parent chunk item
        parent_chunks.append(ParentChunkItem(
            text=parent_text,
            chunk_type="PARENT",
            section_path=section_path,
            entity_tags=parent_tags,
            children=children if children else [
                ChildChunkItem(
                    text=parent_text[:_CHILD_CHUNK_TARGET],
                    chunk_type="DETAIL",
                    section_path=section_path,
                    entity_tags=parent_tags,
                )
            ]
        ))

    return parent_chunks


def _load_document_text(file_path: str) -> str:
    if not os.path.isabs(file_path):
        from app.core.private_storage import safe_existing_path
        try:
            file_path = str(safe_existing_path("documents", file_path))
        except Exception:
            pass
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")
    return extract_text_from_file(file_path)


def _failed(document_id: int, message: str, skipped: int = 0) -> IngestionResult:
    return IngestionResult(document_id, 0, 0, skipped, message, status="FAILED")


def ingest_document(document_id: int, db: Session, force_reindex: bool = False) -> IngestionResult:
    """
    Ingest a document using hierarchical parent-child storage, table normalization,
    and entity linking.
    """
    from app.models.models import DocumentChunk, EmbeddingVector

    doc = get_active_document(document_id, db)
    if not doc:
        return _failed(document_id, f"Document ID {document_id} not found or is inactive.")

    try:
        text = _load_document_text(doc.file_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Ingestion failed for document_id=%d: %s", document_id, exc)
        return _failed(document_id, str(exc))

    hierarchical_parents = _build_hierarchical_chunks(text, doc_title=doc.title or "", db=db)
    
    # Collect all child chunks across all parents for fast batch embedding
    all_children: List[Tuple[int, ChildChunkItem]] = []
    for p_idx, parent_item in enumerate(hierarchical_parents):
        for child_item in parent_item.children:
            all_children.append((p_idx, child_item))

    child_texts = [c.text for _, c in all_children]
    logger.info("Batch embedding %d child chunks for document '%s'...", len(child_texts), doc.title)
    
    raw_embeddings = embed_document_chunks_batch(child_texts, batch_size=50)

    staged_parent_children_map: Dict[int, List[Tuple[ChildChunkItem, List[float]]]] = {
        p_idx: [] for p_idx in range(len(hierarchical_parents))
    }
    total_child_count = 0
    skipped = 0

    for (p_idx, child_item), vector in zip(all_children, raw_embeddings):
        try:
            if not vector:
                raise ValueError("Empty embedding vector returned")
            array = np.asarray(vector, dtype=np.float32).reshape(-1)
            if array.size == 0 or not np.isfinite(array).all() or float(np.linalg.norm(array)) <= 1e-12:
                raise ValueError("embedding is empty, non-finite, or zero-norm")
            vector_to_mysql_string(array.tolist())
            staged_parent_children_map[p_idx].append((child_item, array.tolist()))
            total_child_count += 1
        except Exception as exc:
            skipped += 1
            logger.error("Embedding validation failed for child chunk of document_id=%d: %s", document_id, exc)

    staged_parents: List[Tuple[ParentChunkItem, List[Tuple[ChildChunkItem, List[float]]]]] = []
    for p_idx, parent_item in enumerate(hierarchical_parents):
        c_list = staged_parent_children_map.get(p_idx, [])
        if c_list:
            staged_parents.append((parent_item, c_list))

    if not staged_parents:
        return _failed(document_id, f"No usable embeddings were produced for document '{doc.title}'.", skipped)

    new_memory_vectors: List[Tuple[int, str, List[float], str, Dict[str, Any]]] = []
    chunk_index_counter = 0

    try:
        # Mark previous chunks as outdated
        for old_chunk in db.query(DocumentChunk).filter_by(document_id=document_id).all():
            old_chunk.is_outdated = True

        doc_roles = getattr(doc, "allowed_roles", None)
        if not doc_roles:
            raw_lvl = getattr(doc, "access_level", "VISITOR") or "VISITOR"
            doc_roles = ["VISITOR"] if str(raw_lvl).upper() == "PUBLIC" else [str(raw_lvl).upper()]
        elif isinstance(doc_roles, str):
            try:
                doc_roles = json.loads(doc_roles)
            except Exception:
                doc_roles = [doc_roles]

        for parent_item, child_tuples in staged_parents:
            # 1. Insert Parent Chunk
            chunk_index_counter += 1
            parent_record = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk_index_counter,
                chunk_text=parent_item.text,
                char_count=len(parent_item.text),
                access_level=getattr(doc, "access_level", "VISITOR") or "VISITOR",
                allowed_roles=doc_roles,
                chunk_type=parent_item.chunk_type,
                parent_chunk_id=None,
                section_path=parent_item.section_path,
                entity_tags=parent_item.entity_tags if parent_item.entity_tags else None,
                is_outdated=False,
            )
            db.add(parent_record)
            db.flush()  # populate parent_record.chunk_id

            # 2. Insert Child Chunks
            for child_item, vector in child_tuples:
                chunk_index_counter += 1
                child_record = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_index_counter,
                    chunk_text=child_item.text,
                    char_count=len(child_item.text),
                    access_level=getattr(doc, "access_level", "VISITOR") or "VISITOR",
                    allowed_roles=doc_roles,
                    chunk_type=child_item.chunk_type,
                    parent_chunk_id=parent_record.chunk_id,
                    section_path=child_item.section_path,
                    entity_tags=child_item.entity_tags if child_item.entity_tags else None,
                    is_outdated=False,
                )
                db.add(child_record)
                db.flush()

                # 3. Insert Child Embedding Vector
                db.add(EmbeddingVector(
                    chunk_id=child_record.chunk_id,
                    embedding=vector_to_mysql_string(vector),
                    model_version=rag_settings.EMBEDDING_MODEL,
                ))

                metadata_payload = {
                    "document_id": document_id,
                    "category": getattr(doc, "category", "GENERAL") or "GENERAL",
                    "faculty_code": getattr(doc, "faculty_code", None),
                    "target_audience": getattr(doc, "target_audience", "ALL") or "ALL",
                    "chunk_type": child_item.chunk_type,
                    "parent_chunk_id": parent_record.chunk_id,
                    "section_path": child_item.section_path,
                    "entity_tags": child_item.entity_tags,
                    "allowed_roles": doc_roles,
                }
                new_memory_vectors.append((
                    child_record.chunk_id,
                    getattr(doc, "access_level", "VISITOR") or "VISITOR",
                    vector,
                    child_item.text,
                    metadata_payload,
                ))

        doc.chunking_status = "COMPLETED"
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            doc.chunking_status = "FAILED"
            db.commit()
        except Exception:
            pass
        logger.error("Ingestion DB commit failed for document_id=%d: %s", document_id, exc)
        return _failed(document_id, f"Database commit failed: {exc}", skipped + total_child_count)

    # 4. Update in-memory vector & lexical store
    from RagChatbot.retrieval.vector_store import vector_store
    if vector_store.is_loaded:
        vector_store.replace_document_hierarchical(document_id, new_memory_vectors)

    from RagChatbot.embeddings.google_embedding_service import clear_embedding_cache
    from RagChatbot.services.chat_service import clear_rag_response_cache
    clear_embedding_cache()
    clear_rag_response_cache()

    return IngestionResult(
        document_id=document_id,
        chunks_created=chunk_index_counter,
        embeddings_created=total_child_count,
        skipped=skipped,
        message=(f"Document '{doc.title}' ingested successfully into hierarchical store: "
                 f"{len(staged_parents)} parent chunks, {total_child_count} child chunks. "
                 f"{skipped} skipped."),
        status="COMPLETED",
    )
