"""Stage 3 단위 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.schemas import (
    ContentClusterOutput,
    IntentOutput,
    JTBDOutput,
    TokenUsage,
)
from llm_pipeline.stages import s3_cluster

CLUSTER_JSON = json.dumps({
    "pillar_title": "2025 AI ETF 완벽 가이드: 초보도 수익 내는 투자 전략",
    "pillar_angle": "AI 산업 성장의 핵심 수혜주를 ETF로 분산 투자하는 방법",
    "sub_topics": [
        {"title": "AI ETF란 무엇인가", "angle": "개념 정의", "keywords": ["AI ETF", "정의"]},
        {"title": "국내 AI ETF 비교", "angle": "상품 비교", "keywords": ["TIGER", "KODEX"]},
        {"title": "글로벌 AI ETF 비교", "angle": "QQQ vs AIQ", "keywords": ["QQQ", "AIQ"]},
        {"title": "AI ETF 리밸런싱 전략", "angle": "운용 전략", "keywords": ["리밸런싱"]},
        {"title": "AI ETF 세금 가이드", "angle": "절세 방법", "keywords": ["세금", "절세"]},
    ],
    "competitor_gaps": ["실전 매매 방법 부족", "세금 정보 없음", "리스크 설명 없음"],
})


@pytest.fixture
def sample_intent() -> IntentOutput:
    return IntentOutput(intent_type="Informational", confidence=0.9, reasoning="기초 정보 탐색")


@pytest.fixture
def sample_jtbd() -> JTBDOutput:
    return JTBDOutput(
        main_job="AI ETF로 포트폴리오 수익률을 높인다",
        functional_needs=["ETF 선택 방법", "비용 비교"],
        emotional_needs=["투자 불안 해소"],
        social_needs=["현명한 투자자로 인정"],
        hire_context="AI 붐을 놓치기 싫은 30대 직장인",
    )


def _make_anthropic_client(response_json: str):
    usage = TokenUsage(model="claude-opus-4-7", stage="s3_cluster_design",
                       input_tokens=600, output_tokens=900, cost_usd=0.03)
    client = MagicMock()
    client.complete_with_fallback.return_value = (
        ContentClusterOutput.model_validate_json(response_json), usage
    )
    return client


def _make_gemini_client(fail: bool = False):
    usage = TokenUsage(model="gemini-2.5-flash", stage="s3_gemini_research",
                       input_tokens=300, output_tokens=500, cost_usd=0.005)
    client = MagicMock()
    if fail:
        client.complete.side_effect = RuntimeError("Gemini fail")
    else:
        client.complete.return_value = ("상위 콘텐츠 패턴: ...", usage)
    return client


class TestS3Cluster:
    def test_returns_content_cluster_output(self, sample_cluster, sample_intent, sample_jtbd):
        anthropic = _make_anthropic_client(CLUSTER_JSON)
        gemini = _make_gemini_client()
        result, usages = s3_cluster.run(sample_cluster, sample_intent, sample_jtbd, anthropic, gemini)

        assert isinstance(result, ContentClusterOutput)
        assert result.pillar_title
        assert len(result.sub_topics) == 5

    def test_returns_multiple_usages(self, sample_cluster, sample_intent, sample_jtbd):
        anthropic = _make_anthropic_client(CLUSTER_JSON)
        gemini = _make_gemini_client()
        _, usages = s3_cluster.run(sample_cluster, sample_intent, sample_jtbd, anthropic, gemini)

        # Gemini 1개 + Anthropic 1개
        assert len(usages) == 2

    def test_gemini_failure_continues_without_research(self, sample_cluster, sample_intent, sample_jtbd):
        anthropic = _make_anthropic_client(CLUSTER_JSON)
        gemini = _make_gemini_client(fail=True)

        # Gemini 실패해도 전체 파이프라인 완료
        result, usages = s3_cluster.run(sample_cluster, sample_intent, sample_jtbd, anthropic, gemini)
        assert isinstance(result, ContentClusterOutput)
        # Gemini 호출 실패 시 usage 없음, Anthropic usage만
        assert len(usages) == 1

    def test_opus_fallback_calls_complete_with_fallback(self, sample_cluster, sample_intent, sample_jtbd):
        anthropic = _make_anthropic_client(CLUSTER_JSON)
        gemini = _make_gemini_client()

        result, _ = s3_cluster.run(sample_cluster, sample_intent, sample_jtbd, anthropic, gemini)
        assert isinstance(result, ContentClusterOutput)
        anthropic.complete_with_fallback.assert_called_once()

    def test_competitor_gaps_populated(self, sample_cluster, sample_intent, sample_jtbd):
        anthropic = _make_anthropic_client(CLUSTER_JSON)
        gemini = _make_gemini_client()
        result, _ = s3_cluster.run(sample_cluster, sample_intent, sample_jtbd, anthropic, gemini)

        assert len(result.competitor_gaps) >= 1
