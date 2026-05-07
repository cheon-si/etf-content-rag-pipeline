"""트렌드 기반 콘텐츠 브리프 생성기 — Gemini(검색) + Opus(구조화)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.clients.gemini_client import GeminiClient
from llm_pipeline.config import ANTHROPIC_OPUS, ANTHROPIC_SONNET
from llm_pipeline.prompts import PROMPT_CONTENT_BRIEF_SEARCH, PROMPT_CONTENT_BRIEF_STRUCTURE
from llm_pipeline.schemas import (
    ClusterInput,
    ContentBriefOutput,
    ContentClusterOutput,
    JTBDOutput,
    QualityResult,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def _get_week_label(date: datetime | None = None) -> str:
    """ISO 주차 레이블 반환. 예: '2026년 17주차 (4/22)'"""
    d = date or datetime.now()
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}년 {iso_week}주차 ({d.month}/{d.day})"


def run_content_brief(
    clusters: list[ClusterInput],
    jtbd_list: list[JTBDOutput],
    gemini: GeminiClient,
    anthropic: AnthropicClient,
    s3_list: list[ContentClusterOutput] | None = None,
    rag_context: str = "",
) -> tuple[ContentBriefOutput, list[TokenUsage]]:
    """이번 주 ETF 콘텐츠 브리프 생성.

    Step 1: Gemini (search grounding) → 시장 트렌드 조사
    Step 2: Anthropic Opus → 트렌드 + JTBD + S3 competitor_gaps → 구조화된 브리프
    """
    usages: list[TokenUsage] = []
    week_label = _get_week_label()
    now = datetime.now()
    today = now.strftime("%Y년 %m월 %d일")
    today_year = now.year

    # 클러스터 요약 텍스트
    cluster_summary = "\n".join(
        f"- {c.cluster_name}: {', '.join(c.keywords[:6])}" for c in clusters
    )

    # JTBD 요약 텍스트
    jtbd_summary = "\n".join(
        f"- {j.main_job} (hire_context: {j.hire_context[:80]}...)"
        for j in jtbd_list
    ) if jtbd_list else "(JTBD 분석 없음)"

    # S3 경쟁사 공백 요약 텍스트
    if s3_list:
        competitor_gaps_summary = "\n".join(
            f"- [{s3.pillar_title}] " + " / ".join(s3.competitor_gaps)
            for s3 in s3_list
        )
    else:
        competitor_gaps_summary = "(S3 경쟁사 분석 없음)"

    # Step 1: Gemini 시장 트렌드 조사
    market_trends = _fetch_market_trends(
        cluster_summary=cluster_summary,
        gemini=gemini,
        usages=usages,
    )

    # Step 2: Opus 구조화
    brief = _structure_brief(
        today=today,
        today_year=today_year,
        week_label=week_label,
        cluster_summary=cluster_summary,
        jtbd_summary=jtbd_summary,
        competitor_gaps_summary=competitor_gaps_summary,
        market_trends=market_trends,
        anthropic=anthropic,
        usages=usages,
        rag_context=rag_context,
    )

    return brief, usages


def _fetch_market_trends(
    cluster_summary: str,
    gemini: GeminiClient,
    usages: list[TokenUsage],
) -> str:
    """Gemini search grounding으로 이번 주 ETF 시장 트렌드를 조사한다."""
    logger.info("[ContentBrief] Gemini 시장 트렌드 조사 시작")
    prompt = PROMPT_CONTENT_BRIEF_SEARCH.format(cluster_summary=cluster_summary)
    try:
        result, usage = gemini.complete(
            prompt=prompt,
            use_search_grounding=True,
            stage="content_brief_search",
        )
        usages.append(usage)
        logger.info("[ContentBrief] Gemini 트렌드 조사 완료")
        return str(result)
    except Exception as exc:
        logger.warning("[ContentBrief] Gemini 트렌드 조사 실패: %s — 클러스터 키워드로 대체", exc)
        return f"시장 트렌드 조사 실패. 클러스터 정보 기반으로 분석:\n{cluster_summary}"


def _structure_brief(
    today: str,
    today_year: int,
    week_label: str,
    cluster_summary: str,
    jtbd_summary: str,
    competitor_gaps_summary: str,
    market_trends: str,
    anthropic: AnthropicClient,
    usages: list[TokenUsage],
    rag_context: str = "",
) -> ContentBriefOutput:
    """Opus를 사용해 트렌드 데이터를 구조화된 브리프로 변환한다."""
    logger.info("[ContentBrief] Opus 브리프 구조화 시작")
    prompt = PROMPT_CONTENT_BRIEF_STRUCTURE.format(
        today=today,
        today_year=today_year,
        week_label=week_label,
        cluster_summary=cluster_summary,
        jtbd_summary=jtbd_summary,
        competitor_gaps_summary=competitor_gaps_summary,
        market_trends=market_trends,
        rag_context=rag_context,
    )
    try:
        result, usage = anthropic.complete(
            model=ANTHROPIC_OPUS,
            messages=[{"role": "user", "content": prompt}],
            stage="content_brief_structure",
            response_schema=ContentBriefOutput,
            max_tokens=4096,
        )
    except RuntimeError:
        logger.warning("[ContentBrief] Opus 실패 — Sonnet 폴백")
        result, usage = anthropic.complete(
            model=ANTHROPIC_SONNET,
            messages=[{"role": "user", "content": prompt}],
            stage="content_brief_structure_fallback",
            response_schema=ContentBriefOutput,
            max_tokens=4096,
        )

    usages.append(usage)
    assert isinstance(result, ContentBriefOutput)
    logger.info("[ContentBrief] 브리프 구조화 완료 — 시그널 %d개", len(result.top_signals))
    return result


def render_html(brief: ContentBriefOutput, quality: QualityResult | None = None) -> str:
    """ContentBriefOutput을 이메일 본문 겸 팀 공유용 HTML로 렌더링한다."""
    direction_colors = {
        "급상승": ("#d32f2f", "🔴"),
        "상승":   ("#F36B21", "🟠"),
        "유지":   ("#1565c0", "🔵"),
        "하락":   ("#555",    "⚫"),
    }

    signals_html = ""
    for i, sig in enumerate(brief.top_signals, 1):
        color, emoji = direction_colors.get(sig.trend_direction, ("#333", "⚪"))
        signals_html += f"""
        <tr>
          <td style="padding:12px;font-weight:700;color:#F36B21;width:28px;
                     vertical-align:top;font-size:1.2em;">{i}</td>
          <td style="padding:12px;border-bottom:1px solid #e8e8e8;">
            <div style="font-weight:700;color:#222;margin-bottom:4px;">
              {sig.topic}
              <span style="margin-left:8px;padding:2px 8px;border-radius:12px;
                           font-size:0.8em;background:{color}20;color:{color};
                           font-weight:700;">{emoji} {sig.trend_direction}</span>
            </div>
            <div style="color:#555;font-size:0.9em;margin-bottom:6px;">
              📊 {sig.evidence}
            </div>
            <div style="background:#fff3e0;padding:8px 12px;border-radius:4px;
                        color:#e65100;font-size:0.9em;font-style:italic;">
              💭 독자 질문: "{sig.jtbd_question}"
            </div>
          </td>
        </tr>"""

    formats_html = "".join(
        f'<span style="display:inline-block;margin:4px;padding:6px 14px;'
        f'border-radius:16px;background:#F36B21;color:white;font-size:0.9em;">'
        f'{fmt}</span>'
        for fmt in brief.recommended_formats
    )

    quality_section = ""
    if quality is not None:
        from llm_pipeline.outputs.quality_check import badge_class
        avg = quality.framework.avg_score
        cls = badge_class(avg)
        high_risk = [c for c in quality.hallucination.claims if not c.source_tag_present and c.risk >= 70]
        warn_items = "".join(
            f'<li>"{c.text}" — {c.reason}</li>'
            for c in high_risk[:5]
        )
        warn_block = (
            f'<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:4px;'
            f'padding:8px 12px;margin-top:8px;font-size:0.9em;color:#991b1b;">'
            f'<strong>⚠️ 확인 필요 주장 {len(high_risk)}건</strong>'
            f'<ul style="margin:4px 0 0;padding-left:16px;">{warn_items}</ul></div>'
        ) if high_risk else ""
        quality_section = f"""
  <div class="section-title">🔍 콘텐츠 품질 검증</div>
  <div class="box" style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;">
    <div>
      <span style="font-size:0.85em;color:#888;">AIDA/PAS 준수율</span><br>
      <span style="display:inline-block;padding:4px 14px;border-radius:12px;font-weight:700;font-size:1.1em;
                   background:{'#16a34a' if cls=='badge-green' else '#d97706' if cls=='badge-yellow' else '#dc2626'};
                   color:#fff;margin-top:4px;">품질 {avg:.1f} / 10</span>
    </div>
  </div>
  {warn_block}"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ETF 콘텐츠 브리프 — {brief.week_label}</title>
  <style>
    body {{font-family:'Noto Sans KR',sans-serif;max-width:800px;
           margin:0 auto;padding:24px;background:#f5f5f5;color:#222;}}
    h1 {{color:#F36B21;border-bottom:3px solid #F36B21;padding-bottom:10px;}}
    table {{width:100%;border-collapse:collapse;background:white;
            border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1);}}
    .section-title {{color:#F36B21;font-weight:700;font-size:1.05em;margin:20px 0 10px;}}
    .box {{background:white;border-radius:8px;padding:16px 20px;
           box-shadow:0 1px 4px rgba(0,0,0,.1);margin-bottom:16px;}}
  </style>
</head>
<body>
  <h1>📋 ETF 마케팅 콘텐츠 브리프</h1>
  <p style="color:#888;margin-top:-8px;">
    {brief.week_label} · Acme Securities, Product Solutions Team
  </p>

  <div class="box" style="background:#fff8f4;border-left:4px solid #F36B21;">
    <span style="font-size:0.85em;font-weight:700;color:#F36B21;">⚡ 긴급성</span>
    <p style="margin:6px 0 0;color:#333;">{brief.urgency_reason}</p>
  </div>

  <div class="section-title">📈 이번 주 트렌드 시그널 Top 5</div>
  <table>
    <tbody>{signals_html}</tbody>
  </table>

  <div class="section-title">🗓 콘텐츠 방향</div>
  <div class="box">
    <p style="margin:0;line-height:1.7;">{brief.content_direction}</p>
  </div>

  <div class="section-title">✅ 추천 콘텐츠 형식</div>
  <div class="box">
    {formats_html}
  </div>

  {quality_section}

  <p style="color:#aaa;font-size:0.8em;margin-top:24px;text-align:center;">
    AI 생성 콘텐츠 브리프 · 최종 판단은 마케팅팀 담당자가 수행
  </p>
</body>
</html>"""
