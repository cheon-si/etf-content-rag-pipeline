"""Embedding stage utilities."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)
_FALLBACK_EMBED_DIM = 256
_MAX_FEATURES = 512


def _resolve_text(row: dict[str, Any]) -> str:
    """Resolve text for embedding with clean_text-first policy."""
    clean_text = str(row.get("clean_text", "")).strip()
    if clean_text:
        return clean_text

    title = str(row.get("title", "")).strip()
    description = str(row.get("description", "")).strip()
    return f"{title} {description}".strip()


def _embed_texts_with_hashing(texts: list[str], dim: int = _FALLBACK_EMBED_DIM) -> list[list[float]]:
    """Create deterministic hashed embeddings without external ML dependencies."""
    embeddings: list[list[float]] = []

    for text in texts:
        vector = [0.0] * dim
        tokens = [token for token in text.lower().split() if token]
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            sign = -1.0 if int(digest[8:10], 16) % 2 else 1.0
            vector[idx] += sign

        # L2 normalize for stable cosine-like behavior downstream.
        norm = sum(value * value for value in vector) ** 0.5
        if norm > 0:
            vector = [value / norm for value in vector]
        embeddings.append(vector)

    return embeddings


def _embed_texts_with_tfidf(texts: list[str]) -> list[list[float]]:
    """Create TF-IDF embeddings using scikit-learn when available."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(max_features=_MAX_FEATURES)
    matrix = vectorizer.fit_transform(texts)
    return matrix.toarray().tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create embeddings for input text list."""
    logger.info("Embedding texts requested (count=%d).", len(texts))
    if not texts:
        return []

    normalized_texts = [str(text or "").strip() for text in texts]
    if all(not text for text in normalized_texts):
        logger.warning("All input texts are empty. Returning zero fallback embeddings.")
        return _embed_texts_with_hashing([""] * len(normalized_texts))

    try:
        embeddings = _embed_texts_with_tfidf(normalized_texts)
        logger.info(
            "Embeddings generated with TF-IDF (count=%d, dim=%d).",
            len(embeddings),
            len(embeddings[0]) if embeddings else 0,
        )
        return embeddings
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("TF-IDF embedding unavailable. Falling back to hashing. reason=%s", exc)
        embeddings = _embed_texts_with_hashing(normalized_texts)
        logger.info(
            "Embeddings generated with hashing fallback (count=%d, dim=%d).",
            len(embeddings),
            len(embeddings[0]) if embeddings else 0,
        )
        return embeddings


def attach_embeddings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach embedding vectors to rows and return updated rows."""
    logger.info("Attach embeddings requested (rows=%d).", len(rows))
    if not rows:
        return []

    texts = [_resolve_text(row) for row in rows]
    vectors = embed_texts(texts)
    embedded_rows: list[dict[str, Any]] = []

    for row, vector in zip(rows, vectors, strict=False):
        updated = dict(row)
        updated["embedding"] = vector
        embedded_rows.append(updated)

    logger.info("Embedding attachment completed (rows=%d).", len(embedded_rows))
    return embedded_rows
