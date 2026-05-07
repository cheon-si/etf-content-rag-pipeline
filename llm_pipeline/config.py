"""모델명·가격·운영 상수 중앙 관리."""
from __future__ import annotations

# ── 모델 ──────────────────────────────────────────────────────────────────────
ANTHROPIC_SONNET = "claude-sonnet-4-6"
ANTHROPIC_OPUS   = "claude-opus-4-7"
GEMINI_PRO       = "gemini-2.5-flash"

# ── 토큰당 USD (1M 기준) ──────────────────────────────────────────────────────
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0,   "output": 15.0},
    "claude-opus-4-7":   {"input": 15.0,  "output": 75.0},
    "gemini-2.5-flash":  {"input": 0.075, "output": 0.30},
}

# ── 운영 상수 ─────────────────────────────────────────────────────────────────
MONTHLY_COST_LIMIT_USD = 30.0
STAGE_TIMEOUT_SECONDS  = 300
MAX_RETRIES            = 3
DEFAULT_TOP_N          = 3

# ── 노이즈 키워드 (클러스터 필터링 공통 사용) ─────────────────────────────────
NOISE_KEYWORDS: frozenset[str] = frozenset({"naver", "com", "blog", "사기", "이벤트", "top"})

