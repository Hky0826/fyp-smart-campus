"""
In-RAM Vector Store & MySQL Document Loader for Standalone RAG Assistant.
Loads all document embeddings from MySQL smart_campus_db into RAM for ultra-fast (<20ms) semantic search.
Zero modifications to cloud backend.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from sqlalchemy import create_engine, text

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Load backend configuration
_ENV_PATH = PROJECT_ROOT / "cloud" / "dashboard" / "backend" / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

CACHE_FILE = SCRIPT_DIR / "vector_cache.npz"


def _parse_roles(raw_roles: Any, fallback_level: Any = None) -> Set[str]:
    """Standardize roles to a set of uppercase strings."""
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
        lvl = str(fallback_level).upper()
        if lvl in ("PUBLIC", "VISITOR"):
            return {"VISITOR"}
        return {lvl}

    return {"VISITOR"}


class MySQLRAMVectorStore:
    """
    In-Memory Vector Store matching the cloud backend's InMemoryVectorStore.
    Maintains active embeddings and chunks in RAM for sub-20ms cosine similarity.
    """

    def __init__(self):
        self.chunk_ids = np.array([], dtype=np.int64)
        self.document_ids = np.array([], dtype=np.int64)
        self.doc_titles: List[str] = []
        self.chunk_texts: List[str] = []
        self.section_paths: List[str] = []
        self.access_levels: List[str] = []
        self.allowed_roles: List[Set[str]] = []
        self.embeddings_norm = np.array([], dtype=np.float32).reshape(0, 0)
        self.is_loaded = False
        self.client: Optional[genai.Client] = None

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if api_key:
            self.client = genai.Client(api_key=api_key)

    def _get_db_engine(self):
        user = os.getenv("DB_USER", "root")
        pwd = os.getenv("DB_PASSWORD", "3996")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        db = os.getenv("DB_NAME", "smart_campus_db")
        url = f"mysql+mysqlconnector://{user}:{pwd}@{host}:{port}/{db}"
        return create_engine(url, connect_args={"connect_timeout": 5})

    def load(self, force_reload: bool = False) -> bool:
        """Load chunks and normalized embeddings into RAM (from local cache or MySQL)."""
        if self.is_loaded and not force_reload:
            return True

        # 1. Try loading from fast local cache (.npz)
        if not force_reload and CACHE_FILE.exists():
            try:
                t0 = time.time()
                data = np.load(CACHE_FILE, allow_pickle=True)
                self.chunk_ids = data["chunk_ids"]
                self.document_ids = data["document_ids"]
                self.doc_titles = data["doc_titles"].tolist()
                self.chunk_texts = data["chunk_texts"].tolist()
                self.section_paths = data["section_paths"].tolist()
                self.access_levels = data["access_levels"].tolist()
                self.allowed_roles = [set(r) for r in data["allowed_roles"].tolist()]
                self.embeddings_norm = data["embeddings_norm"]
                self.is_loaded = True
                print(f"[MySQL Vector Store] Loaded {len(self.chunk_ids)} chunks from local RAM cache in {(time.time()-t0)*1000:.1f}ms.")
                return True
            except Exception as e:
                logger.warning("Could not load from vector cache: %s. Loading from MySQL...", e)

        # 2. Load directly from MySQL database
        return self._load_from_mysql()

    def _load_from_mysql(self) -> bool:
        print("[MySQL Vector Store] Connecting to MySQL smart_campus_db on localhost:3306...")
        t0 = time.time()
        sql = text("""
            SELECT
                dc.chunk_id,
                dc.document_id,
                ud.title AS doc_title,
                dc.access_level,
                COALESCE(dc.allowed_roles, ud.allowed_roles) AS allowed_roles,
                dc.chunk_text,
                COALESCE(dc.section_path, '') AS section_path,
                ev.embedding AS chunk_embedding
            FROM document_chunks dc
            INNER JOIN embedding_vectors ev ON dc.chunk_id = ev.chunk_id
            INNER JOIN uploaded_documents ud ON dc.document_id = ud.document_id
            WHERE dc.is_outdated = 0 AND ud.is_active = 1
        """)

        try:
            engine = self._get_db_engine()
            with engine.connect() as conn:
                rows = conn.execute(sql).fetchall()
        except Exception as e:
            print(f"[MySQL Vector Store] Could not connect to MySQL: {e}")
            return False

        if not rows:
            print("[MySQL Vector Store] No active chunks found in MySQL.")
            return False

        t_fetch = time.time() - t0
        print(f"[MySQL Vector Store] Fetched {len(rows)} records in {t_fetch:.2f}s. Parsing vectors into RAM...")

        t1 = time.time()
        c_ids, d_ids, titles, texts, paths, levels, roles_list, raw_embeddings = [], [], [], [], [], [], [], []

        for r in rows:
            raw_emb = r.chunk_embedding
            if isinstance(raw_emb, str):
                emb = json.loads(raw_emb)
            elif isinstance(raw_emb, bytes):
                emb = np.frombuffer(raw_emb, dtype=np.float32).tolist()
            else:
                emb = list(raw_emb)

            c_ids.append(r.chunk_id)
            d_ids.append(r.document_id)
            titles.append(str(r.doc_title or ""))
            texts.append(str(r.chunk_text or ""))
            paths.append(str(r.section_path or ""))
            levels.append(str(r.access_level or "PUBLIC"))
            roles_list.append(list(_parse_roles(r.allowed_roles, r.access_level)))
            raw_embeddings.append(emb)

        self.chunk_ids = np.array(c_ids, dtype=np.int64)
        self.document_ids = np.array(d_ids, dtype=np.int64)
        self.doc_titles = titles
        self.chunk_texts = texts
        self.section_paths = paths
        self.access_levels = levels
        self.allowed_roles = [set(r) for r in roles_list]

        # Normalize matrix for fast unit dot product cosine similarity
        emb_matrix = np.array(raw_embeddings, dtype=np.float32)
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-10
        self.embeddings_norm = emb_matrix / norms
        self.is_loaded = True

        print(f"[MySQL Vector Store] Initialized {self.embeddings_norm.shape} RAM matrix in {time.time()-t1:.2f}s.")

        # Save to local cache for instant future startups
        try:
            np.savez_compressed(
                CACHE_FILE,
                chunk_ids=self.chunk_ids,
                document_ids=self.document_ids,
                doc_titles=np.array(self.doc_titles, dtype=object),
                chunk_texts=np.array(self.chunk_texts, dtype=object),
                section_paths=np.array(self.section_paths, dtype=object),
                access_levels=np.array(self.access_levels, dtype=object),
                allowed_roles=np.array(roles_list, dtype=object),
                embeddings_norm=self.embeddings_norm,
            )
            print(f"[MySQL Vector Store] Cached {len(self.chunk_ids)} chunks to {CACHE_FILE.name} for instant reloads.")
        except Exception as e:
            logger.debug("Could not save vector cache: %s", e)

        return True

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        allowed_roles: Optional[List[str]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Embed query with gemini-embedding-2 and execute in-RAM vector cosine similarity search.
        Returns: (formatted_context, unique_sources)
        """
        if not self.is_loaded:
            if not self.load():
                return "Database vector store unavailable.", []

        if not self.client:
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if not api_key:
                return "Google API Key missing for embedding query.", []
            self.client = genai.Client(api_key=api_key)

        # 1. Embed query with gemini-embedding-2 (3072 dims)
        t_embed = time.time()
        try:
            resp = self.client.models.embed_content(
                model="gemini-embedding-2",
                contents=query,
                config=types.EmbedContentConfig(output_dimensionality=3072),
            )
            q_emb = np.array(resp.embeddings[0].values, dtype=np.float32)
        except Exception as e:
            logger.error("Failed to generate query embedding: %s", e)
            return f"Embedding generation failed: {e}", []

        q_norm_val = np.linalg.norm(q_emb)
        q_norm = q_emb / (q_norm_val if q_norm_val != 0 else 1e-10)

        # 2. RBAC Filter Mask (defaults to PUBLIC / VISITOR)
        roles = {r.upper() for r in (allowed_roles or ["VISITOR", "PUBLIC"])}
        mask = np.array([
            bool(roles & c_roles or "VISITOR" in c_roles or "PUBLIC" in c_roles)
            for c_roles in self.allowed_roles
        ], dtype=bool)

        valid_indices = np.where(mask)[0]
        if len(valid_indices) == 0:
            return "No authorized campus documents found for this role.", []

        # 3. In-RAM Vector Cosine Similarity (< 20ms)
        t_sim = time.time()
        valid_embeddings = self.embeddings_norm[valid_indices]
        scores = np.dot(valid_embeddings, q_norm)

        k = min(top_k * 2, len(scores))
        top_local_idx = np.argsort(scores)[-k:][::-1]
        top_global_indices = valid_indices[top_local_idx]

        # 4. Deduplicate and format context
        parts = []
        sources = []
        seen_texts = set()

        for idx in top_global_indices:
            txt = self.chunk_texts[idx]
            snip = txt[:80]
            if snip in seen_texts:
                continue
            seen_texts.add(snip)

            doc_title = self.doc_titles[idx]
            path = self.section_paths[idx]
            if doc_title not in sources:
                sources.append(doc_title)

            header = f"[{len(sources)}] Source: {doc_title}"
            if path:
                header += f" > {path}"
            parts.append(f"{header}\n{txt}")

            if len(parts) >= top_k:
                break

        context = "\n\n".join(parts) if parts else "No relevant campus records found."
        return context, sources


# Global singleton instance
in_memory_store = MySQLRAMVectorStore()


if __name__ == "__main__":
    print("Testing MySQL In-RAM Vector Store:")
    in_memory_store.load()
    q = "What are the courses offered in QIU?"
    print(f"\nQuery: {q}")
    ctx, srcs = in_memory_store.retrieve(q, top_k=3)
    print(f"Sources: {srcs}")
    print("\nRetrieved Context Preview:\n", ctx[:400])
