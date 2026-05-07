"""콘텐츠 품질 검증 — 할루시네이션 검증 + AIDA/PAS 프레임워크 준수율 채점."""
from __future__ import annotations

import logging
from typing import Literal

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.config import ANTHROPIC_SONNET
from llm_pipeline.prompts import PROMPT_AIDA_PAS_RUBRIC, PROMPT_HALLUCINATION_CHECK, QUALITY_THRESHOLDS
from llm_pipeline.schemas import (
    AidaPasReport,
    ContentBriefOutput,
    ContentIdeasOutput,
    HallucinationReport,
    QualityResult,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def badge_class(score: float) -> Literal["badge-green", "badge-yellow", "badge-red"]:
    """점수에 따라 배지 CSS 클래스를 반환한다."""
    if score >= QUALITY_THRESHOLDS["green"]:
        return "badge-green"
    if score >= QUALITY_THRESHOLDS["yellow"]:
        return "badge-yellow"
    return "badge-red"


def verify_hallucinations(
    client: AnthropicClient,
    ideas: ContentIdeasOutput,
    brief: ContentBriefOutput,
) -> tuple[HallucinationReport, TokenUsage]:
    """콘텐츠 아이디어와 브리프의 수치/상품명/법제 주장을 교차검증한다."""
    content_parts: list[str] = []

    # 카드뉴스 제목
    for cn in ideas.card_news_ideas:
        content_parts.append(f"[카드뉴스: {cn.topic}]")
        content_parts.extend(f"  - {t}" for t in cn.card_titles)
        content_parts.append(f"  핵심 메시지: {cn.key_message}")

    # 블로그·유튜브·SNS
    content_parts.append("[블로그 제목]")
    content_parts.extend(f"  - {t}" for t in ideas.blog_titles)
    content_parts.append("[유튜브 제목]")
    content_parts.extend(f"  - {t}" for t in ideas.youtube_titles)
    content_parts.append("[SNS 메시지]")
    content_parts.extend(f"  - {m}" for m in ideas.sns_messages)
    content_parts.append(f"[한 줄 요약] {ideas.one_liner}")

    # 브리프 시그널
    content_parts.append("[트렌드 시그널]")
    for sig in brief.top_signals:
        content_parts.append(f"  - {sig.topic}: {sig.evidence}")

    content_text = "\n".join(content_parts)

    prompt = PROMPT_HALLUCINATION_CHECK.format(content_text=content_text)
    result, usage = client.complete(
        model=ANTHROPIC_SONNET,
        messages=[{"role": "user", "content": prompt}],
        stage="quality_hallucination",
        response_schema=HallucinationReport,
        max_tokens=4096,
    )
    assert isinstance(result, HallucinationReport)

    logger.info(
        "[Quality] 할루시네이션 검증 완료 — 의심 주장 %d건, 위험도 %d",
        len(result.claims),
        result.overall_risk,
    )
    return result, usage


def score_aida_pas(
    client: AnthropicClient,
    ideas: ContentIdeasOutput,
) -> tuple[AidaPasReport, TokenUsage]:
    """카드뉴스·블로그·SNS 제목·후크의 AIDA/PAS 준수율을 일괄 채점한다."""
    items: list[str] = []

    for i, cn in enumerate(ideas.card_news_ideas, 1):
        items.append(f"카드뉴스{i} [{cn.topic}]:")
        items.append(f"  카드 제목: {', '.join(cn.card_titles[:3])}")
        items.append(f"  핵심 메시지: {cn.key_message}")

    for i, title in enumerate(ideas.blog_titles, 1):
        items.append(f"블로그{i}: {title}")

    for i, msg in enumerate(ideas.sns_messages, 1):
        items.append(f"SNS{i}: {msg}")

    content_items = "\n".join(items)

    prompt = PROMPT_AIDA_PAS_RUBRIC.format(content_items=content_items)
    result, usage = client.complete(
        model=ANTHROPIC_SONNET,
        messages=[{"role": "user", "content": prompt}],
        stage="quality_aida_pas",
        response_schema=AidaPasReport,
        max_tokens=4096,
    )
    assert isinstance(result, AidaPasReport)

    logger.info(
        "[Quality] AIDA/PAS 채점 완료 — 평균 %.1f점 (%d개 아이디어)",
        result.avg_score,
        len(result.scores),
    )
    return result, usage


def run_quality_check(
    client: AnthropicClient,
    ideas: ContentIdeasOutput,
    brief: ContentBriefOutput,
) -> tuple[QualityResult, list[TokenUsage]]:
    """할루시네이션 검증 + AIDA/PAS 채점을 순차 실행하고 QualityResult를 반환한다."""
    hallucination_report, u1 = verify_hallucinations(client, ideas, brief)
    aida_pas_report, u2 = score_aida_pas(client, ideas)

    total_cost = u1.cost_usd + u2.cost_usd
    quality = QualityResult(
        hallucination=hallucination_report,
        framework=aida_pas_report,
        total_cost_usd=total_cost,
    )

    logger.info(
        "[Quality] 클러스터 '%s' 검증 완료 — 할루시네이션 위험 %d, AIDA/PAS 평균 %.1f, 비용 $%.4f",
        ideas.cluster_name,
        hallucination_report.overall_risk,
        aida_pas_report.avg_score,
        total_cost,
    )
    return quality, [u1, u2]
