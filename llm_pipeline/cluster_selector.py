"""블로그 + 뉴스 ML 클러스터 교차 선택 — 공통 N개 + 블로그 M개 + 뉴스 K개."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_pipeline.config import NOISE_KEYWORDS
from llm_pipeline.schemas import ClusterInput

logger = logging.getLogger(__name__)


def select_clusters(
    blog_db: str,
    news_db: str,
    top_common: int = 2,
    top_blog: int = 1,
    top_news: int = 1,
) -> list[ClusterInput]:
    """블로그·뉴스 DB에서 클러스터를 가중 선택해 ClusterInput 목록 반환.

    선택 기준:
      - 공통(blog+news): blog_size + news_size 합산 상위 top_common개
      - 블로그 단독:      blog_size 상위 top_blog개
      - 뉴스 단독:        news_size 상위 top_news개
    """
    from run_generate_content_brief import load_clusters_from_db
    from app.content_strategy.content_brief import match_clusters

    blog_clusters = load_clusters_from_db(blog_db)
    news_clusters = load_clusters_from_db(news_db)

    if not blog_clusters:
        logger.warning("[ClusterSelector] 블로그 DB 클러스터 없음: %s", blog_db)
    if not news_clusters:
        logger.warning("[ClusterSelector] 뉴스 DB 클러스터 없음: %s", news_db)

    themes = match_clusters(blog_clusters, news_clusters)

    # 노이즈 주제 제거 ([노이즈] 태그 또는 노이즈 키워드 포함)
    def _is_noise_theme(t: dict) -> bool:
        if "[노이즈]" in t.get("theme", ""):
            return True
        combined_kws = t.get("blog_keywords", []) + t.get("news_keywords", [])
        return any(n in combined_kws for n in NOISE_KEYWORDS)

    themes = [t for t in themes if not _is_noise_theme(t)]

    common = sorted(
        [t for t in themes if t["source"] == "공통"],
        key=lambda t: t["blog_size"] + t["news_size"],
        reverse=True,
    )
    blog_only = sorted(
        [t for t in themes if t["source"] == "블로그"],
        key=lambda t: t["blog_size"],
        reverse=True,
    )
    news_only = sorted(
        [t for t in themes if t["source"] == "뉴스"],
        key=lambda t: t["news_size"],
        reverse=True,
    )

    selected = common[:top_common] + blog_only[:top_blog] + news_only[:top_news]

    logger.info(
        "[ClusterSelector] 선택: 공통 %d개, 블로그 %d개, 뉴스 %d개 → 합계 %d개",
        min(top_common, len(common)),
        min(top_blog, len(blog_only)),
        min(top_news, len(news_only)),
        len(selected),
    )

    result: list[ClusterInput] = []
    for rank, theme in enumerate(selected, start=1):
        source_tag = {"공통": "[공통]", "블로그": "[블로그]", "뉴스": "[뉴스]"}.get(
            theme["source"], ""
        )
        cluster_name = f"{source_tag} {theme['theme']}"

        # 블로그 키워드 우선, 뉴스 키워드 보완 (중복 제거, top 10)
        combined_kws: list[str] = list(
            dict.fromkeys(theme["blog_keywords"] + theme["news_keywords"])
        )[:10]

        post_count = theme["blog_size"] + theme["news_size"]

        result.append(
            ClusterInput(
                rank=rank,
                cluster_name=cluster_name,
                keywords=combined_kws,
                post_count=post_count,
            )
        )

    return result
