"""Shared schema types for pipeline stages."""

from __future__ import annotations

from typing import TypedDict


class RawPost(TypedDict, total=False):
    """Raw post collected from ingestion sources."""

    doc_id: str
    keyword: str
    title: str
    description: str
    link: str
    post_date: str
    blogger_name: str
    blogger_link: str
    raw_text: str


class PreprocessedDoc(TypedDict, total=False):
    """Document after text extraction and cleaning."""

    doc_id: str
    keyword: str
    clean_text: str
    doc_length: int


class FilteredDoc(TypedDict, total=False):
    """Document after rule and proxy-score filtering."""

    doc_id: str
    passed_rule_filter: bool
    etf_mentions: int
    proxy_score: float


class ClusteredDoc(TypedDict, total=False):
    """Document after embedding and clustering."""

    doc_id: str
    embedding: list[float]
    cluster_id: int


class TrendDoc(TypedDict, total=False):
    """Document with trend analysis signals attached."""

    doc_id: str
    growth_score: float
    volume_score: float
    cohesion_score: float
    trend_score: float


class InsightDoc(TypedDict, total=False):
    """Document with JTBD and search intent insights."""

    doc_id: str
    search_intent: str
    jtbd: str


class ContentIdea(TypedDict, total=False):
    """Content strategy output item."""

    doc_id: str
    topic: str
    video_title: str
    one_line_message: str

