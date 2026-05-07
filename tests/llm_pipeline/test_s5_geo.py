"""Stage 5 단위 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.schemas import (
    AIDAStructure,
    ContentOutput,
    GEOOutput,
    PASStructure,
    TokenUsage,
)
from llm_pipeline.stages import s5_geo

GEO_JSON = json.dumps({
    "optimized_markdown": "## ETF란\nETF는 상장지수펀드입니다.\n\n## FAQ\n**Q. ETF란?**\nA. 분산 투자 상품입니다.",
    "geo_score": {"ai_overview": 82, "naver_cue": 75},
    "improvements": ["단문화 완료", "FAQ 섹션 강화", "출처 위치 최적화"],
})


@pytest.fixture
def sample_content() -> ContentOutput:
    return ContentOutput(
        title="AI ETF 완벽 가이드",
        slug="ai-etf-guide",
        body_markdown="## 본문\n내용입니다.",
        aida_structure=AIDAStructure(
            attention="주목", interest="관심", desire="욕구", action="행동"
        ),
        pas_structure=PASStructure(
            problem="문제", agitation="심화", solution="해결"
        ),
    )


def _make_gemini(response_json: str, fail: bool = False):
    usage = TokenUsage(model="gemini-2.5-flash", stage="s5_geo",
                       input_tokens=400, output_tokens=600, cost_usd=0.006)
    client = MagicMock()
    if fail:
        client.complete.side_effect = RuntimeError("Gemini fail")
    else:
        client.complete.return_value = (GEOOutput.model_validate_json(response_json), usage)
    return client


def _make_anthropic(response_json: str):
    usage = TokenUsage(model="claude-opus-4-7", stage="s5_geo_fallback_opus",
                       input_tokens=400, output_tokens=600, cost_usd=0.02)
    client = MagicMock()
    client.complete_with_fallback.return_value = (GEOOutput.model_validate_json(response_json), usage)
    return client


class TestS5GEO:
    def test_returns_geo_output(self, sample_content):
        gemini = _make_gemini(GEO_JSON)
        anthropic = _make_anthropic(GEO_JSON)
        result, usage = s5_geo.run(sample_content, gemini, anthropic)

        assert isinstance(result, GEOOutput)
        assert result.optimized_markdown
        assert 0 <= result.geo_score.ai_overview <= 100
        assert 0 <= result.geo_score.naver_cue <= 100

    def test_three_improvements(self, sample_content):
        gemini = _make_gemini(GEO_JSON)
        anthropic = _make_anthropic(GEO_JSON)
        result, _ = s5_geo.run(sample_content, gemini, anthropic)

        assert len(result.improvements) >= 1

    def test_gemini_called_with_search_grounding(self, sample_content):
        gemini = _make_gemini(GEO_JSON)
        anthropic = _make_anthropic(GEO_JSON)
        s5_geo.run(sample_content, gemini, anthropic)

        call_kwargs = gemini.complete.call_args.kwargs
        assert call_kwargs.get("use_search_grounding") is True

    def test_fallback_to_anthropic_on_gemini_failure(self, sample_content):
        gemini = _make_gemini(GEO_JSON, fail=True)
        anthropic = _make_anthropic(GEO_JSON)
        result, _ = s5_geo.run(sample_content, gemini, anthropic)

        assert isinstance(result, GEOOutput)
        anthropic.complete_with_fallback.assert_called_once()
