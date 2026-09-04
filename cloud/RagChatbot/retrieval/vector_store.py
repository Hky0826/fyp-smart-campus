"""
In-Memory Vector & Lexical Hybrid Store for RAG Document Chunks.

Maintains a fast, local index of all active document embeddings, text chunks, and metadata
to compute exact cosine similarity, tokenized BM25 lexical relevance, and Reciprocal
Rank Fusion (RRF) with multi-role RBAC authorization and faceted metadata filtering
(Category, Faculty, Target Audience, Chunk Type).
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Set
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_WORD_PATTERN = re.compile(r"[A-Za-z0-9_#\-]+")
ADMIN_ROLES = {"ADMIN", "SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"}
_CACHE_FILE = Path(__file__).resolve().parent / "vector_cache.npz"


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric keywords and acronyms."""
    return [w.lower() for w in _WORD_PATTERN.findall(text or "") if len(w) > 1]


def _parse_roles(raw_roles: Any, fallback_level: Any = None) -> Set[str]:
    """Parse JSON or string roles into a standardized uppercase set."""
    if isinstance(raw_roles, str):
        try:
            parsed = json.loads(raw_roles)
            if isinstance(parsed, list):
                return {str(r).upper() for r in parsed}
        except Exception:
            return {raw_roles.upper()}
    elif isinstance(raw_roles, (list, set, tuple)):
        return {str(r).upper() for r in raw_roles}

    if fallback_level:
        lvl_str = str(fallback_level).upper()
        if lvl_str == "PUBLIC":
            return {"VISITOR"}
        return {lvl_str}

    return {"VISITOR"}


class InMemoryVectorStore:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.chunk_ids = np.array([], dtype=np.int64)
        self.access_levels = np.array([], dtype=object)
        self.allowed_roles: list[Set[str]] = []
        self.document_ids = np.array([], dtype=np.int64)
        self.categories = np.array([], dtype=object)
        self.faculty_codes = np.array([], dtype=object)
        self.target_audiences = np.array([], dtype=object)
        self.chunk_types = np.array([], dtype=object)
        self.parent_chunk_ids = np.array([], dtype=np.int64)
        self.section_paths: list[str] = []
        self.entity_tags: list[Any] = []
        self.chunk_texts: list[str] = []
        self.tokenized_chunks: list[list[str]] = []
        self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)
        self._initialized = True
        self.is_loaded = False

    def load_from_db(self, db: Session, force_reload: bool = False):
        """Loads all active chunk embeddings, texts, and metadata facets from disk cache or DB."""
        if not force_reload and _CACHE_FILE.exists():
            try:
                t0 = time.time()
                data = np.load(_CACHE_FILE, allow_pickle=True)
                if len(data["chunk_ids"]) > 0:
                    self.chunk_ids = data["chunk_ids"]
                    self.access_levels = data["access_levels"]
                    self.allowed_roles = data["allowed_roles"].tolist()
                    self.document_ids = data["document_ids"]
                    self.categories = data["categories"]
                    self.faculty_codes = data["faculty_codes"]
                    self.target_audiences = data["target_audiences"]
                    self.chunk_types = data["chunk_types"]
                    self.parent_chunk_ids = data["parent_chunk_ids"]
                    self.section_paths = data["section_paths"].tolist()
                    self.entity_tags = data["entity_tags"].tolist()
                    self.chunk_texts = data["chunk_texts"].tolist()
                    self.tokenized_chunks = data["tokenized_chunks"].tolist()
                    self.embeddings = data["embeddings"]
                    self.is_loaded = True
                    logger.info("Loaded in-memory vector store from disk cache in %.1f ms (%d chunks).", (time.time() - t0) * 1000, len(self.chunk_ids))
                    return
            except Exception as e:
                logger.warning("Could not load vector store from disk cache (%s); querying DB...", e)

        logger.info("Loading in-memory vector and lexical store from DB with multi-role RBAC...")
        sql_direct = text("""
            SELECT
                dc.chunk_id,
                dc.document_id,
                COALESCE(dc.allowed_roles, ud.allowed_roles) AS allowed_roles,
                dc.access_level,
                dc.chunk_text,
                COALESCE(dc.chunk_type, 'DETAIL') AS chunk_type,
                COALESCE(dc.parent_chunk_id, -1) AS parent_chunk_id,
                COALESCE(dc.section_path, '') AS section_path,
                dc.entity_tags,
                COALESCE(ud.category, 'GENERAL') AS category,
                COALESCE(ud.faculty_code, '') AS faculty_code,
                COALESCE(ud.target_audience, 'ALL') AS target_audience,
                ev.embedding AS chunk_embedding
            FROM document_chunks dc
            INNER JOIN embedding_vectors ev
                ON dc.chunk_id = ev.chunk_id
            INNER JOIN uploaded_documents ud
                ON dc.document_id = ud.document_id
            WHERE dc.is_outdated = 0 AND ud.is_active = 1
        """)
        sql_func = text("""
            SELECT
                dc.chunk_id,
                dc.document_id,
                COALESCE(dc.allowed_roles, ud.allowed_roles) AS allowed_roles,
                dc.access_level,
                dc.chunk_text,
                COALESCE(dc.chunk_type, 'DETAIL') AS chunk_type,
                COALESCE(dc.parent_chunk_id, -1) AS parent_chunk_id,
                COALESCE(dc.section_path, '') AS section_path,
                dc.entity_tags,
                COALESCE(ud.category, 'GENERAL') AS category,
                COALESCE(ud.faculty_code, '') AS faculty_code,
                COALESCE(ud.target_audience, 'ALL') AS target_audience,
                VECTOR_TO_STRING(ev.embedding) AS chunk_embedding
            FROM document_chunks dc
            INNER JOIN embedding_vectors ev
                ON dc.chunk_id = ev.chunk_id
            INNER JOIN uploaded_documents ud
                ON dc.document_id = ud.document_id
            WHERE dc.is_outdated = 0 AND ud.is_active = 1
        """)
        try:
            try:
                rows = db.execute(sql_direct).fetchall()
            except Exception:
                rows = db.execute(sql_func).fetchall()
        except Exception as exc:
            logger.error("Failed to fetch embeddings from DB: %s", exc)
            return

        chunk_ids = []
        access_levels = []
        allowed_roles_list = []
        document_ids = []
        categories = []
        faculty_codes = []
        target_audiences = []
        chunk_types = []
        parent_chunk_ids = []
        section_paths = []
        entity_tags = []
        chunk_texts = []
        tokenized_chunks = []
        embeddings = []

        for row in rows:
            try:
                raw_emb = row.chunk_embedding
                if isinstance(raw_emb, str):
                    emb = json.loads(raw_emb)
                elif isinstance(raw_emb, (list, tuple)):
                    emb = list(raw_emb)
                elif hasattr(raw_emb, "tolist"):
                    emb = raw_emb.tolist()
                elif isinstance(raw_emb, bytes):
                    emb = np.frombuffer(raw_emb, dtype=np.float32).tolist()
                else:
                    emb = json.loads(str(raw_emb))

                c_text = str(getattr(row, "chunk_text", "") or "")
                raw_tags = getattr(row, "entity_tags", None)
                if isinstance(raw_tags, str):
                    try:
                        parsed_tags = json.loads(raw_tags)
                    except Exception:
                        parsed_tags = []
                elif isinstance(raw_tags, list):
                    parsed_tags = raw_tags
                else:
                    parsed_tags = []

                parsed_roles = _parse_roles(getattr(row, "allowed_roles", None), getattr(row, "access_level", None))

                chunk_ids.append(row.chunk_id)
                document_ids.append(row.document_id)
                access_levels.append(str(getattr(row, "access_level", "VISITOR") or "VISITOR"))
                allowed_roles_list.append(parsed_roles)
                categories.append(str(getattr(row, "category", "GENERAL") or "GENERAL"))
                faculty_codes.append(str(getattr(row, "faculty_code", "") or ""))
                target_audiences.append(str(getattr(row, "target_audience", "ALL") or "ALL"))
                chunk_types.append(str(getattr(row, "chunk_type", "DETAIL") or "DETAIL"))
                parent_chunk_ids.append(int(getattr(row, "parent_chunk_id", -1) or -1))
                section_paths.append(str(getattr(row, "section_path", "") or ""))
                entity_tags.append(parsed_tags)
                chunk_texts.append(c_text)
                tokenized_chunks.append(_tokenize(c_text))
                embeddings.append(emb)
            except Exception as e:
                logger.error("Error parsing embedding for chunk_id %s: %s", getattr(row, "chunk_id", "?"), e)

        if embeddings:
            self.chunk_ids = np.array(chunk_ids, dtype=np.int64)
            self.access_levels = np.array(access_levels, dtype=object)
            self.allowed_roles = allowed_roles_list
            self.document_ids = np.array(document_ids, dtype=np.int64)
            self.categories = np.array(categories, dtype=object)
            self.faculty_codes = np.array(faculty_codes, dtype=object)
            self.target_audiences = np.array(target_audiences, dtype=object)
            self.chunk_types = np.array(chunk_types, dtype=object)
            self.parent_chunk_ids = np.array(parent_chunk_ids, dtype=np.int64)
            self.section_paths = section_paths
            self.entity_tags = entity_tags
            self.chunk_texts = chunk_texts
            self.tokenized_chunks = tokenized_chunks
            self.embeddings = np.array(embeddings, dtype=np.float32)
            logger.info("Successfully loaded %d active document chunk embeddings into memory.", len(embeddings))
            try:
                np.savez_compressed(
                    _CACHE_FILE,
                    chunk_ids=self.chunk_ids,
                    access_levels=self.access_levels,
                    allowed_roles=np.array(self.allowed_roles, dtype=object),
                    document_ids=self.document_ids,
                    categories=self.categories,
                    faculty_codes=self.faculty_codes,
                    target_audiences=self.target_audiences,
                    chunk_types=self.chunk_types,
                    parent_chunk_ids=self.parent_chunk_ids,
                    section_paths=np.array(self.section_paths, dtype=object),
                    entity_tags=np.array(self.entity_tags, dtype=object),
                    chunk_texts=np.array(self.chunk_texts, dtype=object),
                    tokenized_chunks=np.array(self.tokenized_chunks, dtype=object),
                    embeddings=self.embeddings,
                )
                logger.info("Cached %d vector chunks to %s for fast reloads.", len(self.chunk_ids), _CACHE_FILE.name)
            except Exception as e:
                logger.debug("Could not write vector disk cache: %s", e)
        else:
            self._reset_empty()

        self.is_loaded = True
        logger.info("Hybrid faceted store loaded with %d chunks.", len(self.chunk_ids))

    def _reset_empty(self):
        self.chunk_ids = np.array([], dtype=np.int64)
        self.access_levels = np.array([], dtype=object)
        self.allowed_roles = []
        self.document_ids = np.array([], dtype=np.int64)
        self.categories = np.array([], dtype=object)
        self.faculty_codes = np.array([], dtype=object)
        self.target_audiences = np.array([], dtype=object)
        self.chunk_types = np.array([], dtype=object)
        self.parent_chunk_ids = np.array([], dtype=np.int64)
        self.section_paths = []
        self.entity_tags = []
        self.chunk_texts = []
        self.tokenized_chunks = []
        self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)

    def add_chunk(
        self,
        chunk_id: int,
        access_level: str,
        embedding: list[float],
        document_id: int | None = None,
        chunk_text: str = "",
        category: str = "GENERAL",
        faculty_code: str = "",
        target_audience: str = "ALL",
        chunk_type: str = "DETAIL",
        parent_chunk_id: int = -1,
        section_path: str = "",
        entity_tags: list | None = None,
        allowed_roles: list | None = None,
    ):
        """Dynamically add a chunk with metadata to the in-memory store."""
        emb_arr = np.array([embedding], dtype=np.float32)
        toks = _tokenize(chunk_text)
        tags = entity_tags or []
        roles = _parse_roles(allowed_roles, access_level)
        
        if len(self.chunk_ids) == 0:
            self.chunk_ids = np.array([chunk_id], dtype=np.int64)
            self.access_levels = np.array([access_level], dtype=object)
            self.allowed_roles = [roles]
            self.document_ids = np.array([document_id if document_id is not None else -1], dtype=np.int64)
            self.categories = np.array([category], dtype=object)
            self.faculty_codes = np.array([faculty_code], dtype=object)
            self.target_audiences = np.array([target_audience], dtype=object)
            self.chunk_types = np.array([chunk_type], dtype=object)
            self.parent_chunk_ids = np.array([parent_chunk_id], dtype=np.int64)
            self.section_paths = [section_path]
            self.entity_tags = [tags]
            self.chunk_texts = [chunk_text]
            self.tokenized_chunks = [toks]
            self.embeddings = emb_arr
        else:
            self.chunk_ids = np.append(self.chunk_ids, chunk_id)
            self.access_levels = np.append(self.access_levels, access_level)
            self.allowed_roles.append(roles)
            self.document_ids = np.append(self.document_ids, document_id if document_id is not None else -1)
            self.categories = np.append(self.categories, category)
            self.faculty_codes = np.append(self.faculty_codes, faculty_code)
            self.target_audiences = np.append(self.target_audiences, target_audience)
            self.chunk_types = np.append(self.chunk_types, chunk_type)
            self.parent_chunk_ids = np.append(self.parent_chunk_ids, parent_chunk_id)
            self.section_paths.append(section_path)
            self.entity_tags.append(tags)
            self.chunk_texts.append(chunk_text)
            self.tokenized_chunks.append(toks)
            self.embeddings = np.vstack([self.embeddings, emb_arr])

    def remove_document(self, document_id: int) -> None:
        """Remove every indexed vector and text belonging to a document."""
        if len(self.chunk_ids) == 0:
            return
        keep_mask = self.document_ids != document_id
        keep_indices = np.where(keep_mask)[0].tolist()

        self.chunk_ids = self.chunk_ids[keep_mask]
        self.access_levels = self.access_levels[keep_mask]
        self.allowed_roles = [self.allowed_roles[i] for i in keep_indices]
        self.document_ids = self.document_ids[keep_mask]
        self.categories = self.categories[keep_mask]
        self.faculty_codes = self.faculty_codes[keep_mask]
        self.target_audiences = self.target_audiences[keep_mask]
        self.chunk_types = self.chunk_types[keep_mask]
        self.parent_chunk_ids = self.parent_chunk_ids[keep_mask]
        self.section_paths = [self.section_paths[i] for i in keep_indices]
        self.entity_tags = [self.entity_tags[i] for i in keep_indices]
        self.chunk_texts = [self.chunk_texts[i] for i in keep_indices]
        self.tokenized_chunks = [self.tokenized_chunks[i] for i in keep_indices]
        self.embeddings = self.embeddings[keep_mask] if self.embeddings.size else self.embeddings

    def replace_document(self, document_id: int, chunks: list[tuple]) -> None:
        """Replace document chunks in memory."""
        self.remove_document(document_id)
        for item in chunks:
            if len(item) == 4:
                chunk_id, access_level, embedding, c_text = item
                meta = {}
            elif len(item) >= 5:
                chunk_id, access_level, embedding, c_text, meta = item[:5]
            else:
                chunk_id, access_level, embedding = item[:3]
                c_text = ""
                meta = {}
            self.add_chunk(
                chunk_id=chunk_id,
                access_level=access_level,
                embedding=embedding,
                document_id=document_id,
                chunk_text=c_text,
                category=meta.get("category", "GENERAL"),
                faculty_code=meta.get("faculty_code", ""),
                target_audience=meta.get("target_audience", "ALL"),
                chunk_type=meta.get("chunk_type", "DETAIL"),
                parent_chunk_id=meta.get("parent_chunk_id", -1),
                section_path=meta.get("section_path", ""),
                entity_tags=meta.get("entity_tags", []),
                allowed_roles=meta.get("allowed_roles", ["VISITOR"]),
            )

    def replace_document_hierarchical(self, document_id: int, chunks: list[tuple]) -> None:
        """Atomically replace document chunks with hierarchical metadata in memory."""
        self.replace_document(document_id, chunks)

    def _build_filter_mask(
        self,
        allowed_roles: list[str],
        category: Optional[str] = None,
        faculty_code: Optional[str] = None,
        target_audience: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
    ) -> np.ndarray:
        """Construct fast boolean mask combining multi-role RBAC and faceted filters."""
        if len(self.chunk_ids) == 0:
            return np.array([], dtype=bool)

        user_roles_set = {str(r).upper() for r in (allowed_roles or [])}
        user_roles_set.add("VISITOR")
        is_admin = bool(user_roles_set & ADMIN_ROLES)

        if is_admin:
            mask = np.ones(len(self.chunk_ids), dtype=bool)
        else:
            # Match if user roles intersect with chunk allowed_roles or chunk is accessible to VISITOR
            mask = np.array([
                bool(user_roles_set & c_roles or "VISITOR" in c_roles or "PUBLIC" in c_roles)
                for c_roles in self.allowed_roles
            ], dtype=bool)

        if category and category.upper() not in ("ALL", "GENERAL"):
            mask = mask & ((self.categories == category.upper()) | (self.categories == "GENERAL") | (self.categories == ""))
        if faculty_code and faculty_code.upper() not in ("ALL", "GENERAL"):
            mask = mask & ((self.faculty_codes == faculty_code.upper()) | (self.faculty_codes == "GENERAL") | (self.faculty_codes == ""))
        if target_audience and target_audience.upper() not in ("ALL", "GENERAL"):
            mask = mask & ((self.target_audiences == target_audience.upper()) | (self.target_audiences == "ALL") | (self.target_audiences == "GENERAL") | (self.target_audiences == ""))
        if chunk_types:
            mask = mask & np.isin(self.chunk_types, chunk_types)

        return mask

    def search_with_scores(
        self,
        query_embedding: list[float],
        allowed_access_levels: list[str],
        top_k: int,
        category: Optional[str] = None,
        faculty_code: Optional[str] = None,
        target_audience: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        prefer_summary: bool = False,
    ) -> list[tuple[int, float]]:
        """Search top_k (chunk_id, cosine_similarity_score) with RBAC and facet pre-filtering."""
        if len(self.chunk_ids) == 0:
            return []

        mask = self._build_filter_mask(
            allowed_access_levels,
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
        )
        valid_indices = np.where(mask)[0]

        # Fallback to general RBAC if facet yielded no results
        if len(valid_indices) == 0 and (category or faculty_code or chunk_types):
            mask = self._build_filter_mask(allowed_access_levels)
            valid_indices = np.where(mask)[0]

        if len(valid_indices) == 0:
            return []

        valid_embeddings = self.embeddings[valid_indices]
        valid_chunk_ids = self.chunk_ids[valid_indices]
        valid_chunk_types = self.chunk_types[valid_indices]

        q_emb = np.array(query_embedding, dtype=np.float32)
        norms_valid = np.linalg.norm(valid_embeddings, axis=1)
        norm_q = np.linalg.norm(q_emb)

        norms_valid[norms_valid == 0] = 1e-10
        norm_q = norm_q if norm_q != 0 else 1e-10

        similarities = np.dot(valid_embeddings, q_emb) / (norms_valid * norm_q)

        # Apply summary preference boost if requested
        if prefer_summary:
            summary_boost = np.where(valid_chunk_types == "SUMMARY", 0.15, 0.0)
            similarities = similarities + summary_boost

        k = min(top_k, len(similarities))
        top_indices = np.argsort(similarities)[-k:][::-1]

        return [(int(valid_chunk_ids[i]), float(similarities[i])) for i in top_indices]

    def search_lexical(
        self,
        query_text: str,
        allowed_access_levels: list[str],
        top_k: int,
        category: Optional[str] = None,
        faculty_code: Optional[str] = None,
        target_audience: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        prefer_summary: bool = False,
    ) -> list[tuple[int, float]]:
        """In-memory BM25-style lexical keyword matching with multi-role filtering."""
        if len(self.chunk_ids) == 0 or not query_text.strip():
            return []

        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []

        # Expand academic query synonyms (e.g. course -> programme)
        expanded_tokens = list(query_tokens)
        synonyms_map = {
            "course": ["programme", "programmes", "degree"],
            "courses": ["programmes", "programme", "degrees"],
            "degree": ["programme", "programmes", "course"],
            "degrees": ["programmes", "courses"],
        }
        for tok in query_tokens:
            if tok in synonyms_map:
                for syn in synonyms_map[tok]:
                    if syn not in expanded_tokens:
                        expanded_tokens.append(syn)
        query_tokens = expanded_tokens

        mask = self._build_filter_mask(
            allowed_access_levels,
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
        )
        valid_indices = np.where(mask)[0]
        if len(valid_indices) == 0:
            mask = self._build_filter_mask(allowed_access_levels)
            valid_indices = np.where(mask)[0]

        if len(valid_indices) == 0:
            return []

        k1 = 1.5
        b = 0.75

        total_docs = len(valid_indices)
        avg_doc_len = (
            sum(len(self.tokenized_chunks[i]) for i in valid_indices) / total_docs
            if total_docs > 0
            else 1.0
        ) or 1.0

        doc_freqs: dict[str, int] = {}
        for q_token in set(query_tokens):
            df = sum(1 for i in valid_indices if q_token in set(self.tokenized_chunks[i]))
            doc_freqs[q_token] = df

        scores: list[tuple[int, float]] = []
        for i in valid_indices:
            chunk_id = int(self.chunk_ids[i])
            toks = self.tokenized_chunks[i]
            doc_len = len(toks)
            
            phrase_bonus = 0.0
            if len(query_tokens) > 1 and query_text.lower() in self.chunk_texts[i].lower():
                phrase_bonus = 3.0

            # Prefer summary bonus
            if prefer_summary and self.chunk_types[i] == "SUMMARY":
                phrase_bonus += 2.0

            chunk_score = phrase_bonus
            tf_map: dict[str, int] = {}
            for t in toks:
                tf_map[t] = tf_map.get(t, 0) + 1

            for q_token in query_tokens:
                tf = tf_map.get(q_token, 0)
                if tf == 0:
                    continue
                df = doc_freqs.get(q_token, 0)
                idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
                term_score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / avg_doc_len)))
                chunk_score += term_score

            if chunk_score > 0.0:
                scores.append((chunk_id, float(chunk_score)))

        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

    def search_hybrid_with_scores(
        self,
        query_text: str,
        query_embedding: list[float],
        allowed_access_levels: list[str],
        top_k: int,
        dense_weight: float = 0.7,
        lexical_weight: float = 0.3,
        category: Optional[str] = None,
        faculty_code: Optional[str] = None,
        target_audience: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        prefer_summary: bool = False,
    ) -> list[tuple[int, float]]:
        """Parallel dense & BM25 search with Reciprocal Rank Fusion (RRF) and multi-role RBAC."""
        candidate_pool = max(top_k * 2, 20)
        dense_results = self.search_with_scores(
            query_embedding,
            allowed_access_levels,
            candidate_pool,
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
            prefer_summary=prefer_summary,
        )
        lexical_results = self.search_lexical(
            query_text,
            allowed_access_levels,
            candidate_pool,
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
            prefer_summary=prefer_summary,
        )

        if not dense_results and not lexical_results:
            return []

        dense_score_map = {cid: score for cid, score in dense_results}
        rrf_scores: dict[int, float] = {}
        rrf_k = 60.0

        for rank, (cid, _) in enumerate(dense_results):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + dense_weight * (1.0 / (rrf_k + rank + 1))

        for rank, (cid, _) in enumerate(lexical_results):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + lexical_weight * (1.0 / (rrf_k + rank + 1))

        sorted_candidates = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
        top_candidates = sorted_candidates[:top_k]
        return [(cid, float(dense_score_map.get(cid, 0.60))) for cid, _ in top_candidates]


# Singleton instance exported for use across the application
vector_store = InMemoryVectorStore()
