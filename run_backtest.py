"""
run_backtest.py — 7개 기간에 대한 ETF 키워드 백테스팅 실행기

기간:
  P1: 2026-01-01 ~ 2026-01-14
  P2: 2026-01-15 ~ 2026-01-28
  P3: 2026-01-29 ~ 2026-02-11
  P4: 2026-02-12 ~ 2026-02-25
  P5: 2026-02-26 ~ 2026-03-11
  P6: 2026-03-12 ~ 2026-03-25
  P7: 2026-03-26 ~ 2026-04-06
"""

from __future__ import annotations

import logging
import sys
from datetime import date

sys.path.insert(0, ".")

import etf_trend
from app.pipeline.run_pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

PERIODS = [
    (1, date(2026, 1,  1),  date(2026, 1, 14)),
    (2, date(2026, 1, 15),  date(2026, 1, 28)),
    (3, date(2026, 1, 29),  date(2026, 2, 11)),
    (4, date(2026, 2, 12),  date(2026, 2, 25)),
    (5, date(2026, 2, 26),  date(2026, 3, 11)),
    (6, date(2026, 3, 12),  date(2026, 3, 25)),
    (7, date(2026, 3, 26),  date(2026, 4,  6)),
]


def main() -> None:
    logger.info("=== Backtest started: %d periods ===", len(PERIODS))

    for period, start, end in PERIODS:
        logger.info("━━━ Period %d | %s ~ %s ━━━", period, start, end)
        try:
            rows = run_pipeline(period=period, start_date=start, end_date=end)
            logger.info("Period %d done (rows=%d).", period, len(rows))
        except Exception as exc:
            logger.exception("Period %d failed: %s", period, exc)

    logger.info("All periods done. Generating trend report...")
    etf_trend._init_db()
    etf_trend._run_trend_analysis()
    logger.info("=== Backtest complete. Results in ./results/ ===")


if __name__ == "__main__":
    main()
