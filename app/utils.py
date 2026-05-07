"""공통 유틸리티 함수."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any


def week_folder() -> str:
    """이번 주 월요일 날짜 문자열 반환 (YYYY-MM-DD). results/ 하위 주간 폴더명으로 사용."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def split_by_week(rows: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    """post_date 기준으로 월요일 시작 주 단위로 그룹화."""
    week_map: dict[date, list] = defaultdict(list)
    for row in rows:
        try:
            post_dt = date.fromisoformat(str(row["post_date"]))
        except (ValueError, KeyError):
            continue
        monday = post_dt - timedelta(days=post_dt.weekday())
        week_map[monday].append(row)
    return dict(sorted(week_map.items()))
