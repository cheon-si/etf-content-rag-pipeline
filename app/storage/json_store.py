"""JSON persistence helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def save_json(data: Any, path: str | Path) -> None:
    """Save data to JSON with UTF-8 encoding, pretty indent, and non-ASCII support."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Saving JSON to %s", output_path)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)

