"""Stage 3: Content Cluster 설계 (Gemini Search grounding → Opus 교차검증)."""
from __future__ import annotations

import logging

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.clients.gemini_client import GeminiClient
from llm_pipeline.prompts import PROMPT_S3_GEMINI, PROMPT_S3_OPUS
from llm_pipeline.schemas import (
    ClusterInput,
    ContentClusterOutput,
    IntentOutput,
    JTBDOutput,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def run(
    cluster: ClusterInput,
    intent: IntentOutput,
    jtbd: JTBDOutput,
    anthropic: AnthropicClient,
    gemini: GeminiClient,
) -> tuple[ContentClusterOutput, list[TokenUsage]]:
    """Gemini Search grounding으로 시장 조사 후 Opus로 Pillar-Sub 구조를 설계한다."""
    usages: list[TokenUsage] = []

    market_research = _run_gemini_research(cluster, jtbd, gemini, usages)
    result = _run_opus_design(cluster, intent, jtbd, market_research, anthropic, usages)

    logger.info("[S3] 완료 — pillar: %s", result.pillar_title[:50])
    return result, usages


def _run_gemini_research(
    cluster: ClusterInput,
    jtbd: JTBDOutput,
    gemini: GeminiClient,
    usages: list[TokenUsage],
) -> str:
    prompt = PROMPT_S3_GEMINI.format(
        cluster_name=cluster.cluster_name,
        keywords=", ".join(cluster.keywords),
        main_job=jtbd.main_job,
    )
    try:
        logger.info("[S3] Gemini Search grounding으로 시장 조사 시작")
        research_text, usage = gemini.complete(
            prompt=prompt,
            use_search_grounding=True,
            stage="s3_gemini_research",
        )
        usages.append(usage)
        assert isinstance(research_text, str)
        return research_text
    except RuntimeError as exc:
        logger.warning("[S3] Gemini 실패 — 시장 조사 생략: %s", exc)
        return "시장 조사 데이터 없음 (Gemini 호출 실패)"


def _run_opus_design(
    cluster: ClusterInput,
    intent: IntentOutput,
    jtbd: JTBDOutput,
    market_research: str,
    anthropic: AnthropicClient,
    usages: list[TokenUsage],
) -> ContentClusterOutput:
    prompt = PROMPT_S3_OPUS.format(
        cluster_name=cluster.cluster_name,
        keywords=", ".join(cluster.keywords),
        main_job=jtbd.main_job,
        functional_needs=", ".join(jtbd.functional_needs),
        intent_type=intent.intent_type,
        market_research=market_research,
    )
    result, usage = anthropic.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s3_cluster_design",
        response_schema=ContentClusterOutput,
    )
    usages.append(usage)
    assert isinstance(result, ContentClusterOutput)
    return result
