"""Insight stage function signatures for intent and JTBD."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def infer_search_intent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Infer search intent labels for input rows."""
    logger.info("Search intent inference requested (rows=%d).", len(rows))
    raise NotImplementedError("infer_search_intent is not implemented yet.")


def infer_jtbd(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Infer JTBD statements for input rows."""
    logger.info("JTBD inference requested (rows=%d).", len(rows))
    raise NotImplementedError("infer_jtbd is not implemented yet.")

