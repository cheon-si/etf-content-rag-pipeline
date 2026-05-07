"""Stage 1 단위 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.schemas import ClusterInput, IntentOutput, TokenUsage
from llm_pipeline.stages import s1_intent

INTENT_JSON = json.dumps({
    "intent_type": "Informational",
    "confidence": 0.9,
    "reasoning": "투자자들이 AI ETF 기초 정보를 검색하고 있습니다.",
})


def _make_client(response_text: str, input_tok: int = 100, output_tok: int = 200):
    usage = TokenUsage(model="claude-sonnet-4-6", stage="s1_intent",
                       input_tokens=input_tok, output_tokens=output_tok,
                       cost_usd=0.001)
    client = MagicMock()
    client.complete.return_value = (IntentOutput.model_validate_json(response_text), usage)
    return client


class TestS1Intent:
    def test_returns_intent_output(self, sample_cluster):
        client = _make_client(INTENT_JSON)
        result, usage = s1_intent.run(sample_cluster, client)

        assert isinstance(result, IntentOutput)
        assert result.intent_type in ("Informational", "Commercial", "Transactional")

    def test_correct_intent_type(self, sample_cluster):
        client = _make_client(INTENT_JSON)
        result, _ = s1_intent.run(sample_cluster, client)
        assert result.intent_type == "Informational"

    def test_returns_usage(self, sample_cluster):
        client = _make_client(INTENT_JSON)
        _, usage = s1_intent.run(sample_cluster, client)
        assert isinstance(usage, TokenUsage)
        assert usage.stage == "s1_intent"

    def test_prompt_contains_cluster_name(self, sample_cluster):
        client = _make_client(INTENT_JSON)
        s1_intent.run(sample_cluster, client)

        call_args = client.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        prompt_text = messages[0]["content"]
        assert sample_cluster.cluster_name in prompt_text

    def test_prompt_contains_keywords(self, sample_cluster):
        client = _make_client(INTENT_JSON)
        s1_intent.run(sample_cluster, client)

        call_args = client.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        prompt_text = messages[0]["content"]
        assert "AI" in prompt_text

    def test_uses_sonnet_model(self, sample_cluster):
        from llm_pipeline.config import ANTHROPIC_SONNET
        client = _make_client(INTENT_JSON)
        s1_intent.run(sample_cluster, client)

        call_args = client.complete.call_args
        model = call_args.kwargs.get("model") or call_args.args[0]
        assert model == ANTHROPIC_SONNET
