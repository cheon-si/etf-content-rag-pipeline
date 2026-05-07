"""VectorStore - FAISS 기반 시맨틱 검색."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import faiss
import numpy as np

from llm_pipeline.rag.embedder import embed_batch, embed_text

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS rag_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    title TEXT,
    text_preview TEXT,
    post_date TEXT,
    metadata JSON,
    faiss_idx INTEGER NOT NULL,
    UNIQUE(collection, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_rag_collection ON rag_documents(collection);
"""


class VectorStore:
    def __init__(self, index_dir: str, db_path: str):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._indices: dict[str, faiss.IndexFlatIP] = {}
        self._ensure_table()

    def _ensure_table(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.executescript(_DDL)
        con.close()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _index_path(self, collection: str) -> Path:
        return self.index_dir / f"{collection}.faiss"

    def _get_index(self, collection: str) -> faiss.IndexFlatIP | None:
        if collection in self._indices:
            return self._indices[collection]
        path = self._index_path(collection)
        if path.exists():
            idx = faiss.read_index(str(path))
            self._indices[collection] = idx
            return idx
        return None

    def _save_index(self, collection: str) -> None:
        idx = self._indices.get(collection)
        if idx is not None:
            faiss.write_index(idx, str(self._index_path(collection)))

    def _get_existing_doc_ids(self, collection: str) -> set[str]:
        con = self._connect()
        rows = con.execute(
            "SELECT doc_id FROM rag_documents WHERE collection=?", (collection,)
        ).fetchall()
        con.close()
        return {r["doc_id"] for r in rows}

    def build_index(self, collection: str, documents: list[dict]) -> int:
        """컬렉션의 인덱스를 처음부터 빌드. documents: [{doc_id, title, text, post_date, metadata}]"""
        if not documents:
            return 0

        existing = self._get_existing_doc_ids(collection)
        new_docs = [d for d in documents if d["doc_id"] not in existing]
        if not new_docs:
            logger.info("[VectorStore] %s: 새 문서 없음 (기존 %d건)", collection, len(existing))
            return 0

        texts = [f"{d.get('title', '')} {d.get('text', '')[:512]}" for d in new_docs]
        vecs = embed_batch(texts)

        idx = self._get_index(collection)
        if idx is None:
            dim = vecs.shape[1]
            idx = faiss.IndexFlatIP(dim)
            self._indices[collection] = idx

        start_idx = idx.ntotal
        idx.add(vecs)

        con = self._connect()
        for i, doc in enumerate(new_docs):
            con.execute(
                """INSERT OR IGNORE INTO rag_documents
                   (collection, doc_id, title, text_preview, post_date, metadata, faiss_idx)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (collection, doc["doc_id"], doc.get("title", ""),
                 doc.get("text", "")[:200], doc.get("post_date", ""),
                 json.dumps(doc.get("metadata", {}), ensure_ascii=False),
                 start_idx + i),
            )
        con.commit()
        con.close()

        self._save_index(collection)
        logger.info("[VectorStore] %s: %d건 인덱싱 (총 %d건)", collection, len(new_docs), idx.ntotal)
        return len(new_docs)

    def search(
        self,
        query: str,
        collection: str,
        top_k: int = 5,
        min_score: float = 0.4,
    ) -> list[dict]:
        """쿼리 텍스트로 시맨틱 검색. min_score 미만은 제거 (노이즈 컷)."""
        idx = self._get_index(collection)
        if idx is None or idx.ntotal == 0:
            return []

        q_vec = embed_text(query).reshape(1, -1)
        k = min(top_k, idx.ntotal)
        scores, indices = idx.search(q_vec, k)

        faiss_ids = indices[0].tolist()
        sim_scores = scores[0].tolist()

        con = self._connect()
        results = []
        for fid, score in zip(faiss_ids, sim_scores):
            if fid < 0:
                continue
            if score < min_score:
                continue
            row = con.execute(
                "SELECT * FROM rag_documents WHERE collection=? AND faiss_idx=?",
                (collection, fid),
            ).fetchone()
            if row:
                results.append({
                    "doc_id": row["doc_id"],
                    "title": row["title"],
                    "text_preview": row["text_preview"],
                    "post_date": row["post_date"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "score": round(score, 4),
                })
        con.close()
        return results

    def collection_size(self, collection: str) -> int:
        con = self._connect()
        row = con.execute(
            "SELECT COUNT(*) FROM rag_documents WHERE collection=?", (collection,)
        ).fetchone()
        con.close()
        return row[0]
