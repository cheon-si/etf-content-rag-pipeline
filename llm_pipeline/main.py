"""CLI 엔트리포인트.

사용법:
    python -m llm_pipeline.main --report path/to/report.html
    python -m llm_pipeline.main --report report.html --clusters 1,3
    python -m llm_pipeline.main --report report.html --list-clusters
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_ROOT = Path("output")

from llm_pipeline.cost_tracker import update_monthly_cost as _update_monthly_cost


def _write_article(geo_output, cluster, run_date: str, output_dir: Path) -> Path:
    from llm_pipeline.prompts import CONTENT_FOOTER

    slug = cluster.cluster_name.replace("/", "-").replace(" ", "_")[:40]
    filename = f"cluster_{cluster.rank}_{slug}.md"
    path = output_dir / filename

    body = geo_output.optimized_markdown + CONTENT_FOOTER
    path.write_text(body, encoding="utf-8")
    logger.info("원고 저장: %s", path)
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ETF 블로그 콘텐츠 자동 생성")
    parser.add_argument("--report", required=True, help="HTML 리포트 경로")
    parser.add_argument(
        "--clusters",
        default=None,
        help="처리할 클러스터 지정. 미지정 시 상위 3개 자동 선택.\n"
             "번호: '1,3' (테이블 순서 1-based)\n"
             "이름: '미국테크/AI,채권ETF' (부분 일치)",
    )
    parser.add_argument(
        "--top-n", type=int, default=3,
        help="--clusters 미지정 시 선택할 클러스터 수 (기본 3)",
    )
    parser.add_argument(
        "--list-clusters", action="store_true",
        help="리포트의 클러스터 목록을 출력하고 종료",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="출력 디렉토리 날짜 (기본: 오늘, 형식: YYYY-MM-DD)",
    )
    args = parser.parse_args(argv)

    from llm_pipeline.parser import list_clusters, parse_clusters

    report_path = Path(args.report)
    if not report_path.exists():
        logger.error("리포트 파일을 찾을 수 없습니다: %s", report_path)
        sys.exit(1)

    # --list-clusters 모드
    if args.list_clusters:
        all_clusters = list_clusters(report_path)
        print(f"\n{'번호':>4}  {'포스트 수':>8}  클러스터명")
        print("-" * 50)
        for c in all_clusters:
            print(f"{c.table_index + 1:>4}  {c.post_count:>8,}  {c.cluster_name}")
        return

    # 클러스터 선택
    clusters = parse_clusters(report_path, spec=args.clusters, top_n=args.top_n)
    if not clusters:
        logger.error("선택된 클러스터가 없습니다.")
        sys.exit(1)

    logger.info("처리할 클러스터 %d개:", len(clusters))
    for c in clusters:
        logger.info("  [%d] %s (%d 포스트)", c.rank, c.cluster_name, c.post_count)

    # 클라이언트 초기화
    from llm_pipeline.clients.anthropic_client import AnthropicClient
    from llm_pipeline.clients.gemini_client import GeminiClient
    from llm_pipeline.orchestrator import run_cluster_pipeline
    from llm_pipeline.schemas import RunCostReport
    from llm_pipeline.config import MONTHLY_COST_LIMIT_USD

    anthropic = AnthropicClient()
    gemini = GeminiClient()

    output_dir = OUTPUT_ROOT / args.date
    output_dir.mkdir(parents=True, exist_ok=True)

    # 파이프라인 실행
    cluster_reports = []
    article_paths = []

    for cluster in clusters:
        try:
            geo_output, cost_report = run_cluster_pipeline(
                cluster, output_dir, anthropic, gemini
            )
            article_path = _write_article(geo_output, cluster, args.date, output_dir)
            article_paths.append(article_path)
            cluster_reports.append(cost_report)
        except Exception as exc:
            logger.error("[Cluster %d] 파이프라인 실패: %s", cluster.rank, exc)
            raise

    # 비용 집계
    total_run_cost = sum(r.total_cost_usd for r in cluster_reports)
    monthly_total, exceeded = _update_monthly_cost(total_run_cost)

    run_report = RunCostReport(
        run_date=args.date,
        clusters=cluster_reports,
        total_cost_usd=total_run_cost,
        monthly_total_usd=monthly_total,
        monthly_limit_usd=MONTHLY_COST_LIMIT_USD,
        limit_exceeded=exceeded,
    )

    cost_report_path = output_dir / "cost_report.json"
    cost_report_path.write_text(
        json.dumps(run_report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 결과 출력
    print("\n" + "=" * 60)
    print(f"완료: {len(article_paths)}개 원고 생성")
    for p in article_paths:
        print(f"  OK {p}")
    print(f"\n이번 실행 비용:  ${total_run_cost:.4f}")
    print(f"이번 달 누적:    ${monthly_total:.4f} / ${MONTHLY_COST_LIMIT_USD:.2f}")
    if exceeded:
        print(f"⚠️  월 한도 ${MONTHLY_COST_LIMIT_USD:.0f} 초과!")
    print(f"\n비용 리포트: {cost_report_path}")
    print("=" * 60)


def _load_clusters_from_intermediate(
    output_root: Path,
    top_n: int = 3,
) -> tuple[list, list]:
    """가장 최근 output 디렉토리의 intermediate JSON에서 ClusterInput + JTBDOutput 복원.

    Returns:
        (clusters, jtbd_list) — 둘 다 비어있으면 ([], [])
    """
    import json as _j
    from llm_pipeline.schemas import ClusterInput, JTBDOutput

    # 날짜 디렉토리 중 intermediate 폴더가 있는 최신 것 탐색
    date_dirs = sorted(
        [d for d in output_root.iterdir() if d.is_dir() and (d / "intermediate").exists()],
        key=lambda d: d.name,
        reverse=True,
    )
    if not date_dirs:
        return [], []

    inter_dir = date_dirs[0] / "intermediate"
    logger.info("Intermediate 디렉토리: %s", inter_dir)

    clusters: list[ClusterInput] = []
    jtbd_list: list[JTBDOutput] = []

    # cluster_{rank}_s2_jtbd.json 이 있는 rank를 탐색
    for rank in range(1, top_n + 1):
        s1_path = inter_dir / f"cluster_{rank}_s1_intent.json"
        s2_path = inter_dir / f"cluster_{rank}_s2_jtbd.json"
        s3_path = inter_dir / f"cluster_{rank}_s3_cluster.json"

        if not s2_path.exists():
            continue

        jtbd_data = _j.loads(s2_path.read_text(encoding="utf-8"))
        jtbd = JTBDOutput(**jtbd_data)
        jtbd_list.append(jtbd)

        # 클러스터명과 키워드는 s3 데이터에서 복원
        cluster_name = f"cluster_{rank}"
        keywords: list[str] = []
        if s3_path.exists():
            s3_data = _j.loads(s3_path.read_text(encoding="utf-8"))
            cluster_name = s3_data.get("pillar_title", cluster_name)[:40]
            # sub_topics의 키워드를 flat하게 모아 top 10
            for st in s3_data.get("sub_topics", [])[:3]:
                keywords.extend(st.get("keywords", []))
            keywords = list(dict.fromkeys(keywords))[:10]  # 중복 제거

        clusters.append(ClusterInput(
            rank=rank,
            cluster_name=cluster_name,
            keywords=keywords,
            post_count=0,
        ))

    return clusters, jtbd_list


def _resolve_clusters(
    report_path: Path | None,
    top_n: int,
) -> tuple[list, list]:
    """클러스터 소스를 결정한다: DB 가중 선택 → HTML 리포트 → intermediate JSON.

    Returns:
        (clusters, prefilled_jtbd) — jtbd는 intermediate 복원 시에만 채워짐
    """
    import glob as glob_mod

    project_root = Path(__file__).resolve().parent.parent
    blog_db = project_root / "etf_trend.db"
    news_db = project_root / "etf_trend_news.db"

    if blog_db.exists() and news_db.exists():
        from llm_pipeline.cluster_selector import select_clusters
        clusters = select_clusters(
            blog_db=str(blog_db),
            news_db=str(news_db),
            top_common=2,
            top_blog=1,
            top_news=1,
        )
        logger.info("DB 가중 선택으로 클러스터 %d개 로드 (공통2+블로그1+뉴스1)", len(clusters))
        return clusters, []

    logger.warning("etf_trend.db / etf_trend_news.db 없음 — fallback 시도")

    if report_path is None:
        candidates = sorted(
            glob_mod.glob("results/etf_trend_report*.html"),
            key=lambda p: Path(p).stat().st_mtime,
            reverse=True,
        )
        if candidates:
            report_path = Path(candidates[0])
            logger.info("리포트 자동 탐지: %s", report_path)

    if report_path is not None and report_path.exists():
        from llm_pipeline.parser import parse_clusters
        clusters = parse_clusters(report_path, top_n=top_n)
        logger.info("HTML 리포트에서 클러스터 %d개 로드", len(clusters))
        return clusters, []

    clusters, jtbd_list = _load_clusters_from_intermediate(OUTPUT_ROOT, top_n)
    if not clusters:
        raise FileNotFoundError(
            "etf_trend.db, HTML 리포트, intermediate JSON 모두 없습니다. "
            "먼저 run_all.py Step 1~4를 실행하거나 --report 옵션을 사용하세요."
        )
    return clusters, jtbd_list


def _run_pipeline_for_cluster(
    cluster,
    prefilled_jtbd,
    cluster_index: int,
    inter_dir: Path,
    anthropic,
    gemini,
    all_usages: list,
    rag=None,
):
    """클러스터 하나에 대해 S1→S2→S3→ContentIdeas를 실행한다.

    Returns:
        (jtbd, cluster_design, ideas, usages)
    """
    import json as _json

    from llm_pipeline.stages import s1_intent, s2_jtbd, s3_cluster
    from llm_pipeline.schemas import ContentClusterOutput
    from llm_pipeline.outputs.content_ideas import run_content_ideas

    # S1→S2: prefilled인 경우 재실행 생략
    if cluster_index < len(prefilled_jtbd):
        jtbd = prefilled_jtbd[cluster_index]
    else:
        intent, u1 = s1_intent.run(cluster, anthropic)
        jtbd, u2 = s2_jtbd.run(cluster, intent, anthropic)
        all_usages.extend([u1, u2])

    # S3: 캐시 우선
    s3_cache_path = inter_dir / f"cluster_{cluster.rank}_s3_cluster.json"
    cluster_design: ContentClusterOutput | None = None

    if s3_cache_path.exists():
        try:
            cluster_design = ContentClusterOutput(
                **_json.loads(s3_cache_path.read_text(encoding="utf-8"))
            )
            logger.info("[S3] 클러스터 %d S3 캐시 로드: %s", cluster.rank, s3_cache_path)
        except Exception as exc:
            logger.warning("[S3] 캐시 로드 실패 (%s) — S3 재실행", exc)

    if cluster_design is None:
        try:
            intent_for_s3, _ = s1_intent.run(cluster, anthropic)
            cluster_design, u3 = s3_cluster.run(cluster, intent_for_s3, jtbd, anthropic, gemini)
            all_usages.extend(u3)
            s3_cache_path.write_text(
                _json.dumps(cluster_design.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("[S3] 클러스터 %d S3 실행 완료, 캐시 저장", cluster.rank)
        except Exception as exc:
            logger.warning("[S3] 클러스터 %d S3 실행 실패: %s — S3 없이 진행", cluster.rank, exc)

    rag_context = ""
    if rag is not None:
        rag_context = rag.build_context("content_ideas", cluster.keywords, cluster.cluster_name)

    ideas, u_ideas = run_content_ideas(cluster, jtbd, anthropic, cluster_design=cluster_design, rag_context=rag_context)
    all_usages.append(u_ideas)

    return jtbd, cluster_design, ideas


def _save_marketing_artifacts(
    output_dir: Path,
    all_ideas: list,
    all_jtbd: list,
    all_s3: list,
    clusters: list,
    gemini,
    anthropic,
    all_usages: list,
    rag=None,
) -> tuple[Path, Path]:
    """콘텐츠 아이디어·브리프 HTML/JSON을 저장하고 (ideas_path, brief_path)를 반환한다."""
    import json as _json
    from llm_pipeline.outputs.content_ideas import render_html as ideas_html
    from llm_pipeline.outputs.content_brief import run_content_brief, render_html as brief_html
    from llm_pipeline.outputs.quality_check import run_quality_check

    d = datetime.now()
    _, iso_week, _ = d.isocalendar()
    week_label = f"{d.year}년 {iso_week}주차 ({d.month}/{d.day})"

    all_keywords = []
    for c in clusters:
        all_keywords.extend(c.keywords[:3])
    rag_context = ""
    if rag is not None:
        rag_context = rag.build_context("content_brief", all_keywords)

    brief, u_brief = run_content_brief(
        clusters, all_jtbd, gemini, anthropic, s3_list=all_s3 or None, rag_context=rag_context
    )
    all_usages.extend(u_brief)

    # 클러스터별 품질 검증 (실패 시 경고만 표시, 파이프라인 차단 없음)
    quality_list = []
    for ideas in all_ideas:
        try:
            quality, u_quality = run_quality_check(anthropic, ideas, brief)
            all_usages.extend(u_quality)
            quality_list.append(quality)
            logger.info(
                "[quality] cluster=%s hallucination_risk=%d aida_pas_avg=%.1f cost=$%.4f",
                ideas.cluster_name,
                quality.hallucination.overall_risk,
                quality.framework.avg_score,
                quality.total_cost_usd,
            )
        except Exception as exc:
            logger.warning("[quality] 검증 실패 (%s) — 배지 없이 계속", exc)
            quality_list.append(None)

    ideas_html_path = output_dir / "content_ideas_report.html"
    ideas_html_path.write_text(ideas_html(all_ideas, week_label, quality_list), encoding="utf-8")
    (output_dir / "content_ideas.json").write_text(
        _json.dumps([i.model_dump() for i in all_ideas], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("콘텐츠 아이디어 저장: %s", ideas_html_path)

    # 브리프 HTML에는 첫 번째 클러스터 quality를 대표로 표시
    representative_quality = next((q for q in quality_list if q is not None), None)
    brief_html_path = output_dir / "content_brief_report.html"
    brief_html_path.write_text(brief_html(brief, quality=representative_quality), encoding="utf-8")
    (output_dir / "content_brief.json").write_text(
        _json.dumps(brief.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("콘텐츠 브리프 저장: %s", brief_html_path)

    return ideas_html_path, brief_html_path


def run_marketing_outputs(
    report_path: Path | None = None,
    date: str | None = None,
    top_n: int = 3,
) -> dict:
    """마케팅 신규 산출물 생성 — run_all.py Step 10에서 호출.

    반환값: {
        "output_dir": Path,
        "content_ideas_html": Path,
        "content_brief_html": Path,
        "cost_summary": str,
    }
    """
    from llm_pipeline.clients.anthropic_client import AnthropicClient
    from llm_pipeline.clients.gemini_client import GeminiClient
    from llm_pipeline.schemas import ContentClusterOutput, JTBDOutput
    from llm_pipeline.rag.context_builder import RAGContextBuilder

    anthropic = AnthropicClient()
    gemini = GeminiClient()
    rag = RAGContextBuilder()

    run_date = date or datetime.now().strftime("%Y-%m-%d")
    output_dir = OUTPUT_ROOT / run_date
    output_dir.mkdir(parents=True, exist_ok=True)

    clusters, prefilled_jtbd = _resolve_clusters(report_path, top_n)
    logger.info("마케팅 출력 — 클러스터 %d개 처리 시작", len(clusters))

    inter_dir = output_dir / "intermediate"
    inter_dir.mkdir(parents=True, exist_ok=True)

    all_ideas: list = []
    all_jtbd: list[JTBDOutput] = []
    all_s3: list[ContentClusterOutput] = []
    all_usages: list = []

    for i, cluster in enumerate(clusters):
        jtbd, cluster_design, ideas = _run_pipeline_for_cluster(
            cluster, prefilled_jtbd, i, inter_dir, anthropic, gemini, all_usages, rag
        )
        all_jtbd.append(jtbd)
        if cluster_design is not None:
            all_s3.append(cluster_design)
        all_ideas.append(ideas)

    ideas_html_path, brief_html_path = _save_marketing_artifacts(
        output_dir, all_ideas, all_jtbd, all_s3, clusters, gemini, anthropic, all_usages, rag
    )

    total_cost = sum(u.cost_usd for u in all_usages)
    _update_monthly_cost(total_cost)
    cost_summary = f"${total_cost:.4f}"
    logger.info("마케팅 출력 완료 — 총 비용 %s", cost_summary)

    return {
        "output_dir": output_dir,
        "content_ideas_html": ideas_html_path,
        "content_brief_html": brief_html_path,
        "cost_summary": cost_summary,
    }


if __name__ == "__main__":
    main()
