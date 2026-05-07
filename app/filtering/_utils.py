"""Shared filtering utilities."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_doc_length(doc: dict[str, Any], fallback_text: str) -> int:
    """Use existing doc_length when present, otherwise fallback to text length."""
    existing = doc.get("doc_length")
    try:
        if existing is not None:
            return max(0, int(existing))
    except (TypeError, ValueError):
        logger.debug("Invalid existing doc_length value: %r", existing)
    return len(fallback_text)
