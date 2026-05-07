"""Stage 2 단위 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.schemas import ClusterInput, IntentOutput, JTBDOutput, TokenUsage
from llm_pipeline.stages import s2_jtbd

JTBD_JSON = json.dumps({
    "main_job": "ETF 포트폴리오로 안정적 노후 자산을 구성한다",
    "functional_needs": ["저비용 ETF 추천", "분산 투자 방법", "세금 효율"],
    "emotional_needs": ["투자 불안 해소", "자신감 획득"],
    "social_needs": ["가족에게 현명한 투자자로 인정"],
    "hire_context": "퇴직 5년 전 투자자가 연금 외 ETF 포트폴리오를 처음 구성할 때",
})


@pytest.fixture
def sample_intent() -> IntentOutput:
    return IntentOutput(
        intent_type="Informational",
        confidence=0.9,
        reasoning="투자자가 기초 정보를 찾고 있습니다.",
    )


def _make_client(response_json: str):
    usage = TokenUsage(model="claude-opus-4-7", stage="s2_jtbd",
                       input_tokens=500, output_tokens=800, cost_usd=0.02)
    client = MagicMock()
    client.complete_with_fallback.return_value = (JTBDOutput.model_validate_json(response_json), usage)
    return client


class TestS2JTBD:
    def test_returns_jtbd_output(self, sample_cluster, sample_intent):
        client = _make_client(JTBD_JSON)
        result, usage = s2_jtbd.run(sample_cluster, sample_intent, client)

        assert isinstance(result, JTBDOutput)
        assert result.main_job

    def test_has_all_need_categories(self, sample_cluster, sample_intent):
        client = _make_client(JTBD_JSON)
        result, _ = s2_jtbd.run(sample_cluster, sample_intent, client)

        assert len(result.functional_needs) >= 1
        assert len(result.emotional_needs) >= 1
        assert len(result.social_needs) >= 1
        assert result.hire_context

    def test_uses_complete_with_fallback(self, sample_cluster, sample_intent):
        client = _make_client(JTBD_JSON)
        s2_jtbd.run(sample_cluster, sample_intent, client)

        client.complete_with_fallback.assert_called_once()

    def test_intent_context_in_prompt(self, sample_cluster, sample_intent):
        client = _make_client(JTBD_JSON)
        s2_jtbd.run(sample_cluster, sample_intent, client)

        call_kwargs = client.complete_with_fallback.call_args.kwargs
        messages = call_kwargs.get("messages") or client.complete_with_fallback.call_args.args[0]
        prompt_text = messages[0]["content"]
        assert "Informational" in prompt_text
