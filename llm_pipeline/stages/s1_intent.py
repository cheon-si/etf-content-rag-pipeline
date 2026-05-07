"""Stage 1: Search Intent 분류 (claude-sonnet-4-6)."""
from __future__ import annotations

import logging

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.config import ANTHROPIC_SONNET
from llm_pipeline.prompts import PROMPT_S1
from llm_pipeline.schemas import ClusterInput, IntentOutput, TokenUsage

logger = logging.getLogger(__name__)


def run(
    cluster: ClusterInput,
    client: AnthropicClient,
) -> tuple[IntentOutput, TokenUsage]:
    """클러스터 키워드로 Search Intent를 분류한다."""
    prompt = PROMPT_S1.format(
        cluster_name=cluster.cluster_name,
        keywords=", ".join(cluster.keywords),
    )
    logger.info("[S1] 클러스터 '%s' Intent 분류 시작", cluster.cluster_name)

    result, usage = client.complete(
        model=ANTHROPIC_SONNET,
        messages=[{"role": "user", "content": prompt}],
        stage="s1_intent",
        response_schema=IntentOutput,
    )
    assert isinstance(result, IntentOutput)
    logger.info("[S1] 완료 — intent=%s confidence=%.2f", result.intent_type, result.confidence)
    return result, usage
