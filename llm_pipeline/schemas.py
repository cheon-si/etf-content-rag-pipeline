"""Pydantic v2 스키마 — 단계별 input/output 및 비용 추적."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── 공통 ──────────────────────────────────────────────────────────────────────

class TokenUsage(BaseModel):
    model: str
    stage: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ClusterRaw(BaseModel):
    """HTML 파싱 결과 (선택 전 전체 클러스터)."""
    table_index: int          # 테이블 내 0-based 순서
    cluster_name: str
    post_count: int
    keywords: list[str]       # span 텍스트 목록


class ClusterInput(BaseModel):
    """파이프라인 입력 단위."""
    rank: int = Field(ge=1)   # 선택된 순서 (1~N)
    cluster_name: str
    keywords: list[str]       # top 10
    post_count: int = 0


# ── Stage 1: Search Intent ────────────────────────────────────────────────────

class IntentOutput(BaseModel):
    intent_type: Literal["Informational", "Commercial", "Transactional"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ── Stage 2: JTBD ─────────────────────────────────────────────────────────────

class JTBDOutput(BaseModel):
    main_job: str
    functional_needs: list[str]
    emotional_needs: list[str]
    social_needs: list[str]
    hire_context: str


# ── Stage 3: Content Cluster ──────────────────────────────────────────────────

class SubTopic(BaseModel):
    title: str
    angle: str
    keywords: list[str]


class ContentClusterOutput(BaseModel):
    pillar_title: str
    pillar_angle: str
    sub_topics: list[SubTopic] = Field(min_length=5, max_length=5)
    competitor_gaps: list[str]


# ── Stage 4: Content Body ─────────────────────────────────────────────────────

class AIDAStructure(BaseModel):
    attention: str
    interest: str
    desire: str
    action: str


class PASStructure(BaseModel):
    problem: str
    agitation: str
    solution: str


class ContentOutput(BaseModel):
    title: str
    slug: str
    body_markdown: str
    aida_structure: AIDAStructure
    pas_structure: PASStructure


# ── Stage 5: GEO ─────────────────────────────────────────────────────────────

class GEOScore(BaseModel):
    ai_overview: int = Field(ge=0, le=100)
    naver_cue: int = Field(ge=0, le=100)


class GEOOutput(BaseModel):
    optimized_markdown: str
    geo_score: GEOScore
    improvements: list[str] = Field(min_length=1)


# ── 비용 리포트 ───────────────────────────────────────────────────────────────

class ClusterCostReport(BaseModel):
    cluster_name: str
    rank: int
    usages: list[TokenUsage]
    total_cost_usd: float


class RunCostReport(BaseModel):
    run_date: str
    clusters: list[ClusterCostReport]
    total_cost_usd: float
    monthly_total_usd: float
    monthly_limit_usd: float
    limit_exceeded: bool


# ── 콘텐츠 아이디어 생성기 ────────────────────────────────────────────────────

class CardNewsIdea(BaseModel):
    topic: str                        # 카드뉴스 주제
    card_titles: list[str]            # 카드별 제목 5~7개
    key_message: str                  # 핵심 메시지 1문장


class ContentIdeasOutput(BaseModel):
    cluster_name: str
    keywords: list[str]
    card_news_ideas: list[CardNewsIdea] = Field(min_length=1)   # 3개
    blog_titles: list[str]            # 5개
    youtube_titles: list[str]         # 3개
    sns_messages: list[str]           # 5개 (140자 이내, 해시태그 포함)
    one_liner: str                    # 팀장 보고용 한 줄 요약


# ── 트렌드 기반 콘텐츠 브리프 ─────────────────────────────────────────────────

class TrendSignal(BaseModel):
    topic: str
    trend_direction: Literal["급상승", "상승", "유지", "하락"]
    evidence: str                     # 수치나 근거 1문장
    jtbd_question: str                # 독자가 실제로 묻는 질문 (JTBD 형식)


class ContentBriefOutput(BaseModel):
    week_label: str                   # "2026년 17주차"
    top_signals: list[TrendSignal] = Field(min_length=1)    # 5개
    content_direction: str            # 이번 주 콘텐츠 방향 1단락
    recommended_formats: list[str]    # ["카드뉴스", "블로그", "유튜브 쇼츠"]
    urgency_reason: str               # 왜 이번 주에 이 주제인가


# ── 품질 검증 ─────────────────────────────────────────────────────────────────

class SuspiciousClaim(BaseModel):
    text: str
    claim_type: Literal["number", "product", "legal"]
    risk: int = Field(ge=0, le=100)
    reason: str
    source_tag_present: bool


class HallucinationReport(BaseModel):
    overall_risk: int = Field(ge=0, le=100)
    claims: list[SuspiciousClaim] = Field(default_factory=list)
    summary: str


class FrameworkScore(BaseModel):
    idea_id: str
    framework: Literal["AIDA", "PAS"]
    checklist: dict[str, int]
    normalized_score: float = Field(ge=0.0, le=10.0)
    comment: str


class AidaPasReport(BaseModel):
    scores: list[FrameworkScore] = Field(default_factory=list)
    avg_score: float = Field(ge=0.0, le=10.0)


class QualityResult(BaseModel):
    hallucination: HallucinationReport
    framework: AidaPasReport
    total_cost_usd: float
