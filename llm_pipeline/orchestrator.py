"""5단계 파이프라인 순차 실행 — 중간 산출물 저장·비용 집계·타임아웃."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from llm_pipeline.clients.anthropic_client import AnthropicClient
from llm_pipeline.clients.gemini_client import GeminiClient
from llm_pipeline.config import STAGE_TIMEOUT_SECONDS
from llm_pipeline.schemas import (
    ClusterCostReport,
    ClusterInput,
    GEOOutput,
    TokenUsage,
)
from llm_pipeline.stages import s1_intent, s2_jtbd, s3_cluster, s4_content, s5_geo

logger = logging.getLogger(__name__)


def _save_intermediate(data: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(data, "model_dump"):
        content = json.dumps(data.model_dump(), ensure_ascii=False, indent=2)
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")


def _run_with_timeout(fn, timeout: int = STAGE_TIMEOUT_SECONDS):
    """fn()을 별도 스레드에서 실행하고 timeout 초 내 완료되지 않으면 예외를 발생시킨다."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        return future.result(timeout=timeout)


def run_cluster_pipeline(
    cluster: ClusterInput,
    output_dir: Path,
    anthropic: AnthropicClient,
    gemini: GeminiClient,
) -> tuple[GEOOutput, ClusterCostReport]:
    """단일 클러스터에 대해 5단계 파이프라인을 실행한다."""
    inter_dir = output_dir / "intermediate"
    inter_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"cluster_{cluster.rank}"
    all_usages: list[TokenUsage] = []

    # Stage 1
    logger.info("=== [Cluster %d] Stage 1 시작 ===", cluster.rank)
    intent, u1 = _run_with_timeout(lambda: s1_intent.run(cluster, anthropic))
    all_usages.append(u1)
    _save_intermediate(intent, inter_dir / f"{prefix}_s1_intent.json")

    # Stage 2
    logger.info("=== [Cluster %d] Stage 2 시작 ===", cluster.rank)
    jtbd, u2 = _run_with_timeout(lambda: s2_jtbd.run(cluster, intent, anthropic))
    all_usages.append(u2)
    _save_intermediate(jtbd, inter_dir / f"{prefix}_s2_jtbd.json")

    # Stage 3
    logger.info("=== [Cluster %d] Stage 3 시작 ===", cluster.rank)
    cluster_design, u3_list = _run_with_timeout(
        lambda: s3_cluster.run(cluster, intent, jtbd, anthropic, gemini)
    )
    all_usages.extend(u3_list)
    _save_intermediate(cluster_design, inter_dir / f"{prefix}_s3_cluster.json")

    # Stage 4
    logger.info("=== [Cluster %d] Stage 4 시작 ===", cluster.rank)
    content_output, u4_list = _run_with_timeout(
        lambda: s4_content.run(cluster, jtbd, cluster_design, anthropic)
    )
    all_usages.extend(u4_list)
    _save_intermediate(content_output, inter_dir / f"{prefix}_s4_content.json")

    # Stage 5
    logger.info("=== [Cluster %d] Stage 5 시작 ===", cluster.rank)
    geo_output, u5 = _run_with_timeout(
        lambda: s5_geo.run(content_output, gemini, anthropic)
    )
    all_usages.append(u5)
    _save_intermediate(geo_output, inter_dir / f"{prefix}_s5_geo.json")

    total_cost = sum(u.cost_usd for u in all_usages)
    cost_report = ClusterCostReport(
        cluster_name=cluster.cluster_name,
        rank=cluster.rank,
        usages=all_usages,
        total_cost_usd=total_cost,
    )
    logger.info(
        "=== [Cluster %d] 파이프라인 완료 — 총 비용 $%.4f ===",
        cluster.rank, total_cost,
    )
    return geo_output, cost_report
