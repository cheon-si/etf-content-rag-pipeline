"""Content strategy stage functions — LLM 기반 콘텐츠 아이디어 생성."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_anthropic_client():
    """AnthropicClient를 지연 임포트로 초기화한다."""
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env", override=True)
    from llm_pipeline.clients.anthropic_client import AnthropicClient
    return AnthropicClient()


def _rows_to_cluster_inputs(rows: list[dict[str, Any]]):
    """run_generate_report의 클러스터 rows → ClusterInput 목록으로 변환."""
    from llm_pipeline.schemas import ClusterInput
    result = []
    for i, row in enumerate(rows, 1):
        kws = row.get("keywords", [])
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]
        result.append(ClusterInput(
            rank=i,
            cluster_name=row.get("cluster_name", row.get("cluster_id", f"cluster_{i}")),
            keywords=kws[:10],
            post_count=row.get("size", row.get("post_count", 0)),
        ))
    return result


def generate_topics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """클러스터 rows → 카드뉴스·블로그 주제 목록 생성.

    반환 형식:
        [{"cluster_name": str, "topics": [{"title": str, "angle": str}]}]
    """
    logger.info("Topic generation requested (rows=%d).", len(rows))
    if not rows:
        return []

    try:
        from llm_pipeline.stages import s1_intent, s2_jtbd
        from llm_pipeline.outputs.content_ideas import run_content_ideas

        client = _get_anthropic_client()
        clusters = _rows_to_cluster_inputs(rows)
        output = []
        for cluster in clusters:
            intent, _ = s1_intent.run(cluster, client)
            jtbd, _ = s2_jtbd.run(cluster, intent, client)
            ideas, _ = run_content_ideas(cluster, jtbd, client)
            output.append({
                "cluster_name": cluster.cluster_name,
                "topics": [
                    {"title": cn.topic, "angle": cn.key_message}
                    for cn in ideas.card_news_ideas
                ] + [
                    {"title": t, "angle": "블로그"} for t in ideas.blog_titles
                ],
            })
        return output
    except Exception as exc:
        logger.error("generate_topics 실패: %s", exc)
        raise


def generate_video_titles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """클러스터 rows → 유튜브 제목 목록 생성.

    반환 형식:
        [{"cluster_name": str, "youtube_titles": [str]}]
    """
    logger.info("Video title generation requested (rows=%d).", len(rows))
    if not rows:
        return []

    try:
        from llm_pipeline.stages import s1_intent, s2_jtbd
        from llm_pipeline.outputs.content_ideas import run_content_ideas

        client = _get_anthropic_client()
        clusters = _rows_to_cluster_inputs(rows)
        output = []
        for cluster in clusters:
            intent, _ = s1_intent.run(cluster, client)
            jtbd, _ = s2_jtbd.run(cluster, intent, client)
            ideas, _ = run_content_ideas(cluster, jtbd, client)
            output.append({
                "cluster_name": cluster.cluster_name,
                "youtube_titles": ideas.youtube_titles,
            })
        return output
    except Exception as exc:
        logger.error("generate_video_titles 실패: %s", exc)
        raise


def generate_one_line_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """클러스터 rows → SNS 메시지 + 팀장 보고 한 줄 요약 생성.

    반환 형식:
        [{"cluster_name": str, "sns_messages": [str], "one_liner": str}]
    """
    logger.info("One-line message generation requested (rows=%d).", len(rows))
    if not rows:
        return []

    try:
        from llm_pipeline.stages import s1_intent, s2_jtbd
        from llm_pipeline.outputs.content_ideas import run_content_ideas

        client = _get_anthropic_client()
        clusters = _rows_to_cluster_inputs(rows)
        output = []
        for cluster in clusters:
            intent, _ = s1_intent.run(cluster, client)
            jtbd, _ = s2_jtbd.run(cluster, intent, client)
            ideas, _ = run_content_ideas(cluster, jtbd, client)
            output.append({
                "cluster_name": cluster.cluster_name,
                "sns_messages": ideas.sns_messages,
                "one_liner": ideas.one_liner,
            })
        return output
    except Exception as exc:
        logger.error("generate_one_line_messages 실패: %s", exc)
        raise
