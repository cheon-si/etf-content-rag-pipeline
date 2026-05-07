"""Stage 4 단위 테스트."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from llm_pipeline.schemas import (
    AIDAStructure,
    ContentClusterOutput,
    ContentOutput,
    JTBDOutput,
    PASStructure,
    SubTopic,
    TokenUsage,
)
from llm_pipeline.stages import s4_content

BODY_MD = """## ETF란 무엇인가\n\nETF는 상장지수펀드입니다.\n\n## 투자 방법\n\n분산 투자가 핵심입니다.\n\n## 주요 상품\n\nTIGER ETF가 대표적입니다.\n\n## FAQ\n\n**Q. ETF 수수료는?**\nA. 연 0.1~0.5%입니다.\n\n**Q. 최소 투자금은?**\nA. 1주부터 가능합니다.\n\n**Q. 세금은?**\nA. 배당소득세 15.4%가 적용됩니다."""

DRAFT_JSON = json.dumps({
    "title": "2025 AI ETF 완벽 가이드",
    "slug": "2025-ai-etf-guide",
    "body_markdown": BODY_MD,
    "aida_structure": {
        "attention": "AI ETF로 수익 내는 법",
        "interest": "AI 산업 성장 데이터",
        "desire": "실제 수익 사례",
        "action": "지금 투자 시작하기",
    },
    "pas_structure": {
        "problem": "AI 투자 기회를 놓치고 있다",
        "agitation": "시장은 이미 움직이고 있다",
        "solution": "AI ETF로 분산 투자하라",
    },
})


@pytest.fixture
def sample_jtbd() -> JTBDOutput:
    return JTBDOutput(
        main_job="AI ETF 투자 방법을 파악한다",
        functional_needs=["ETF 선택", "수수료 비교"],
        emotional_needs=["안심"],
        social_needs=["현명한 투자"],
        hire_context="처음 ETF를 매수하려는 30대",
    )


@pytest.fixture
def sample_cluster_design() -> ContentClusterOutput:
    return ContentClusterOutput(
        pillar_title="AI ETF 완벽 가이드",
        pillar_angle="초보도 이해하는 AI ETF 투자 전략",
        sub_topics=[
            SubTopic(title=f"Sub {i}", angle=f"Angle {i}", keywords=[f"kw{i}"])
            for i in range(1, 6)
        ],
        competitor_gaps=["세금 정보 없음"],
    )


def _make_client(draft_json: str):
    usage = TokenUsage(model="claude-opus-4-7", stage="s4_draft",
                       input_tokens=800, output_tokens=1200, cost_usd=0.05)
    draft = ContentOutput.model_validate_json(draft_json)
    client = MagicMock()
    client.complete_with_fallback.side_effect = [
        (draft, usage),               # 1차 초안
        ("toned body", usage),        # 2차 톤 조정
        ("fact-checked body", usage), # 3차 팩트 검증
    ]
    return client


class TestS4Content:
    def test_returns_content_output(self, sample_cluster, sample_jtbd, sample_cluster_design):
        client = _make_client(DRAFT_JSON)
        result, usages = s4_content.run(sample_cluster, sample_jtbd, sample_cluster_design, client)

        assert isinstance(result, ContentOutput)
        assert result.title
        assert result.slug
        assert result.body_markdown

    def test_three_iterations_called(self, sample_cluster, sample_jtbd, sample_cluster_design):
        client = _make_client(DRAFT_JSON)
        s4_content.run(sample_cluster, sample_jtbd, sample_cluster_design, client)

        assert client.complete_with_fallback.call_count == 3

    def test_three_usages_returned(self, sample_cluster, sample_jtbd, sample_cluster_design):
        client = _make_client(DRAFT_JSON)
        _, usages = s4_content.run(sample_cluster, sample_jtbd, sample_cluster_design, client)

        assert len(usages) == 3

    def test_final_body_is_fact_checked(self, sample_cluster, sample_jtbd, sample_cluster_design):
        client = _make_client(DRAFT_JSON)
        result, _ = s4_content.run(sample_cluster, sample_jtbd, sample_cluster_design, client)

        assert result.body_markdown == "fact-checked body"

    def test_aida_structure_preserved_from_draft(self, sample_cluster, sample_jtbd, sample_cluster_design):
        client = _make_client(DRAFT_JSON)
        result, _ = s4_content.run(sample_cluster, sample_jtbd, sample_cluster_design, client)

        assert isinstance(result.aida_structure, AIDAStructure)
        assert result.aida_structure.attention
