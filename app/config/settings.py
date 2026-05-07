"""Application settings and environment variable loading."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from a local .env file if it exists."""
    path = Path(env_path)
    if not path.exists():
        logger.info("No .env file found at %s", path.resolve())
        return

    logger.info("Loading environment variables from %s", path.resolve())
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")

        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")
# OPENAI_API_KEY is optional for collection-only stages.
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

BASE_KEYWORDS: list[str] = [
    "ETF",
    "미국 ETF",
    "국내 ETF",
    "배당 ETF",
    "월배당 ETF",
    "채권 ETF",
    "리츠 ETF",
    "원자재 ETF",
    "S&P500 ETF",
    "나스닥 ETF",
]

EXPANDED_KEYWORDS: list[str] = [
    # Anchor + Theme
    "ETF 초보 포트폴리오",
    "미국 ETF 자산배분",
    "연금 ETF 장기투자",
    "테마 ETF 리스크",
    # Anchor + Intent
    "ETF 추천 기준",
    "ETF 비교 방법",
    "ETF 수수료 낮은 상품",
    "ETF 리밸런싱 주기",
    "ETF 세금 정리",
    # Theme + Trigger
    "금리 인하 수혜 ETF",
    "환율 변동 대응 ETF",
    "경기침체 방어 ETF",
    "AI 성장 수혜 ETF",
    "반도체 사이클 ETF",
    # Manual Combined
    "S&P500 ETF vs 나스닥 ETF",
    "채권 ETF 듀레이션 전략",
    "고배당 ETF 함정",
    "인버스 ETF 단기 대응",
    "레버리지 ETF 장기보유 위험",
]

DEFAULT_KEYWORDS: list[str] = BASE_KEYWORDS + EXPANDED_KEYWORDS

DEFAULT_DAYS: int = 14
MAX_RESULTS_PER_KEYWORD: int = 60
MIN_RESULTS_PER_KEYWORD: int = 20


def load_settings() -> dict[str, Any]:
    """Validate required settings and return runtime configuration dictionary."""
    missing_required: list[str] = []

    if not NAVER_CLIENT_ID:
        missing_required.append("NAVER_CLIENT_ID")
    if not NAVER_CLIENT_SECRET:
        missing_required.append("NAVER_CLIENT_SECRET")

    if missing_required:
        missing_str = ", ".join(missing_required)
        logger.error("Missing required environment variables: %s", missing_str)
        raise ValueError(f"Missing required environment variables: {missing_str}")

    settings_map: dict[str, Any] = {
        "NAVER_CLIENT_ID": NAVER_CLIENT_ID,
        "NAVER_CLIENT_SECRET": NAVER_CLIENT_SECRET,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "BASE_KEYWORDS": BASE_KEYWORDS,
        "EXPANDED_KEYWORDS": EXPANDED_KEYWORDS,
        "DEFAULT_KEYWORDS": DEFAULT_KEYWORDS,
        "DEFAULT_DAYS": DEFAULT_DAYS,
        "MIN_RESULTS_PER_KEYWORD": MIN_RESULTS_PER_KEYWORD,
        "MAX_RESULTS_PER_KEYWORD": MAX_RESULTS_PER_KEYWORD,
    }
    logger.info("Settings loaded successfully.")
    return settings_map
