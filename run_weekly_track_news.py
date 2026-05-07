"""
run_weekly_track_news.py — ETF 키워드 주간 트렌드 트래커 (뉴스 버전)

네이버 뉴스 수집 → 날짜 기준 1주 단위 자동 분리 → ML 분석 (etf_trend_news.db)
블로그 본문 추출 없이 title+description 기반으로 바로 필터링·ML 실행.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta

sys.path.insert(0, ".")

import etf_trend
from app.config.settings import load_settings
from app.filtering.rule_filter import apply_rule_filter_to_rows
from app.filtering.scorer import attach_proxy_scores
from app.ingestion.naver_news import collect_news_posts
from app.storage.json_store import save_json
from app.utils import split_by_week, week_folder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SEED_KEYWORD = "ETF"
MAX_POSTS = 1000
NEWS_DB = "etf_trend_news.db"
NEWS_MIN_LENGTH = 80
PROXY_THRESHOLD = 0.55


def collect_and_filter_news() -> list[dict[str, Any]]:
    """뉴스 수집 후 필터링. 본문 추출 없이 title+description 기반 clean_text 사용."""
    load_settings()  # API 키 검증
    logger.info("뉴스 수집 시작: keyword=%s, max=%d", SEED_KEYWORD, MAX_POSTS)
    raw_rows = collect_news_posts(
        keywords=[SEED_KEYWORD],
        days=365,
        max_per_keyword=MAX_POSTS,
    )
    for row in raw_rows:
        row.setdefault("source_type", "news")
    logger.info("수집 완료: %d개", len(raw_rows))
    save_json(raw_rows, "data/raw/news_weekly_raw.json")

    # 뉴스는 title+description이 clean_text로 이미 설정됨 → 바로 필터링
    rule_filtered = apply_rule_filter_to_rows(raw_rows, min_length=NEWS_MIN_LENGTH)
    scored = attach_proxy_scores(rule_filtered)
    final = [
        r for r in scored
        if r.get("passed_rule_filter") and float(r.get("proxy_score", 0)) >= PROXY_THRESHOLD
    ]

    logger.info("필터링 완료: %d → %d개 (rule+proxy)", len(raw_rows), len(final))
    save_json(final, "data/processed/news_weekly_filtered.json")
    return final


def run_weekly_track_news() -> None:
    etf_trend.set_db(NEWS_DB)
    etf_trend._init_db()

    rows = collect_and_filter_news()
    if not rows:
        logger.error("수집된 데이터가 없습니다.")
        return

    week_map = split_by_week(rows)
    weeks = sorted(week_map.keys())
    logger.info("감지된 주: %d개 (%s ~ %s)", len(weeks), weeks[0], weeks[-1])

    print("\n=== 주별 뉴스 데이터 현황 ===")
    for monday in weeks:
        sunday = monday + timedelta(days=6)
        print(f"  {monday} ~ {sunday}: {len(week_map[monday])}개")

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

    logger.info("트렌드 리포트 생성 중...")
    etf_trend.RESULTS_DIR = etf_trend._PROJECT_ROOT / "results" / week_folder() / "news"
    etf_trend.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    etf_trend._run_trend_analysis()
    print(f"\n뉴스 ML 분석 완료: DB={NEWS_DB}")


if __name__ == "__main__":
    run_weekly_track_news()
