"""
run_all.py — ETF 트렌드 분석 전체 파이프라인 통합 실행기

실행 순서:
  1. run_weekly_track  — 네이버 블로그 수집 + ML 분석
  2. run_datalab_trend — DataLab 검색량 트렌드
  3. run_youtube_trend — YouTube 영상 트렌드 (YOUTUBE_API_KEY 없으면 스킵)
  4. run_generate_report — HTML 보고서 생성
  5~8. 뉴스 수집/DataLab/YouTube/보고서
  9.   콘텐츠 브리프 통합 보고서
  9.5. RAG 데이터 갱신 — Wiki(네이버/LSEG) + Vector(블로그/뉴스/과거결과물)
  10.  LLM 콘텐츠 아이디어 + 트렌드 브리프 생성
  11.  이메일 발송

각 단계가 실패해도 다음 단계는 계속 실행됩니다.
실행 로그: logs/run_YYYYMMDD_HHMMSS.log
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

# ── 로그 설정 ─────────────────────────────────────────────────────────────────
LOGS_DIR = Path("./logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

log_filename = LOGS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Windows cp949 콘솔 호환: StreamHandler에 utf-8 강제 적용
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1) \
    if hasattr(sys.stdout, 'fileno') else sys.stdout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        _stdout_handler,
    ],
)
logger = logging.getLogger(__name__)


def _run_step(name: str, fn) -> bool:
    """단계 실행 래퍼. 성공하면 True, 실패하면 False 반환."""
    logger.info("=" * 60)
    logger.info(">> STEP START: %s", name)
    logger.info("=" * 60)
    t0 = time.time()
    try:
        fn()
        elapsed = time.time() - t0
        logger.info("OK STEP DONE: %s (%.1fs)", name, elapsed)
        return True
    except Exception:
        elapsed = time.time() - t0
        logger.error("FAIL STEP FAILED: %s (%.1fs)\n%s", name, elapsed, traceback.format_exc())
        return False


def main() -> None:
    start_time = time.time()
    logger.info("ETF 주간 전체 파이프라인 시작")
    logger.info("로그 파일: %s", log_filename.resolve())

    results: dict[str, bool] = {}

    # ── Step 1: 블로그 수집 + ML ──────────────────────────────────────────────
    def step1():
        from run_weekly_track import run_weekly_track
        run_weekly_track()

    results["1. 블로그 수집 + ML"] = _run_step("블로그 수집 + ML", step1)

    # ── Step 2: DataLab 트렌드 ────────────────────────────────────────────────
    def step2():
        from run_datalab_trend import main as datalab_main
        datalab_main()

    results["2. DataLab 트렌드"] = _run_step("DataLab 트렌드", step2)

    # ── Step 3: YouTube 트렌드 (API 키 없으면 스킵) ───────────────────────────
    def step3():
        from app.config.settings import load_settings
        settings = load_settings()
        if not settings.get("YOUTUBE_API_KEY"):
            logger.info("YOUTUBE_API_KEY 없음 → YouTube 단계 스킵")
            return
        from run_youtube_trend import main as yt_main
        yt_main()

    results["3. YouTube 트렌드"] = _run_step("YouTube 트렌드", step3)

    # ── Step 4: 블로그 보고서 생성 ───────────────────────────────────────────
    def step4():
        from run_generate_report import build_report
        build_report(source="blog")

    results["4. HTML 보고서 (블로그)"] = _run_step("HTML 보고서 (블로그)", step4)

    # ── Step 5: 뉴스 수집 + ML ───────────────────────────────────────────────
    def step5():
        from run_weekly_track_news import run_weekly_track_news
        run_weekly_track_news()

    results["5. 뉴스 수집 + ML"] = _run_step("뉴스 수집 + ML", step5)

    # ── Step 6: 뉴스 DataLab 트렌드 ─────────────────────────────────────────
    def step6():
        from run_datalab_trend import main as datalab_main
        datalab_main(source="news")

    results["6. DataLab 트렌드 (뉴스)"] = _run_step("DataLab 트렌드 (뉴스)", step6)

    # ── Step 7: 뉴스 YouTube 트렌드 ──────────────────────────────────────────
    def step7():
        from app.config.settings import load_settings
        settings = load_settings()
        if not settings.get("YOUTUBE_API_KEY"):
            logger.info("YOUTUBE_API_KEY 없음 → YouTube (뉴스) 단계 스킵")
            return
        from run_youtube_trend import main as yt_main
        yt_main(source="news")

    results["7. YouTube 트렌드 (뉴스)"] = _run_step("YouTube 트렌드 (뉴스)", step7)

    # ── Step 8: 뉴스 보고서 생성 ─────────────────────────────────────────────
    def step8():
        from run_generate_report import build_report
        build_report(source="news")

    results["8. HTML 보고서 (뉴스)"] = _run_step("HTML 보고서 (뉴스)", step8)

    # ── Step 9: 콘텐츠 브리프 통합 보고서 ───────────────────────────────────
    def step9():
        from run_generate_content_brief import build_content_brief_report
        build_content_brief_report()

    results["9. 콘텐츠 브리프"] = _run_step("콘텐츠 브리프", step9)

    # ── Step 9.5: RAG 데이터 갱신 (Wiki + Vector) ────────────────────────────
    def step9_5():
        from llm_pipeline.rag.wiki import WikiStore
        from llm_pipeline.rag.vector_store import VectorStore
        from llm_pipeline.rag.wiki_seed import (
            seed_products, seed_tax_rules, seed_regulations,
            DB_PATH,
        )
        from llm_pipeline.rag.theme_loader import (
            load_etf_metadata_from_snapshot, SNAPSHOT_JSON_PATH,
        )
        from llm_pipeline.rag.indexer import (
            index_blog_corpus, index_news_corpus, index_past_outputs,
            INDEX_DIR,
        )

        wiki = WikiStore(DB_PATH)

        n_products = seed_products(wiki)
        n_tax = seed_tax_rules(wiki)
        n_reg = seed_regulations(wiki)
        logger.info("Wiki 시드: 상품=%d, 세제=%d, 규제=%d", n_products, n_tax, n_reg)

        try:
            metadata = load_etf_metadata_from_snapshot(SNAPSHOT_JSON_PATH)
            n_meta = wiki.update_product_metadata(metadata)
            logger.info("LSEG 고정 메타 주입: %d개 종목 (스냅샷)", n_meta)
        except FileNotFoundError:
            logger.warning(
                "LSEG 스냅샷 JSON 없음 → 고정 메타 갱신 스킵. "
                "복구: data/raw/lseg.xlsx 두고 'python -m llm_pipeline.rag.theme_loader snapshot' 실행. 경로: %s",
                SNAPSHOT_JSON_PATH,
            )

        vs = VectorStore(INDEX_DIR, DB_PATH)
        n_blog = index_blog_corpus(vs)
        n_news = index_news_corpus(vs)
        n_past = index_past_outputs(vs)
        logger.info(
            "Vector 인덱싱(증분): 블로그=%d, 뉴스=%d, 과거결과=%d",
            n_blog, n_news, n_past,
        )

    results["9.5 RAG 데이터 갱신"] = _run_step("RAG 데이터 갱신", step9_5)

    # ── Step 10: LLM 콘텐츠 아이디어 + 트렌드 브리프 생성 ────────────────────
    def step10():
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(".env"), override=True)
        from llm_pipeline.main import run_marketing_outputs
        run_marketing_outputs()

    results["10. LLM 콘텐츠 아이디어 + 브리프"] = _run_step(
        "LLM 콘텐츠 아이디어 + 브리프", step10
    )

    # ── Step 11: 이메일 발송 ─────────────────────────────────────────────────
    def step11():
        from datetime import datetime as _dt
        import json as _json
        from llm_pipeline.email_sender import send_weekly_email

        today = _dt.now().strftime("%Y-%m-%d")
        cost_tracker_path = Path("output") / "cost_tracker.json"
        cost_summary = ""
        if cost_tracker_path.exists():
            tracker = _json.loads(cost_tracker_path.read_text(encoding="utf-8"))
            month_key = _dt.now().strftime("%Y-%m")
            if month_key in tracker:
                monthly = tracker[month_key]["total_usd"]
                cost_summary = f"월 누적 ${monthly:.4f}"

        output_dir = Path("output") / today
        send_weekly_email(
            output_dir=output_dir,
            cost_summary=cost_summary,
        )

    results["11. 이메일 발송"] = _run_step("이메일 발송", step11)

    # ── 최종 요약 ─────────────────────────────────────────────────────────────
    total_elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("파이프라인 완료 (총 %.1f초)", total_elapsed)
    logger.info("=" * 60)
    for step_name, success in results.items():
        status = "OK 성공" if success else "FAIL 실패"
        logger.info("  %s  %s", status, step_name)

    failed = [k for k, v in results.items() if not v]
    if failed:
        logger.warning("실패한 단계: %s", ", ".join(failed))
        sys.exit(1)
    else:
        logger.info("모든 단계 성공 → 블로그 보고서:      results/etf_trend_report.html")
        logger.info("              → 뉴스 보고서:        results/news/etf_trend_news_report.html")
        logger.info("              → 콘텐츠 브리프:      results/etf_content_brief.html")
        logger.info("              → 콘텐츠 아이디어:    output/YYYY-MM-DD/content_ideas_report.html")
        logger.info("              → LLM 브리프:         output/YYYY-MM-DD/content_brief_report.html")


if __name__ == "__main__":
    main()
