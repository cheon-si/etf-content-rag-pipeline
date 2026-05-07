"""월별 LLM API 비용 추적."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from llm_pipeline.config import MONTHLY_COST_LIMIT_USD

_COST_TRACKER_PATH = Path("output") / "cost_tracker.json"


def _load() -> dict:
    if _COST_TRACKER_PATH.exists():
        return json.loads(_COST_TRACKER_PATH.read_text(encoding="utf-8"))
    return {}


def _save(tracker: dict) -> None:
    _COST_TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COST_TRACKER_PATH.write_text(
        json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_monthly_cost(run_cost: float) -> tuple[float, bool]:
    """월별 누적 비용을 갱신하고 (월 누적, 한도 초과 여부)를 반환한다."""
    tracker = _load()
    month_key = datetime.now().strftime("%Y-%m")
    tracker.setdefault(month_key, {"total_usd": 0.0, "runs": []})
    tracker[month_key]["total_usd"] += run_cost
    tracker[month_key]["runs"].append({
        "date": datetime.now().isoformat(),
        "cost_usd": run_cost,
    })
    _save(tracker)

    monthly_total = tracker[month_key]["total_usd"]
    exceeded = monthly_total > MONTHLY_COST_LIMIT_USD
    return monthly_total, exceeded
