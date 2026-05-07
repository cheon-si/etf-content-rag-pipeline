"""Stage 2: JTBD 추론 (Opus → Sonnet 폴백)."""
from __future__ import annotations

import logging

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.prompts import PROMPT_S2
from llm_pipeline.schemas import ClusterInput, IntentOutput, JTBDOutput, TokenUsage

logger = logging.getLogger(__name__)


def run(
    cluster: ClusterInput,
    intent: IntentOutput,
    client: AnthropicClient,
) -> tuple[JTBDOutput, TokenUsage]:
    """JTBD 프레임워크로 투자자의 핵심 Job을 추론한다."""
    logger.info("[S2] 클러스터 '%s' JTBD 추론 시작", cluster.cluster_name)

    prompt = PROMPT_S2.format(
        cluster_name=cluster.cluster_name,
        keywords=", ".join(cluster.keywords),
        intent_type=intent.intent_type,
        intent_reasoning=intent.reasoning,
    )
    result, usage = client.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s2_jtbd",
        response_schema=JTBDOutput,
    )
    assert isinstance(result, JTBDOutput)
    logger.info("[S2] 완료 — main_job: %s", result.main_job[:50])
    return result, usage
