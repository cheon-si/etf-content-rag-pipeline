"""CSV persistence helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def save_csv(data: Any, path: str | Path) -> None:
    """Save data to CSV with UTF-8 BOM encoding and auto-create parent directory."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    logger.info("Saving CSV to %s (rows=%d, cols=%d)", output_path, len(frame), len(frame.columns))
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")

