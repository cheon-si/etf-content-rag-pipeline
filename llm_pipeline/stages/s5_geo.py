"""Stage 5: GEO 최적화 (Gemini 2.5 Flash → Opus → Sonnet 폴백)."""
from __future__ import annotations

import logging

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.clients.gemini_client import GeminiClient
from llm_pipeline.prompts import PROMPT_S5
from llm_pipeline.schemas import ContentOutput, GEOOutput, TokenUsage

logger = logging.getLogger(__name__)


def run(
    content: ContentOutput,
    gemini: GeminiClient,
    anthropic: AnthropicClient,
) -> tuple[GEOOutput, TokenUsage]:
    """Gemini Search grounding으로 GEO 최적화. 실패 시 Opus → Sonnet 폴백."""
    prompt = PROMPT_S5.format(body_markdown=content.body_markdown)

    try:
        logger.info("[S5] Gemini Search grounding으로 GEO 최적화 시작")
        result, usage = gemini.complete(
            prompt=prompt,
            use_search_grounding=True,
            stage="s5_geo",
            response_schema=GEOOutput,
        )
        assert isinstance(result, GEOOutput)
        logger.info(
            "[S5] 완료 — ai_overview=%d naver_cue=%d",
            result.geo_score.ai_overview,
            result.geo_score.naver_cue,
        )
        return result, usage

    except RuntimeError as exc:
        logger.warning("[S5] Gemini 실패 — Opus → Sonnet 폴백: %s", exc)

    result, usage = anthropic.complete_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        stage="s5_geo_fallback_opus",
        response_schema=GEOOutput,
    )
    assert isinstance(result, GEOOutput)
    logger.info(
        "[S5] 폴백 완료 — ai_overview=%d naver_cue=%d",
        result.geo_score.ai_overview,
        result.geo_score.naver_cue,
    )
    return result, usage
