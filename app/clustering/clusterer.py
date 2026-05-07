"""Clustering stage utilities."""

from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)
_MIN_CLUSTERS = 2
_MAX_CLUSTERS = 12


def _resolve_embedding(row: dict[str, Any]) -> list[float]:
    """Return embedding vector from a row, or an empty list when unavailable."""
    embedding = row.get("embedding")
    if isinstance(embedding, list) and embedding:
        try:
            return [float(value) for value in embedding]
        except (TypeError, ValueError):
            return []
    return []


def _estimate_cluster_count(n_rows: int) -> int:
    """Estimate a practical number of clusters from row count."""
    if n_rows <= 1:
        return 1
    estimated = max(_MIN_CLUSTERS, int((n_rows ** 0.5) / 1.5))
    estimated = min(estimated, _MAX_CLUSTERS, n_rows)
    return max(1, estimated)


def _cluster_with_hash(rows: list[dict[str, Any]], n_clusters: int) -> list[int]:
    """Fallback clustering using stable hash partitioning."""
    labels: list[int] = []
    for index, row in enumerate(rows):
        key = str(row.get("doc_id", "")) or f"row-{index}"
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        labels.append(int(digest[:8], 16) % n_clusters)
    return labels


def _cluster_with_kmeans(embeddings: list[list[float]], n_clusters: int) -> list[int]:
    """Cluster embeddings with scikit-learn KMeans."""
    from sklearn.cluster import KMeans

    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    return model.fit_predict(embeddings).tolist()


def cluster_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign cluster IDs to documents."""
    logger.info("Clustering requested (rows=%d).", len(rows))
    if not rows:
        return []

    n_clusters = _estimate_cluster_count(len(rows))
    embeddings = [_resolve_embedding(row) for row in rows]
    has_valid_embeddings = all(bool(vector) for vector in embeddings)

    if n_clusters == 1:
        labels = [0] * len(rows)
    elif has_valid_embeddings:
        try:
            labels = _cluster_with_kmeans(embeddings, n_clusters=n_clusters)
            logger.info(
                "KMeans clustering completed (rows=%d, clusters=%d).",
                len(rows),
                n_clusters,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("KMeans clustering failed. Falling back to hash clustering. reason=%s", exc)
            labels = _cluster_with_hash(rows, n_clusters=n_clusters)
    else:
        logger.warning("Embeddings missing or invalid. Falling back to hash clustering.")
        labels = _cluster_with_hash(rows, n_clusters=n_clusters)

    clustered_rows: list[dict[str, Any]] = []
    for row, label in zip(rows, labels, strict=False):
        updated = dict(row)
        updated["cluster_id"] = int(label)
        clustered_rows.append(updated)

    logger.info("Cluster IDs attached (rows=%d).", len(clustered_rows))
    return clustered_rows


def summarize_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize clustered documents into cluster-level outputs."""
    logger.info("Cluster summary requested (rows=%d).", len(rows))
    if not rows:
        return []

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cluster_id = int(row.get("cluster_id", -1))
        grouped[cluster_id].append(row)

    summaries: list[dict[str, Any]] = []
    for cluster_id, cluster_rows in grouped.items():
        keyword_counter: Counter[str] = Counter(
            str(row.get("keyword", "")).strip() for row in cluster_rows if str(row.get("keyword", "")).strip()
        )
        top_keywords = [keyword for keyword, _ in keyword_counter.most_common(5)]

        proxy_scores = [float(row.get("proxy_score", 0.0)) for row in cluster_rows]
        doc_lengths = [int(row.get("doc_length", 0)) for row in cluster_rows]

        summary = {
            "cluster_id": cluster_id,
            "doc_count": len(cluster_rows),
            "avg_proxy_score": (sum(proxy_scores) / len(proxy_scores)) if proxy_scores else 0.0,
            "avg_doc_length": (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 0.0,
            "top_keywords": top_keywords,
        }
        summaries.append(summary)

    summaries.sort(key=lambda item: int(item["doc_count"]), reverse=True)
    logger.info("Cluster summary completed (clusters=%d).", len(summaries))
    return summaries
