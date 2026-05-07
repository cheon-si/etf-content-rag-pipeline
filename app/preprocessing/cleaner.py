"""Text cleaning utilities for blog preprocessing."""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
# Keep common punctuation/symbols to avoid over-cleaning meaning-bearing text.
_SPECIAL_CHAR_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,!?%()/\-+:&\"'\[\]{}~@#*=]")


def clean_text(text: str) -> dict[str, str | int]:
    """Clean input text and return normalized text with document length."""
    try:
        if not text:
            return {"clean_text": "", "doc_length": 0}

        # Defensive fallback: remove possible HTML fragments that remain in raw text.
        no_html = BeautifulSoup(text, "html.parser").get_text(" ")
        normalized = _WHITESPACE_RE.sub(" ", no_html).strip()
        normalized = _SPECIAL_CHAR_RE.sub(" ", normalized)
        normalized = _WHITESPACE_RE.sub(" ", normalized).strip()

        doc_length = len(normalized)
        return {"clean_text": normalized, "doc_length": doc_length}
    except Exception as exc:
        logger.exception("Failed to clean text: %s", exc)
        return {"clean_text": "", "doc_length": 0}


def enrich_document_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Populate clean_text and doc_length for each row using raw_text."""
    logger.info("Start enriching document fields (rows=%d)", len(rows))
    enriched_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        raw_text = str(row.get("raw_text", ""))
        cleaned = clean_text(raw_text)

        updated_row = dict(row)
        updated_row["clean_text"] = cleaned["clean_text"]
        updated_row["doc_length"] = cleaned["doc_length"]
        enriched_rows.append(updated_row)

        if (idx + 1) % 100 == 0:
            logger.info("Enriched rows progress: %d/%d", idx + 1, len(rows))

    logger.info("Completed enriching document fields (rows=%d)", len(enriched_rows))
    return enriched_rows

