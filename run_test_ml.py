"""
ML 파라미터 테스트용 스크립트.
기존 수집 데이터로 ML만 재실행 — 블로그 재수집 없음.

사용법:
    python run_test_ml.py                      # 블로그 ML 실행 (기본값)
    python run_test_ml.py --source news        # 뉴스 수집 후 ML 실행
    python run_test_ml.py --period 3           # period 번호 지정
    python run_test_ml.py --delete 2           # 특정 period 삭제
    python run_test_ml.py --source news --delete 1

DB:
    블로그 → etf_trend.db
    뉴스   → etf_trend_news.db

보고서:
    python run_generate_report.py              # 블로그 보고서
    python run_generate_report.py --source news  # 뉴스 보고서
"""
import argparse
import json
from pathlib import Path

import etf_trend
from app.filtering.scorer import attach_proxy_score
from app.pipeline.run_pipeline import _DEFAULT_PROXY_THRESHOLD, _NEWS_MIN_LENGTH
from app.filtering.rule_filter import apply_rule_filter

BLOG_DOCS  = Path(__file__).parent / "data/processed/filtered_docs.json"
NEWS_DOCS  = Path(__file__).parent / "data/processed/news_docs.json"

DB_BLOG = "etf_trend.db"
DB_NEWS = "etf_trend_news.db"


def _get_default_period() -> int:
    """현재 DB에서 MAX(period)+1을 반환한다."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    etf_trend._init_db()
    with Session(etf_trend.engine) as session:
        row = session.execute(
            text("SELECT MAX(period) FROM collections WHERE status='done'")
        ).fetchone()
    max_period = row[0] if row and row[0] is not None else 0
    return max_period + 1


def _collect_and_save_news() -> None:
    """뉴스를 수집해 news_docs.json으로 저장한다."""
    from app.ingestion.naver_news import collect_news_posts
    from app.config.settings import load_settings
    from app.storage.json_store import save_json

    s = load_settings()
    keywords = list(s["DEFAULT_KEYWORDS"])
    days = int(s["DEFAULT_DAYS"])

    print(f"[news] 키워드 {len(keywords)}개, 최근 {days}일 수집 시작...")
    posts = collect_news_posts(
        keywords=keywords,
        days=days,
        max_per_keyword=int(s["MAX_RESULTS_PER_KEYWORD"]),
    )
    NEWS_DOCS.parent.mkdir(parents=True, exist_ok=True)
    save_json(posts, str(NEWS_DOCS))
    print(f"[news] 수집 완료: {len(posts)}개 → {NEWS_DOCS}")


def load_blog_posts() -> list[dict]:
    """블로그 filtered_docs.json 로드 + proxy 필터 적용."""
    with open(BLOG_DOCS, encoding="utf-8") as f:
        rows = json.load(f)

    scored = [attach_proxy_score(r) for r in rows if r.get("clean_text")]
    passed = [r for r in scored if r["proxy_score"] >= _DEFAULT_PROXY_THRESHOLD]
    print(f"[proxy filter] threshold={_DEFAULT_PROXY_THRESHOLD} | 통과 {len(passed)} / 탈락 {len(scored)-len(passed)}")

    posts = [{"text": r["clean_text"], "post_date": str(r.get("post_date", ""))}
             for r in passed if r.get("clean_text")]
    print(f"[load] 블로그 {len(posts)}개 로드 완료")
    return posts


def load_news_posts() -> list[dict]:
    """news_docs.json 로드 + rule filter + proxy 필터 적용."""
    if not NEWS_DOCS.exists():
        print("[news] news_docs.json 없음 → 자동 수집 시작")
        _collect_and_save_news()

    with open(NEWS_DOCS, encoding="utf-8") as f:
        rows = json.load(f)

    # rule filter (뉴스는 min_length=80)
    rule_filtered = [apply_rule_filter(r, min_length=_NEWS_MIN_LENGTH)
                     for r in rows if r.get("clean_text")]
    rule_passed = [r for r in rule_filtered if r.get("passed_rule_filter")]

    # proxy filter
    scored = [attach_proxy_score(r) for r in rule_passed]
    passed = [r for r in scored if r["proxy_score"] >= _DEFAULT_PROXY_THRESHOLD]
    print(f"[proxy filter] threshold={_DEFAULT_PROXY_THRESHOLD} | 통과 {len(passed)} / 탈락 {len(rows)-len(passed)}")

    posts = [{"text": r["clean_text"], "post_date": str(r.get("post_date", ""))}
             for r in passed if r.get("clean_text")]
    print(f"[load] 뉴스 {len(posts)}개 로드 완료")
    return posts


def delete_period(period: int) -> None:
    etf_trend._init_db()
    tables = ["collections", "keywords", "clusters", "cluster_runs"]
    with Session(etf_trend.engine) as session:
        for table in tables:
            result = session.execute(
                text(f"DELETE FROM {table} WHERE period = :p"), {"p": period}
            )
            print(f"[delete] {table}: {result.rowcount}행 삭제")
        session.commit()
    print(f"[done] Period {period} 삭제 완료")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", choices=["blog", "news"], default="blog",
        help="데이터 소스 (기본값: blog)",
    )
    parser.add_argument(
        "--period", type=int, default=None,
        help="실행할 period 번호 (기본값: DB MAX(period)+1 자동 산출)",
    )
    parser.add_argument("--delete", type=int, help="삭제할 period 번호")
    args = parser.parse_args()

    # DB 전환
    db_path = DB_NEWS if args.source == "news" else DB_BLOG
    etf_trend.set_db(db_path)
    print(f"[db] {db_path} 사용")

    if args.delete is not None:
        delete_period(args.delete)
        return

    period = args.period if args.period is not None else _get_default_period()

    if args.source == "news":
        posts = load_news_posts()
        report_cmd = "python run_generate_report.py --source news"
    else:
        posts = load_blog_posts()
        report_cmd = "python run_generate_report.py"

    print(f"[run] Period {period}으로 ML 실행 중...")
    etf_trend.run_period(period, posts)
    print(f"[done] Period {period} 완료. 보고서 확인: {report_cmd}")


if __name__ == "__main__":
    main()
