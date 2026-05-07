"""Proxy scoring utilities for filtered ETF documents."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_ETF_DENSITY = 0.05
MAX_AD_MENTIONS = 5

try:
    from app.config.constants import AD_TERMS as _AD_TERMS
    from app.config.constants import ETF_TERMS as _ETF_TERMS
except Exception as exc:  # pragma: no cover - defensive fallback
    logger.warning("Failed to import terms from constants: %s", exc)
    _ETF_TERMS = [
        "etf",
        "상장지수펀드",
        "월배당",
        "커버드콜",
        "분배금",
        "수익률",
        "리스크",
        "포트폴리오",
        "isa",
    ]
    _AD_TERMS = [
        "광고",
        "협찬",
        "체험단",
        "유료광고",
        "원고료",
        "소정의 수수료",
        "sponsored",
        "promotion",
        "affiliate",
    ]


def _clip_01(value: float) -> float:
    """Clip numeric value into [0, 1] range."""
    return max(0.0, min(1.0, value))


def _resolve_text_for_scoring(doc: dict[str, Any]) -> str:
    """Use clean_text first; fallback to title/description when unavailable."""
    clean_text = str(doc.get("clean_text", "")).strip()
    if clean_text:
        return clean_text.lower()

    title = str(doc.get("title", ""))
    description = str(doc.get("description", ""))
    return f"{title} {description}".strip().lower()


def _resolve_doc_length(doc: dict[str, Any], fallback_text: str) -> int:
    """Use existing doc_length when present, otherwise fallback to text length."""
    existing = doc.get("doc_length")
    try:
        if existing is not None:
            return max(0, int(existing))
    except (TypeError, ValueError):
        logger.debug("Invalid existing doc_length value: %r", existing)
    return len(fallback_text)


def attach_proxy_score(doc: dict[str, Any]) -> dict[str, Any]:
    """Attach proxy_score and score_meta to a document."""
    text = _resolve_text_for_scoring(doc)
    doc_length = _resolve_doc_length(doc, text)
    words = [w for w in text.split() if w]
    word_count = max(1, len(words))

    etf_mentions = sum(text.count(term.lower()) for term in _ETF_TERMS if term)
    ad_mentions = sum(text.count(term.lower()) for term in _AD_TERMS if term)

    length_score = _clip_01((doc_length - 100) / 900)
    etf_density = etf_mentions / word_count
    etf_density_score = _clip_01(etf_density / MAX_ETF_DENSITY)
    non_ad_score = _clip_01(1.0 - (ad_mentions / MAX_AD_MENTIONS))

    proxy_score = _clip_01(
        (0.45 * length_score) + (0.4 * etf_density_score) + (0.15 * non_ad_score)
    )

    updated = dict(doc)
    updated["doc_length"] = doc_length
    updated["proxy_score"] = proxy_score
    updated["score_meta"] = {
        "length_score": length_score,
        "etf_density_score": etf_density_score,
        "non_ad_score": non_ad_score,
        "etf_mentions": etf_mentions,
        "ad_mentions": ad_mentions,
        "word_count": word_count,
    }

    logger.debug(
        "Proxy score attached (proxy_score=%.4f, length_score=%.4f, etf_density_score=%.4f, non_ad_score=%.4f)",
        proxy_score,
        length_score,
        etf_density_score,
        non_ad_score,
    )
    return updated


def attach_proxy_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach proxy score to multiple rows and log batch summary."""
    scored_rows = [attach_proxy_score(row) for row in rows]
    if not scored_rows:
        logger.info("Proxy scoring batch completed (total=0)")
        return scored_rows

    avg_proxy_score = sum(float(row.get("proxy_score", 0.0)) for row in scored_rows) / len(scored_rows)
    logger.info(
        "Proxy scoring batch completed (total=%d, avg_proxy_score=%.4f)",
        len(scored_rows),
        avg_proxy_score,
    )
    return scored_rows


def calculate_proxy_score(doc: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for attach_proxy_score."""
    return attach_proxy_score(doc)

