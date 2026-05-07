"""Rule-based document filtering for ETF content."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from app.config.constants import ETF_TERMS as _ETF_TERMS
except Exception as exc:  # pragma: no cover - defensive fallback
    logger.warning("Failed to import ETF_TERMS from constants: %s", exc)
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
        "연금",
    ]


def _get_text_from_doc(doc: dict[str, Any]) -> str:
    """Build a single lowercase text blob from common document fields."""
    parts = [
        str(doc.get("title", "")),
        str(doc.get("description", "")),
        str(doc.get("clean_text", "")),
        str(doc.get("text", "")),
    ]
    return " ".join(parts).strip().lower()


def _resolve_doc_length(doc: dict[str, Any], fallback_text: str) -> int:
    """Use existing doc_length when available, otherwise fallback to text length."""
    existing = doc.get("doc_length")
    try:
        if existing is not None:
            return max(0, int(existing))
    except (TypeError, ValueError):
        logger.debug("Invalid existing doc_length value: %r", existing)
    return len(fallback_text)


def apply_rule_filter(doc: dict[str, Any], min_length: int = 150) -> dict[str, Any]:
    """Apply minimum-length and ETF-term rules and append filtering metadata."""
    text = _get_text_from_doc(doc)
    etf_mentions = sum(text.count(term.lower()) for term in _ETF_TERMS if term)
    has_etf_term = etf_mentions > 0
    doc_length = _resolve_doc_length(doc, text)
    passed = doc_length >= min_length and has_etf_term

    updated = dict(doc)
    updated["doc_length"] = doc_length
    updated["etf_mentions"] = etf_mentions
    updated["has_etf_term"] = has_etf_term
    updated["passed_rule_filter"] = passed

    logger.debug(
        "Rule filter result (length=%d, min_length=%d, etf_mentions=%d, passed=%s)",
        doc_length,
        min_length,
        etf_mentions,
        passed,
    )
    return updated


def apply_rule_filter_to_rows(
    rows: list[dict[str, Any]],
    min_length: int = 150,
) -> list[dict[str, Any]]:
    """Apply rule filter to rows and return updated rows with summary logging."""
    filtered_rows = [apply_rule_filter(row, min_length=min_length) for row in rows]
    passed_count = sum(1 for row in filtered_rows if row.get("passed_rule_filter") is True)

    logger.info(
        "Rule filter batch completed (total=%d, passed=%d, failed=%d, min_length=%d)",
        len(filtered_rows),
        passed_count,
        len(filtered_rows) - passed_count,
        min_length,
    )
    return filtered_rows

