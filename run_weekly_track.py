"""
run_weekly_track.py — ETF 키워드 주간 트렌드 트래커

"ETF" 키워드 하나로 API 최대치 수집 → 날짜 기준으로 1주 단위 자동 분리 → 각 주 ML 분석
API가 닿는 만큼만 추적하고, 기간은 자동으로 결정됩니다.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta

sys.path.insert(0, ".")

import etf_trend
from app.ingestion.naver_blog import collect_blog_posts
from app.pipeline.run_pipeline import run_filtering, run_preprocessing
from app.storage.json_store import save_json
from app.utils import split_by_week, week_folder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SEED_KEYWORD = "ETF"
MAX_POSTS = 1000   # 네이버 API 최대치


def collect_and_preprocess() -> list[dict[str, Any]]:
    """ETF 키워드 하나로 최대치 수집 후 전처리/필터링."""
    logger.info("수집 시작: keyword=%s, max=%d", SEED_KEYWORD, MAX_POSTS)
    raw_rows = collect_blog_posts(
        keywords=[SEED_KEYWORD],
        days=365,
        max_per_keyword=MAX_POSTS,
    )
    logger.info("수집 완료: %d개", len(raw_rows))
    save_json(raw_rows, "data/raw/weekly_raw.json")

    preprocessed = run_preprocessing(raw_rows)
    final = run_filtering(preprocessed)

    logger.info("필터링 완료: %d → %d개", len(raw_rows), len(final))
    save_json(final, "data/processed/weekly_filtered.json")
    return final


def run_weekly_track() -> None:
    etf_trend._init_db()

    # 수집 + 전처리
    rows = collect_and_preprocess()
    if not rows:
        logger.error("수집된 데이터가 없습니다.")
        return

    # 주 단위 분리
    week_map = split_by_week(rows)
    weeks = sorted(week_map.keys())
    logger.info("감지된 주: %d개 (%s ~ %s)", len(weeks), weeks[0], weeks[-1])

    print("\n=== 주별 데이터 현황 ===")
    for monday in weeks:
        sunday = monday + timedelta(days=6)
        print(f"  {monday} ~ {sunday}: {len(week_map[monday])}개")

    # 각 주 ML 분석: 날짜 기준 중복 체크 → 새 주만 처리
    # period는 DB MAX(period)+1로 순차 증가 (날짜가 바뀌어도 번호 유지)
    for monday in weeks:
        sunday = monday + timedelta(days=6)
        week_start_str = monday.isoformat()

        if etf_trend._is_week_done(week_start_str):
            logger.info("Week %s already done — skip.", week_start_str)
            continue

        week_rows = week_map[monday]
        posts = [
            {"text": r.get("clean_text", ""), "post_date": r.get("post_date", "")}
            for r in week_rows
            if r.get("clean_text")
        ]
        period = etf_trend.get_next_period()
        logger.info("━━━ Period %d | %s ~ %s | %d posts ━━━", period, monday, sunday, len(posts))

        if len(posts) < 10:
            logger.warning("  포스트 수 부족 (n=%d) — ML 스킵", len(posts))
            continue

        etf_trend.run_period(period, posts, week_start=week_start_str)

    # 전체 트렌드 리포트
    logger.info("트렌드 리포트 생성 중...")
    etf_trend.RESULTS_DIR = etf_trend._PROJECT_ROOT / "results" / week_folder()
    etf_trend.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    etf_trend._run_trend_analysis()
    print(f"\n리포트 저장 완료: ./results/{week_folder()}/")


if __name__ == "__main__":
    run_weekly_track()
