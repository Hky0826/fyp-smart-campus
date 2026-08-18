"""
In-Memory Vector & Lexical Hybrid Store for RAG Document Chunks.

Maintains a fast, local index of all active document embeddings and text chunks to
compute exact cosine similarity, tokenized BM25 lexical relevance, and Reciprocal
Rank Fusion (RRF) with strict pre-retrieval RBAC filtering.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_WORD_PATTERN = re.compile(r"[A-Za-z0-9_#\-]+")


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric keywords and acronyms."""
    return [w.lower() for w in _WORD_PATTERN.findall(text or "") if len(w) > 1]


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
        self.document_ids = np.array([], dtype=np.int64)
        self.chunk_texts: list[str] = []
        self.tokenized_chunks: list[list[str]] = []
        self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)
        self._initialized = True
        self.is_loaded = False

    def load_from_db(self, db: Session):
        """Loads all active chunk embeddings and texts from the database."""
        logger.info("Loading in-memory vector and lexical store from DB...")
        sql = text("""
            SELECT
                dc.chunk_id,
                dc.document_id,
                dc.access_level,
                dc.chunk_text,
                VECTOR_TO_STRING(ev.embedding) AS chunk_embedding
            FROM document_chunks dc
            INNER JOIN embedding_vectors ev
                ON dc.chunk_id = ev.chunk_id
            INNER JOIN uploaded_documents ud
                ON dc.document_id = ud.document_id
            WHERE dc.is_outdated = 0 AND ud.is_active = 1
              AND ud.access_level = dc.access_level
        """)
        try:
            rows = db.execute(sql).fetchall()
        except Exception as exc:
            logger.error("Failed to fetch embeddings from DB: %s", exc)
            return

        chunk_ids = []
        access_levels = []
        document_ids = []
        chunk_texts = []
        tokenized_chunks = []
        embeddings = []

        for row in rows:
            try:
                emb = json.loads(row.chunk_embedding)
                c_text = str(getattr(row, "chunk_text", "") or "")
                chunk_ids.append(row.chunk_id)
                document_ids.append(row.document_id)
                access_levels.append(row.access_level)
                chunk_texts.append(c_text)
                tokenized_chunks.append(_tokenize(c_text))
                embeddings.append(emb)
            except Exception as e:
                logger.error("Error parsing embedding for chunk_id %s: %s", getattr(row, "chunk_id", "?"), e)

        if embeddings:
            self.chunk_ids = np.array(chunk_ids, dtype=np.int64)
            self.access_levels = np.array(access_levels, dtype=object)
            self.document_ids = np.array(document_ids, dtype=np.int64)
            self.chunk_texts = chunk_texts
            self.tokenized_chunks = tokenized_chunks
            self.embeddings = np.array(embeddings, dtype=np.float32)
        else:
            self.chunk_ids = np.array([], dtype=np.int64)
            self.access_levels = np.array([], dtype=object)
            self.document_ids = np.array([], dtype=np.int64)
            self.chunk_texts = []
            self.tokenized_chunks = []
            self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)

        self.is_loaded = True
        logger.info("Hybrid store loaded with %d chunks.", len(self.chunk_ids))

    def add_chunk(
        self,
        chunk_id: int,
        access_level: str,
        embedding: list[float],
        document_id: int | None = None,
        chunk_text: str = "",
    ):
        """Dynamically add a chunk to the in-memory store."""
        emb_arr = np.array([embedding], dtype=np.float32)
        toks = _tokenize(chunk_text)
        
        if len(self.chunk_ids) == 0:
            self.chunk_ids = np.array([chunk_id], dtype=np.int64)
            self.access_levels = np.array([access_level], dtype=object)
            self.document_ids = np.array([document_id if document_id is not None else -1], dtype=np.int64)
            self.chunk_texts = [chunk_text]
            self.tokenized_chunks = [toks]
            self.embeddings = emb_arr
        else:
            self.chunk_ids = np.append(self.chunk_ids, chunk_id)
            self.access_levels = np.append(self.access_levels, access_level)
            self.document_ids = np.append(self.document_ids, document_id if document_id is not None else -1)
            self.chunk_texts.append(chunk_text)
            self.tokenized_chunks.append(toks)
            self.embeddings = np.vstack([self.embeddings, emb_arr])
        logger.debug("Added chunk %d to hybrid vector store.", chunk_id)

    def remove_document(self, document_id: int) -> None:
        """Remove every indexed vector and text belonging to a document."""
        if len(self.chunk_ids) == 0:
            return
        keep_mask = self.document_ids != document_id
        keep_indices = np.where(keep_mask)[0].tolist()

        self.chunk_ids = self.chunk_ids[keep_mask]
        self.access_levels = self.access_levels[keep_mask]
        self.document_ids = self.document_ids[keep_mask]
        self.chunk_texts = [self.chunk_texts[i] for i in keep_indices]
        self.tokenized_chunks = [self.tokenized_chunks[i] for i in keep_indices]
        self.embeddings = self.embeddings[keep_mask] if self.embeddings.size else self.embeddings

    def replace_document(self, document_id: int, chunks: list[tuple]) -> None:
        """
        Atomically replace one document's vectors and text chunks in the in-memory index.
        Accepts tuples of (chunk_id, access_level, embedding) or (chunk_id, access_level, embedding, chunk_text).
        """
        self.remove_document(document_id)
        for item in chunks:
            if len(item) == 4:
                chunk_id, access_level, embedding, c_text = item
            else:
                chunk_id, access_level, embedding = item[:3]
                c_text = ""
            self.add_chunk(chunk_id, access_level, embedding, document_id=document_id, chunk_text=c_text)

    def search(self, query_embedding: list[float], allowed_access_levels: list[str], top_k: int) -> list[int]:
        """Search top_k chunk_ids by cosine similarity with RBAC filtering."""
        results = self.search_with_scores(query_embedding, allowed_access_levels, top_k)
        return [cid for cid, _ in results]

    def search_with_scores(
        self, query_embedding: list[float], allowed_access_levels: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """Search top_k (chunk_id, cosine_similarity_score) with RBAC filtering."""
        if len(self.chunk_ids) == 0:
            return []

        # Boolean mask for access control
        mask = np.isin(self.access_levels, allowed_access_levels)
        valid_indices = np.where(mask)[0]

        if len(valid_indices) == 0:
            return []

        valid_embeddings = self.embeddings[valid_indices]
        valid_chunk_ids = self.chunk_ids[valid_indices]

        # Calculate cosine similarity
        q_emb = np.array(query_embedding, dtype=np.float32)
        norms_valid = np.linalg.norm(valid_embeddings, axis=1)
        norm_q = np.linalg.norm(q_emb)

        norms_valid[norms_valid == 0] = 1e-10
        norm_q = norm_q if norm_q != 0 else 1e-10

        similarities = np.dot(valid_embeddings, q_emb) / (norms_valid * norm_q)

        k = min(top_k, len(similarities))
        top_indices = np.argsort(similarities)[-k:][::-1]

        return [(int(valid_chunk_ids[i]), float(similarities[i])) for i in top_indices]

    def search_lexical(
        self, query_text: str, allowed_access_levels: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """
        In-memory BM25-style lexical keyword matching with RBAC filtering.
        Excels at acronyms, course codes, building labels, and exact names.
        """
        if len(self.chunk_ids) == 0 or not query_text.strip():
            return []

        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []

        mask = np.isin(self.access_levels, allowed_access_levels)
        valid_indices = np.where(mask)[0]
        if len(valid_indices) == 0:
            return []

        # BM25 parameters
        k1 = 1.5
        b = 0.75

        total_docs = len(valid_indices)
        avg_doc_len = (
            sum(len(self.tokenized_chunks[i]) for i in valid_indices) / total_docs
            if total_docs > 0
            else 1.0
        ) or 1.0

        # Calculate IDF for each query term among authorized docs
        doc_freqs: dict[str, int] = {}
        for q_token in set(query_tokens):
            df = sum(1 for i in valid_indices if q_token in set(self.tokenized_chunks[i]))
            doc_freqs[q_token] = df

        scores: list[tuple[int, float]] = []
        for i in valid_indices:
            chunk_id = int(self.chunk_ids[i])
            toks = self.tokenized_chunks[i]
            doc_len = len(toks)
            
            # Exact phrase bonus
            phrase_bonus = 0.0
            if len(query_tokens) > 1 and query_text.lower() in self.chunk_texts[i].lower():
                phrase_bonus = 3.0

            chunk_score = phrase_bonus
            tf_map: dict[str, int] = {}
            for t in toks:
                tf_map[t] = tf_map.get(t, 0) + 1

            for q_token in query_tokens:
                tf = tf_map.get(q_token, 0)
                if tf == 0:
                    continue
                df = doc_freqs.get(q_token, 0)
                # Standard BM25 IDF
                idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
                term_score = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / avg_doc_len)))
                chunk_score += term_score

            if chunk_score > 0.0:
                scores.append((chunk_id, float(chunk_score)))

        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

    def search_hybrid(
        self,
        query_text: str,
        query_embedding: list[float],
        allowed_access_levels: list[str],
        top_k: int,
        dense_weight: float = 0.7,
        lexical_weight: float = 0.3,
    ) -> list[int]:
        """
        Execute parallel dense semantic search and tokenized BM25 lexical search,
        combining results via Reciprocal Rank Fusion (RRF).
        """
        results = self.search_hybrid_with_scores(
            query_text=query_text,
            query_embedding=query_embedding,
            allowed_access_levels=allowed_access_levels,
            top_k=top_k,
            dense_weight=dense_weight,
            lexical_weight=lexical_weight,
        )
        return [cid for cid, _ in results]

    def search_hybrid_with_scores(
        self,
        query_text: str,
        query_embedding: list[float],
        allowed_access_levels: list[str],
        top_k: int,
        dense_weight: float = 0.7,
        lexical_weight: float = 0.3,
    ) -> list[tuple[int, float]]:
        """
        Execute parallel dense semantic search and tokenized BM25 lexical search,
        combining results via Reciprocal Rank Fusion (RRF).
        Returns list of (chunk_id, similarity_score).
        """
        candidate_pool = max(top_k * 2, 20)
        dense_results = self.search_with_scores(query_embedding, allowed_access_levels, candidate_pool)
        lexical_results = self.search_lexical(query_text, allowed_access_levels, candidate_pool)

        if not dense_results and not lexical_results:
            return []

        dense_score_map = {cid: score for cid, score in dense_results}
        rrf_scores: dict[int, float] = {}
        rrf_k = 60.0

        # Dense ranking contributions
        for rank, (cid, _) in enumerate(dense_results):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + dense_weight * (1.0 / (rrf_k + rank + 1))

        # Lexical ranking contributions
        for rank, (cid, _) in enumerate(lexical_results):
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + lexical_weight * (1.0 / (rrf_k + rank + 1))

        # Sort chunk IDs by descending RRF score
        sorted_candidates = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
        top_candidates = sorted_candidates[:top_k]
        return [(cid, float(dense_score_map.get(cid, 0.60))) for cid, _ in top_candidates]


# Singleton instance exported for use across the application
vector_store = InMemoryVectorStore()
