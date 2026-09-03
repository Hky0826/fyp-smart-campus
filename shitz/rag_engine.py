"""
Standalone in-memory RAG retriever for the shitz folder.
Loads campus markdown documents directly from the local filesystem with zero backend or database dependencies.
"""

from __future__ import annotations

import os
import re
import math
from pathlib import Path
from typing import List, Dict, Any, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DOCS_DIR = PROJECT_ROOT / "documents"


def _tokenize(text: str) -> List[str]:
    """Tokenize and normalize text into lowercase alphanumeric words."""
    return re.findall(r"\w+", text.lower())


class StandaloneRAG:
    """Fast, in-memory BM25 lexical + semantic knowledge search engine."""

    def __init__(self, docs_dir: Path = DOCS_DIR):
        self.docs_dir = docs_dir
        self.chunks: List[Dict[str, Any]] = []
        self.doc_freqs: Dict[str, int] = {}
        self.avg_doc_len = 0.0
        self._load_documents()

    def _load_documents(self):
        """Parse markdown files in documents/ into chunk paragraphs."""
        if not self.docs_dir.exists():
            print(f"[RAG] Warning: Documents directory not found at {self.docs_dir}")
            return

        total_words = 0
        md_files = list(self.docs_dir.glob("*.md"))

        for file_path in md_files:
            if file_path.name in ["rag_evaluation_report.md", "testing_results_report.md", "extraction_report.md"]:
                continue

            doc_title = file_path.stem.replace("_", " ").title()
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                continue

            # Split into sections based on headings or paragraphs (~500-1500 chars)
            sections = re.split(r"\n(?=#{1,3}\s+)", content)
            for sec in sections:
                clean_sec = sec.strip()
                if len(clean_sec) < 80:
                    continue

                tokens = _tokenize(clean_sec)
                if not tokens:
                    continue

                chunk_entry = {
                    "doc_title": doc_title,
                    "file_name": file_path.name,
                    "content": clean_sec[:2000],  # Bound length
                    "tokens": tokens,
                    "length": len(tokens),
                }
                self.chunks.append(chunk_entry)
                total_words += len(tokens)

                # Track document frequency for BM25
                unique_tokens = set(tokens)
                for t in unique_tokens:
                    self.doc_freqs[t] = self.doc_freqs.get(t, 0) + 1

        if self.chunks:
            self.avg_doc_len = total_words / len(self.chunks)
        print(f"[RAG Engine] Loaded {len(self.chunks)} knowledge chunks from {len(md_files)} markdown files (Standalone mode).")

    def search(self, query: str, top_k: int = 4) -> Dict[str, Any]:
        """Perform BM25 scoring across loaded campus chunks with stopword filtering."""
        raw_tokens = _tokenize(query)
        if not raw_tokens or not self.chunks:
            return {"status": "empty", "results": []}

        stopwords = {
            "what", "is", "are", "a", "an", "the", "in", "on", "at", "for", "to",
            "of", "and", "or", "do", "does", "did", "can", "could", "would",
            "should", "tell", "me", "about", "how", "why", "where", "when", "who", "which",
            "there", "any", "some", "i", "you", "we", "they", "he", "she", "it"
        }
        filtered = [t for t in raw_tokens if t not in stopwords]

        # Synonym expansion for common university vocabulary
        synonyms = {
            "course": ["programme", "degree", "faculty", "study"],
            "courses": ["programmes", "degrees", "faculties", "study"],
            "fee": ["tuition", "scholarship", "finance"],
            "fees": ["tuition", "scholarships", "finance"],
            "requirements": ["admission", "entry", "eligibility", "qualification"],
            "requirement": ["admission", "entry", "eligibility", "qualification"],
            "locate": ["address", "campus", "ipoh", "perak"],
            "location": ["address", "campus", "ipoh", "perak"],
            "where": ["address", "campus", "ipoh", "perak"],
        }
        expanded_tokens = list(filtered)
        for t in filtered:
            if t in synonyms:
                expanded_tokens.extend(synonyms[t])

        q_tokens = expanded_tokens if expanded_tokens else raw_tokens

        scored: List[Tuple[float, Dict[str, Any]]] = []
        k1 = 1.5
        b = 0.75
        N = len(self.chunks)

        for chunk in self.chunks:
            score = 0.0
            chunk_tokens = chunk["tokens"]
            chunk_len = chunk["length"]
            token_counts = {}
            for t in chunk_tokens:
                token_counts[t] = token_counts.get(t, 0) + 1

            for qt in q_tokens:
                if qt in token_counts:
                    freq = token_counts[qt]
                    df = self.doc_freqs.get(qt, 1)
                    idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                    denom = freq + k1 * (1 - b + b * (chunk_len / self.avg_doc_len))
                    score += idf * (freq * (k1 + 1)) / denom

            # Deprioritize short syllabus stubs (e.g. course code list stubs)
            clean_text = chunk["content"].lower()
            if "compulsory courses/modules offered" in clean_text and chunk_len < 50:
                score *= 0.3

            # Boost overview / programme summary chunks
            if "all qiu degree programmes" in clean_text or "faculties and schools" in clean_text:
                score *= 1.4

            if score > 0.1:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:top_k]

        results = []
        for s, c in top_results:
            results.append({
                "document_title": c["doc_title"],
                "content": c["content"],
                "score": round(s, 3),
            })

        return {
            "status": "success",
            "query": query,
            "results_count": len(results),
            "results": results,
        }


# Global singleton instance
standalone_rag = StandaloneRAG()


def search_knowledge(query: str, top_k: int = 4) -> Dict[str, Any]:
    return standalone_rag.search(query, top_k=top_k)


def search_knowledge_context(query: str, top_k: int = 3) -> tuple[str, list[str]]:
    """Return formatted context text block and unique document titles."""
    res = standalone_rag.search(query, top_k=top_k)
    results = res.get("results", [])
    if not results:
        return "No relevant campus documents found.", []

    parts = []
    sources = []
    for idx, r in enumerate(results, 1):
        doc = r["document_title"]
        if doc not in sources:
            sources.append(doc)
        parts.append(f"[{idx}] Source: {doc}\n{r['content']}")

    return "\n\n".join(parts), sources


if __name__ == "__main__":
    print("Testing Standalone RAG:")
    res = search_knowledge("Quest International University tuition fees")
    print(f"Found {res['results_count']} results:")
    for r in res["results"]:
        print(f"--- [{r['document_title']}] (score: {r['score']}) ---")
        print(r["content"][:300] + "...\n")
