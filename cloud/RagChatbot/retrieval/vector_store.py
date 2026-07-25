"""
In-Memory Numpy Vector Store for RAG Document Chunks.

Maintains a fast, local index of all active document embeddings to
compute exact cosine similarity without relying on MySQL's LIMIT clause,
which cannot sort by vector distance.
"""

import json
import logging
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

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
        self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)
        self._initialized = True
        self.is_loaded = False

    def load_from_db(self, db: Session):
        """Loads all active chunk embeddings from the database."""
        logger.info("Loading in-memory vector store from DB...")
        sql = text("""
            SELECT
                dc.chunk_id,
                dc.access_level,
                VECTOR_TO_STRING(ev.embedding) AS chunk_embedding
            FROM document_chunks dc
            INNER JOIN embedding_vectors ev
                ON dc.chunk_id = ev.chunk_id
            INNER JOIN uploaded_documents ud
                ON dc.document_id = ud.document_id
            WHERE dc.is_outdated = 0 AND ud.is_active = 1
        """)
        try:
            rows = db.execute(sql).fetchall()
        except Exception as exc:
            logger.error("Failed to fetch embeddings from DB: %s", exc)
            return

        chunk_ids = []
        access_levels = []
        embeddings = []

        for row in rows:
            try:
                emb = json.loads(row.chunk_embedding)
                chunk_ids.append(row.chunk_id)
                access_levels.append(row.access_level)
                embeddings.append(emb)
            except Exception as e:
                logger.error("Error parsing embedding for chunk_id %s: %s", row.chunk_id, e)

        if embeddings:
            self.chunk_ids = np.array(chunk_ids, dtype=np.int64)
            self.access_levels = np.array(access_levels, dtype=object)
            self.embeddings = np.array(embeddings, dtype=np.float32)
        else:
            self.chunk_ids = np.array([], dtype=np.int64)
            self.access_levels = np.array([], dtype=object)
            self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)

        self.is_loaded = True
        logger.info("Vector store loaded with %d chunks.", len(self.chunk_ids))

    def add_chunk(self, chunk_id: int, access_level: str, embedding: list[float]):
        """Dynamically add a chunk to the in-memory store."""
        emb_arr = np.array([embedding], dtype=np.float32)
        
        if len(self.chunk_ids) == 0:
            self.chunk_ids = np.array([chunk_id], dtype=np.int64)
            self.access_levels = np.array([access_level], dtype=object)
            self.embeddings = emb_arr
        else:
            self.chunk_ids = np.append(self.chunk_ids, chunk_id)
            self.access_levels = np.append(self.access_levels, access_level)
            self.embeddings = np.vstack([self.embeddings, emb_arr])
        logger.debug("Added chunk %d to vector store.", chunk_id)

    def search(self, query_embedding: list[float], allowed_access_levels: list[str], top_k: int) -> list[int]:
        """Search the top_k chunk_ids by cosine similarity with RBAC filtering."""
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
        
        # Avoid division by zero
        norms_valid[norms_valid == 0] = 1e-10
        norm_q = norm_q if norm_q != 0 else 1e-10

        similarities = np.dot(valid_embeddings, q_emb) / (norms_valid * norm_q)

        # Get top k indices
        k = min(top_k, len(similarities))
        top_indices = np.argsort(similarities)[-k:][::-1]
        
        return valid_chunk_ids[top_indices].tolist()

# Singleton instance exported for use across the application
vector_store = InMemoryVectorStore()
