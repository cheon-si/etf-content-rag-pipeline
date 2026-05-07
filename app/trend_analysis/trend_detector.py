"""Trend analysis stage function signatures."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def calculate_growth(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach growth-related metrics to rows."""
    logger.info("Growth calculation requested (rows=%d).", len(rows))
    raise NotImplementedError("calculate_growth is not implemented yet.")


def calculate_volume(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach volume-related metrics to rows."""
    logger.info("Volume calculation requested (rows=%d).", len(rows))
    raise NotImplementedError("calculate_volume is not implemented yet.")


def calculate_cohesion(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach cohesion-related metrics to rows."""
    logger.info("Cohesion calculation requested (rows=%d).", len(rows))
    raise NotImplementedError("calculate_cohesion is not implemented yet.")


def attach_trend_score(
    rows: list[dict[str, Any]],
    weights: dict[str, float],
) -> list[dict[str, Any]]:
    """Attach weighted trend score using growth, volume, and cohesion metrics."""
    logger.info("Trend score attachment requested (rows=%d).", len(rows))
    raise NotImplementedError("attach_trend_score is not implemented yet.")

