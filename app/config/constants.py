"""Static constants used across ETF idea generation modules."""

from __future__ import annotations

ETF_TERMS: list[str] = [
    "etf",
    "상장지수펀드",
    "인덱스펀드",
    "미국 etf",
    "국내 etf",
    "테마 etf",
    "배당 etf",
    "고배당",
    "월배당",
    "커버드콜",
    "분배금",
    "금리",
    "수익률",
    "변동성",
    "리스크",
    "포트폴리오",
    "자산배분",
    "리밸런싱",
    "isa",
    "연금",
    "퇴직연금",
    "절세계좌",
    "채권 etf",
    "리츠 etf",
    "원자재 etf",
    "레버리지 etf",
    "인버스 etf",
    "환헤지",
    "총보수",
    "추적오차",
]

AD_TERMS: list[str] = [
    "광고",
    "협찬",
    "체험단",
    "유료광고",
    "유료 홍보",
    "제휴",
    "파트너스 활동",
    "쿠팡 파트너스",
    "원고료",
    "소정의 수수료",
    "수수료를 제공받",
    "경제적 대가",
    "sponsored",
    "paid promotion",
    "promotion",
    "affiliate",
]

KOREAN_STOPWORDS: list[str] = [
    "이",
    "그",
    "저",
    "것",
    "수",
    "등",
    "및",
    "또는",
    "그리고",
    "하지만",
    "그러나",
    "에서",
    "으로",
    "에게",
    "하다",
    "했다",
    "합니다",
    "있는",
    "없는",
    "대한",
    "위한",
    "관련",
    "통해",
    "정도",
    "이번",
    "지난",
    "최근",
    "오늘",
    "내일",
    "매우",
    "정말",
    "좀",
    "더",
    "또",
    "각",
    "추천",
    "후기",
    "정리",
    "포스팅",
    "소개",
    "리뷰",
    "공유",
]

TREND_SCORE_WEIGHTS: dict[str, float] = {
    "growth": 0.45,
    "volume": 0.35,
    "cohesion": 0.20,
}

# ── 키워드 필터 상수 (여러 스크립트에서 공유) ─────────────────────────────────
GENERIC_KEYWORDS: set[str] = {
    "미국", "시장", "상품", "투자자", "종목", "기업", "수익", "상승", "하락",
    "가격", "자산", "주식", "비중", "운용", "상장", "비용", "구조", "관계",
    "활용", "전략", "포트폴리오", "분산", "투자", "국내", "해외", "정보",
    "비교", "방향", "기록", "내용", "이해", "추천", "방법",
}

NOISE_KEYWORDS: set[str] = {"naver", "com", "blog", "사기", "이벤트", "top"}

SOURCE_DB_CONFIG: dict[str, dict] = {
    "blog": {"db": "etf_trend.db",      "results_dir": "results"},
    "news": {"db": "etf_trend_news.db", "results_dir": "results/news"},
}

# ── ML / 클러스터링 상수 ──────────────────────────────────────────────────────
KMEANS_K_MIN: int = 2
KMEANS_K_MAX: int = 10
KMEANS_N_INIT: int = 10
KMEANS_RANDOM_STATE: int = 42

SVD_N_COMPONENTS: int = 50
SVD_RANDOM_STATE: int = 42

LDA_N_COMPONENTS: int = 10
LDA_RANDOM_STATE: int = 42
