"""ETF 콘텐츠 아이디어 생성기 — 카드뉴스·SNS·블로그 제목 자동 생성."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.config import ANTHROPIC_SONNET
from llm_pipeline.prompts import PROMPT_CONTENT_IDEAS
from llm_pipeline.schemas import ClusterInput, ContentClusterOutput, ContentIdeasOutput, JTBDOutput, QualityResult, TokenUsage

logger = logging.getLogger(__name__)

_BRACKET_TAG_RE = re.compile(r"\[.*?\]")


def _clean_cluster_name(name: str) -> str:
    """[노이즈], [광고] 등 내부 태그를 클러스터명에서 제거한다."""
    return _BRACKET_TAG_RE.sub("", name).strip()


def run_content_ideas(
    cluster: ClusterInput,
    jtbd: JTBDOutput,
    anthropic: AnthropicClient,
    cluster_design: ContentClusterOutput | None = None,
    rag_context: str = "",
) -> tuple[ContentIdeasOutput, TokenUsage]:
    """S2 JTBD + S3 경쟁사 공백 분석 + 클러스터 키워드 → 콘텐츠 아이디어 생성.

    모델: claude-sonnet-4-6 (비용 효율)
    """
    logger.info("[ContentIdeas] 클러스터 '%s' 아이디어 생성 시작", cluster.cluster_name)

    pillar_angle = cluster_design.pillar_angle if cluster_design else "(S3 분석 없음)"
    competitor_gaps = (
        "; ".join(cluster_design.competitor_gaps) if cluster_design else "(S3 분석 없음)"
    )

    prompt = PROMPT_CONTENT_IDEAS.format(
        cluster_name=_clean_cluster_name(cluster.cluster_name),
        keywords=", ".join(cluster.keywords),
        keywords_json=json.dumps(cluster.keywords, ensure_ascii=False),
        main_job=jtbd.main_job,
        functional_needs=", ".join(jtbd.functional_needs),
        emotional_needs=", ".join(jtbd.emotional_needs),
        hire_context=jtbd.hire_context,
        pillar_angle=pillar_angle,
        competitor_gaps=competitor_gaps,
        today_year=datetime.now().year,
        rag_context=rag_context,
    )

    result, usage = anthropic.complete(
        model=ANTHROPIC_SONNET,
        messages=[{"role": "user", "content": prompt}],
        stage="content_ideas",
        response_schema=ContentIdeasOutput,
        max_tokens=4096,
    )
    assert isinstance(result, ContentIdeasOutput)

    logger.info(
        "[ContentIdeas] 완료 — 카드뉴스 %d개, 블로그 제목 %d개, SNS %d개",
        len(result.card_news_ideas),
        len(result.blog_titles),
        len(result.sns_messages),
    )
    return result, usage


def _render_quality_badge(quality: QualityResult | None) -> str:
    """QualityResult로 품질 배지 + 할루시네이션 경고 박스 HTML을 반환한다."""
    if quality is None:
        return ""

    from llm_pipeline.outputs.quality_check import badge_class

    avg = quality.framework.avg_score
    cls = badge_class(avg)

    badge_html = (
        f'<span class="quality-badge {cls}" title="AIDA/PAS 준수율">'
        f"품질 {avg:.1f}</span>"
    )

    warn_html = ""
    high_risk_claims = [c for c in quality.hallucination.claims if not c.source_tag_present and c.risk >= 70]
    if high_risk_claims:
        items = "".join(
            f'<li>"{c.text}" — {c.reason}</li>'
            for c in high_risk_claims[:5]
        )
        warn_html = f"""
        <div class="hallucination-warn">
          <strong>⚠️ 확인 필요 주장 {len(high_risk_claims)}건</strong>
          <ul>{items}</ul>
        </div>"""

    return badge_html + warn_html


def render_html(ideas_list: list[ContentIdeasOutput], date_label: str, quality_list: list[QualityResult | None] | None = None) -> str:
    """ContentIdeasOutput 목록을 팀 공유용 HTML로 렌더링한다."""
    cards_html = ""
    for idx, ideas in enumerate(ideas_list):
        quality = (quality_list[idx] if quality_list and idx < len(quality_list) else None)
        card_news_blocks = ""
        for cn in ideas.card_news_ideas:
            cards_html_items = "".join(
                f'<li style="padding:4px 0;">{t}</li>' for t in cn.card_titles
            )
            card_news_blocks += f"""
            <div style="background:#fff8f4;border-left:4px solid #F36B21;
                        padding:12px 16px;margin-bottom:12px;border-radius:4px;">
              <div style="font-weight:700;color:#F36B21;margin-bottom:6px;">
                📌 {cn.topic}
              </div>
              <ul style="margin:0;padding-left:18px;color:#333;">{cards_html_items}</ul>
              <div style="margin-top:8px;font-size:0.85em;color:#555;">
                💬 핵심 메시지: <em>{cn.key_message}</em>
              </div>
            </div>"""

        blog_items = "".join(
            f'<li style="padding:3px 0;">{t}</li>' for t in ideas.blog_titles
        )
        yt_items = "".join(
            f'<li style="padding:3px 0;">{t}</li>' for t in ideas.youtube_titles
        )
        sns_items = "".join(
            f'<li style="padding:3px 0;font-size:0.9em;">{m}</li>' for m in ideas.sns_messages
        )

        quality_html = _render_quality_badge(quality)
        cards_html += f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:20px;
                    margin-bottom:24px;background:#fafafa;">
          <div style="background:#F36B21;color:white;padding:10px 16px;
                      border-radius:6px;margin-bottom:16px;display:flex;
                      align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div>
              <span style="font-size:1.1em;font-weight:700;">
                {_clean_cluster_name(ideas.cluster_name)}
              </span>
              <span style="margin-left:12px;font-size:0.85em;opacity:0.9;">
                {", ".join(ideas.keywords[:5])}
              </span>
            </div>
            <div>{quality_html}</div>
          </div>

          <div style="background:#fff3e0;padding:10px 14px;border-radius:4px;
                      margin-bottom:16px;font-weight:600;color:#e65100;">
            🎯 핵심 보고 한 줄: {ideas.one_liner}
          </div>

          <h4 style="color:#F36B21;margin:12px 0 8px;">🃏 카드뉴스 아이디어</h4>
          {card_news_blocks}

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px;">
            <div>
              <h4 style="color:#333;margin:0 0 8px;">📝 블로그 제목</h4>
              <ul style="margin:0;padding-left:18px;color:#444;">{blog_items}</ul>
            </div>
            <div>
              <h4 style="color:#333;margin:0 0 8px;">🎬 유튜브 제목</h4>
              <ul style="margin:0;padding-left:18px;color:#444;">{yt_items}</ul>
            </div>
          </div>

          <h4 style="color:#333;margin:16px 0 8px;">📱 SNS 메시지 (인스타/스레드)</h4>
          <ul style="margin:0;padding-left:18px;color:#444;">{sns_items}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ETF 콘텐츠 아이디어 — {date_label}</title>
  <style>
    body {{font-family:'Noto Sans KR',sans-serif;max-width:900px;
           margin:0 auto;padding:24px;background:#f5f5f5;color:#222;}}
    h1 {{color:#F36B21;border-bottom:2px solid #F36B21;padding-bottom:8px;}}
    h2 {{color:#555;font-size:1em;font-weight:400;margin-top:-8px;}}
    .quality-badge {{display:inline-block;padding:3px 10px;border-radius:12px;
                     font-size:0.82em;font-weight:700;white-space:nowrap;}}
    .badge-green  {{background:#16a34a;color:#fff;}}
    .badge-yellow {{background:#d97706;color:#fff;}}
    .badge-red    {{background:#dc2626;color:#fff;}}
    .hallucination-warn {{background:#fef2f2;border:1px solid #fca5a5;
                          border-radius:4px;padding:8px 12px;margin-top:8px;
                          font-size:0.85em;color:#991b1b;}}
    .hallucination-warn ul {{margin:4px 0 0;padding-left:16px;}}
  </style>
</head>
<body>
  <h1>🎨 ETF 콘텐츠 아이디어</h1>
  <h2>{date_label} 기준 · Acme Securities, Product Solutions Team</h2>
  <p style="color:#888;font-size:0.85em;">
    ※ AI 생성 콘텐츠 아이디어 · 최종 콘텐츠 제작 전 검토 필요
  </p>
  {cards_html}
</body>
</html>"""
