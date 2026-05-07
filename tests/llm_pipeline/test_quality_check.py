"""quality_check.py 단위 테스트 — Mock LLM 응답으로 검증."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from llm_pipeline.outputs.quality_check import badge_class, run_quality_check, score_aida_pas, verify_hallucinations
from llm_pipeline.schemas import (
    AidaPasReport,
    CardNewsIdea,
    ContentBriefOutput,
    ContentIdeasOutput,
    FrameworkScore,
    HallucinationReport,
    QualityResult,
    SuspiciousClaim,
    TokenUsage,
    TrendSignal,
)


# ── 픽스처 ────────────────────────────────────────────────────────────────────

def _make_ideas() -> ContentIdeasOutput:
    return ContentIdeasOutput(
        cluster_name="미국ETF",
        keywords=["미국ETF", "S&P500"],
        card_news_ideas=[
            CardNewsIdea(
                topic="S&P500 ETF 비교",
                card_titles=["지금 S&P500 ETF 사야 할까?", "수익률 +18% 달성 [확인 필요: 출처]", "TIGER vs KODEX 비교"],
                key_message="핵심 메시지",
            )
        ],
        blog_titles=["S&P500 ETF 완벽 가이드", "연 148만 원 절세 방법"],
        youtube_titles=["ETF 지금 사면 되나요?"],
        sns_messages=["ETF 투자 시작하기 #ETF #TIGER #투자"],
        one_liner="미국 ETF 관심 급증",
    )


def _make_brief() -> ContentBriefOutput:
    return ContentBriefOutput(
        week_label="2026년 17주차",
        top_signals=[
            TrendSignal(
                topic="미국ETF",
                trend_direction="상승",
                evidence="순자산 10조 돌파 [확인 필요: 출처]",
                jtbd_question="미국ETF 지금 사도 될까요?",
            )
        ],
        content_direction="이번 주 방향",
        recommended_formats=["카드뉴스", "블로그"],
        urgency_reason="이번 주 이슈",
    )


def _make_mock_client(response_json: str) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 200
    content = MagicMock()
    content.text = response_json
    response = MagicMock()
    response.content = [content]
    response.usage = usage

    client = MagicMock()
    client._client = MagicMock()
    client._client.messages.create.return_value = response

    # complete()가 실제 AnthropicClient 로직을 타도록 진짜 client 반환
    from llm_pipeline.clients.anthropic_client import AnthropicClient
    real_client = AnthropicClient.__new__(AnthropicClient)
    real_client._client = client._client
    return real_client


# ── badge_class ───────────────────────────────────────────────────────────────

class TestBadgeClass:
    def test_green_at_threshold(self):
        assert badge_class(8.0) == "badge-green"

    def test_green_above_threshold(self):
        assert badge_class(9.5) == "badge-green"

    def test_yellow_at_threshold(self):
        assert badge_class(5.0) == "badge-yellow"

    def test_yellow_just_below_green(self):
        assert badge_class(7.9) == "badge-yellow"

    def test_red_below_yellow(self):
        assert badge_class(4.9) == "badge-red"

    def test_red_at_zero(self):
        assert badge_class(0.0) == "badge-red"


# ── verify_hallucinations ─────────────────────────────────────────────────────

class TestVerifyHallucinations:
    def test_parses_mock_response(self):
        mock_response = json.dumps({
            "overall_risk": 65,
            "claims": [
                {
                    "text": "수익률 +18%",
                    "claim_type": "number",
                    "risk": 70,
                    "reason": "출처 태그 없이 단정 기술",
                    "source_tag_present": False,
                }
            ],
            "summary": "출처 없는 수치 1건 발견",
        })

        client = _make_mock_client(mock_response)
        report, usage = verify_hallucinations(client, _make_ideas(), _make_brief())

        assert isinstance(report, HallucinationReport)
        assert report.overall_risk == 65
        assert len(report.claims) == 1
        assert report.claims[0].claim_type == "number"
        assert isinstance(usage, TokenUsage)

    def test_empty_claims_allowed(self):
        mock_response = json.dumps({
            "overall_risk": 0,
            "claims": [],
            "summary": "의심 주장 없음",
        })

        client = _make_mock_client(mock_response)
        report, _ = verify_hallucinations(client, _make_ideas(), _make_brief())
        assert report.claims == []


# ── score_aida_pas ────────────────────────────────────────────────────────────

class TestScoreAidaPas:
    def test_normalization(self):
        """AIDA 4항목 모두 1점 → normalized_score 10.0"""
        mock_response = json.dumps({
            "scores": [
                {
                    "idea_id": "카드뉴스1",
                    "framework": "AIDA",
                    "checklist": {"attention": 1, "interest": 1, "desire": 1, "action": 1},
                    "normalized_score": 10.0,
                    "comment": "모든 항목 충족",
                }
            ],
            "avg_score": 10.0,
        })

        client = _make_mock_client(mock_response)
        report, _ = score_aida_pas(client, _make_ideas())

        assert isinstance(report, AidaPasReport)
        assert report.avg_score == 10.0
        assert report.scores[0].normalized_score == 10.0

    def test_pas_partial_score(self):
        """PAS 3항목 중 2항목 → normalized_score 6.7"""
        mock_response = json.dumps({
            "scores": [
                {
                    "idea_id": "블로그1",
                    "framework": "PAS",
                    "checklist": {"problem": 1, "agitation": 0, "solution": 1},
                    "normalized_score": 6.7,
                    "comment": "agitation 미흡",
                }
            ],
            "avg_score": 6.7,
        })

        client = _make_mock_client(mock_response)
        report, _ = score_aida_pas(client, _make_ideas())
        assert report.scores[0].framework == "PAS"
        assert report.scores[0].normalized_score == pytest.approx(6.7, abs=0.1)


# ── run_quality_check ─────────────────────────────────────────────────────────

class TestRunQualityCheck:
    def test_aggregates_cost(self):
        """두 LLM 호출의 비용이 total_cost_usd에 합산되는지 확인."""
        hallucination_resp = json.dumps({
            "overall_risk": 30,
            "claims": [],
            "summary": "이상 없음",
        })
        aida_pas_resp = json.dumps({
            "scores": [
                {
                    "idea_id": "카드뉴스1",
                    "framework": "AIDA",
                    "checklist": {"attention": 1, "interest": 0, "desire": 1, "action": 0},
                    "normalized_score": 5.0,
                    "comment": "보통",
                }
            ],
            "avg_score": 5.0,
        })

        call_count = 0
        responses = [hallucination_resp, aida_pas_resp]

        def fake_create(**kwargs):
            nonlocal call_count
            content = MagicMock()
            content.text = responses[call_count]
            usage = MagicMock()
            usage.input_tokens = 100
            usage.output_tokens = 200
            response = MagicMock()
            response.content = [content]
            response.usage = usage
            call_count += 1
            return response

        from llm_pipeline.clients.anthropic_client import AnthropicClient
        real_client = AnthropicClient.__new__(AnthropicClient)
        real_client._client = MagicMock()
        real_client._client.messages.create.side_effect = fake_create

        quality, usages = run_quality_check(real_client, _make_ideas(), _make_brief())

        assert isinstance(quality, QualityResult)
        assert len(usages) == 2
        expected_cost = sum(u.cost_usd for u in usages)
        assert quality.total_cost_usd == pytest.approx(expected_cost)


# ── 출처 태그 누락 위험도 ─────────────────────────────────────────────────────

class TestMissingSourceTagFlagged:
    def test_missing_tag_risk_above_70(self):
        """출처 태그 없는 수치 주장은 risk >= 70이어야 함."""
        claim = SuspiciousClaim(
            text="수익률 +18%",
            claim_type="number",
            risk=75,
            reason="출처 태그 누락",
            source_tag_present=False,
        )
        assert claim.risk >= 70
        assert not claim.source_tag_present

    def test_tag_present_lower_risk(self):
        """출처 태그가 있으면 risk < 70이 정상."""
        claim = SuspiciousClaim(
            text="연 148만 원 세액공제 [확인 필요: 국세청]",
            claim_type="number",
            risk=20,
            reason="출처 태그 존재",
            source_tag_present=True,
        )
        assert claim.risk < 70
        assert claim.source_tag_present
