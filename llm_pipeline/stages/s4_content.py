"""Stage 4: AIDA/PAS 본문 생성 (3-iteration: 초안 → 톤 조정 → 팩트 검증)."""
from __future__ import annotations

import logging

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.prompts import PROMPT_S4_DRAFT, PROMPT_S4_FACTCHECK, PROMPT_S4_TONE
from llm_pipeline.schemas import (
    ClusterInput,
    ContentClusterOutput,
    ContentOutput,
    JTBDOutput,
    TokenUsage,
)

logger = logging.getLogger(__name__)


def run(
    cluster: ClusterInput,
    jtbd: JTBDOutput,
    cluster_design: ContentClusterOutput,
    client: AnthropicClient,
) -> tuple[ContentOutput, list[TokenUsage]]:
    """3-iteration으로 블로그 원고를 생성한다."""
    usages: list[TokenUsage] = []

    draft, usage1 = _run_draft(cluster, jtbd, cluster_design, client)
    usages.append(usage1)
    logger.info("[S4] 1차 초안 완료 — title: %s", draft.title[:50])

    toned_body, usage2 = _run_tone_adjustment(draft.body_markdown, client)
    usages.append(usage2)
    logger.info("[S4] 2차 톤 조정 완료")

    final_body, usage3 = _run_fact_check(toned_body, client)
    usages.append(usage3)
    logger.info("[S4] 3차 팩트 검증 완료")

    result = ContentOutput(
        title=draft.title,
        slug=draft.slug,
        body_markdown=final_body,
        aida_structure=draft.aida_structure,
        pas_structure=draft.pas_structure,
    )
    return result, usages


def _run_draft(
    cluster: ClusterInput,
    jtbd: JTBDOutput,
    cluster_design: ContentClusterOutput,
    client: AnthropicClient,
) -> tuple[ContentOutput, TokenUsage]:
    prompt = PROMPT_S4_DRAFT.format(
        cluster_name=cluster.cluster_name,
        pillar_title=cluster_design.pillar_title,
        pillar_angle=cluster_design.pillar_angle,
        main_job=jtbd.main_job,
        functional_needs=", ".join(jtbd.functional_needs),
        hire_context=jtbd.hire_context,
    )
    result, usage = client.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s4_draft",
        response_schema=ContentOutput,
    )
    assert isinstance(result, ContentOutput)
    return result, usage


def _run_tone_adjustment(body: str, client: AnthropicClient) -> tuple[str, TokenUsage]:
    prompt = PROMPT_S4_TONE.format(draft_body=body)
    result, usage = client.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s4_tone",
    )
    assert isinstance(result, str)
    return result.strip(), usage


def _run_fact_check(body: str, client: AnthropicClient) -> tuple[str, TokenUsage]:
    prompt = PROMPT_S4_FACTCHECK.format(toned_body=body)
    result, usage = client.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s4_factcheck",
    )
    assert isinstance(result, str)
    return result.strip(), usage
