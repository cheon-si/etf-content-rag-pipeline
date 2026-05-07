"""Orchestrator 단위 테스트."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llm_pipeline.orchestrator import run_cluster_pipeline
from llm_pipeline.schemas import (
    AIDAStructure,
    ClusterCostReport,
    ClusterInput,
    ContentClusterOutput,
    ContentOutput,
    GEOOutput,
    GEOScore,
    IntentOutput,
    JTBDOutput,
    PASStructure,
    SubTopic,
    TokenUsage,
)

_USAGE = TokenUsage(model="claude-sonnet-4-6", stage="test",
                    input_tokens=100, output_tokens=200, cost_usd=0.001)


def _make_mocks():
    anthropic = MagicMock()
    gemini = MagicMock()

    intent = IntentOutput(intent_type="Informational", confidence=0.9, reasoning="테스트")
    jtbd = JTBDOutput(
        main_job="테스트 Job",
        functional_needs=["니즈1"],
        emotional_needs=["감정1"],
        social_needs=["사회1"],
        hire_context="테스트 컨텍스트",
    )
    cluster_design = ContentClusterOutput(
        pillar_title="테스트 Pillar",
        pillar_angle="테스트 각도",
        sub_topics=[SubTopic(title=f"Sub{i}", angle=f"A{i}", keywords=[f"k{i}"]) for i in range(5)],
        competitor_gaps=["갭1"],
    )
    content = ContentOutput(
        title="테스트 제목",
        slug="test-slug",
        body_markdown="## 본문\n테스트 내용입니다.",
        aida_structure=AIDAStructure(attention="A", interest="I", desire="D", action="A"),
        pas_structure=PASStructure(problem="P", agitation="A", solution="S"),
    )
    geo = GEOOutput(
        optimized_markdown="## 최적화 본문\n내용입니다.",
        geo_score=GEOScore(ai_overview=80, naver_cue=75),
        improvements=["개선1", "개선2", "개선3"],
    )

    return anthropic, gemini, intent, jtbd, cluster_design, content, geo


class TestOrchestrator:
    def test_returns_geo_output_and_cost_report(self, tmp_path, sample_cluster):
        anthropic, gemini, intent, jtbd, cluster_design, content, geo = _make_mocks()

        with patch("llm_pipeline.orchestrator.s1_intent.run", return_value=(intent, _USAGE)), \
             patch("llm_pipeline.orchestrator.s2_jtbd.run", return_value=(jtbd, _USAGE)), \
             patch("llm_pipeline.orchestrator.s3_cluster.run", return_value=(cluster_design, [_USAGE])), \
             patch("llm_pipeline.orchestrator.s4_content.run", return_value=(content, [_USAGE, _USAGE, _USAGE])), \
             patch("llm_pipeline.orchestrator.s5_geo.run", return_value=(geo, _USAGE)):

            result_geo, cost_report = run_cluster_pipeline(
                sample_cluster, tmp_path, anthropic, gemini
            )

        assert isinstance(result_geo, GEOOutput)
        assert isinstance(cost_report, ClusterCostReport)

    def test_intermediate_files_saved(self, tmp_path, sample_cluster):
        anthropic, gemini, intent, jtbd, cluster_design, content, geo = _make_mocks()

        with patch("llm_pipeline.orchestrator.s1_intent.run", return_value=(intent, _USAGE)), \
             patch("llm_pipeline.orchestrator.s2_jtbd.run", return_value=(jtbd, _USAGE)), \
             patch("llm_pipeline.orchestrator.s3_cluster.run", return_value=(cluster_design, [_USAGE])), \
             patch("llm_pipeline.orchestrator.s4_content.run", return_value=(content, [_USAGE, _USAGE, _USAGE])), \
             patch("llm_pipeline.orchestrator.s5_geo.run", return_value=(geo, _USAGE)):

            run_cluster_pipeline(sample_cluster, tmp_path, anthropic, gemini)

        inter_dir = tmp_path / "intermediate"
        expected = [
            f"cluster_1_s1_intent.json",
            f"cluster_1_s2_jtbd.json",
            f"cluster_1_s3_cluster.json",
            f"cluster_1_s4_content.json",
            f"cluster_1_s5_geo.json",
        ]
        for fname in expected:
            assert (inter_dir / fname).exists(), f"{fname} 없음"

    def test_intermediate_files_are_valid_json(self, tmp_path, sample_cluster):
        anthropic, gemini, intent, jtbd, cluster_design, content, geo = _make_mocks()

        with patch("llm_pipeline.orchestrator.s1_intent.run", return_value=(intent, _USAGE)), \
             patch("llm_pipeline.orchestrator.s2_jtbd.run", return_value=(jtbd, _USAGE)), \
             patch("llm_pipeline.orchestrator.s3_cluster.run", return_value=(cluster_design, [_USAGE])), \
             patch("llm_pipeline.orchestrator.s4_content.run", return_value=(content, [_USAGE, _USAGE, _USAGE])), \
             patch("llm_pipeline.orchestrator.s5_geo.run", return_value=(geo, _USAGE)):

            run_cluster_pipeline(sample_cluster, tmp_path, anthropic, gemini)

        for f in (tmp_path / "intermediate").glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_cost_report_aggregates_all_usages(self, tmp_path, sample_cluster):
        anthropic, gemini, intent, jtbd, cluster_design, content, geo = _make_mocks()

        with patch("llm_pipeline.orchestrator.s1_intent.run", return_value=(intent, _USAGE)), \
             patch("llm_pipeline.orchestrator.s2_jtbd.run", return_value=(jtbd, _USAGE)), \
             patch("llm_pipeline.orchestrator.s3_cluster.run", return_value=(cluster_design, [_USAGE])), \
             patch("llm_pipeline.orchestrator.s4_content.run", return_value=(content, [_USAGE, _USAGE, _USAGE])), \
             patch("llm_pipeline.orchestrator.s5_geo.run", return_value=(geo, _USAGE)):

            _, cost_report = run_cluster_pipeline(
                sample_cluster, tmp_path, anthropic, gemini
            )

        # s1(1) + s2(1) + s3(1) + s4(3) + s5(1) = 7개
        assert len(cost_report.usages) == 7
        assert cost_report.total_cost_usd == pytest.approx(7 * 0.001)
