"""RAGContextBuilder — 파이프라인 스테이지별 컨텍스트 조합."""
from __future__ import annotations

import logging
from pathlib import Path

from llm_pipeline.rag.vector_store import VectorStore
from llm_pipeline.rag.wiki import WikiStore

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")
INDEX_DIR = str(_PROJECT_ROOT / "data" / "rag")


class RAGContextBuilder:
    def __init__(self, wiki: WikiStore | None = None, vector: VectorStore | None = None):
        self.wiki = wiki or WikiStore(DB_PATH)
        self.vector = vector or VectorStore(INDEX_DIR, DB_PATH)

    def build_context(self, stage: str, keywords: list[str], cluster_name: str = "") -> str:
        """스테이지에 맞는 RAG 컨텍스트를 조합하여 반환."""
        if stage == "content_ideas":
            return self._for_content_ideas(keywords, cluster_name)
        elif stage == "content_brief":
            return self._for_content_brief(keywords)
        elif stage == "s4_draft":
            return self._for_s4_draft(keywords, cluster_name)
        elif stage == "s4_factcheck":
            return self._for_s4_factcheck(keywords)
        elif stage == "s3_cluster":
            return self._for_s3(keywords, cluster_name)
        else:
            return self._for_generic(keywords)

    def _for_content_ideas(self, keywords: list[str], cluster_name: str) -> str:
        """콘텐츠 아이디어: ETF 상품(키워드+테마) + 과거 결과물(반복 방지)."""
        parts = []

        products = self._search_with_theme_fallback(keywords, top_k=10)
        if products:
            parts.append(WikiStore.format_products(products))

        query = f"{cluster_name} {' '.join(keywords[:5])}"
        past = self.vector.search(query, "past_output", top_k=5)
        if past:
            lines = ["[과거 생성 콘텐츠 (반복 방지 참고)]"]
            for r in past:
                lines.append(f"- [{r['post_date']}] {r['title']}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def _for_content_brief(self, keywords: list[str]) -> str:
        """콘텐츠 브리프: 세제/규제 + 거래대금 상위 ETF + 과거 브리프."""
        parts = []

        tax_rules = self.wiki.search_tax_rules(keywords)
        if not tax_rules:
            tax_rules = self.wiki.get_all("tax_rule")
        if tax_rules:
            parts.append(WikiStore.format_tax_rules(tax_rules))

        regs = self.wiki.get_all("regulation")
        if regs:
            parts.append(WikiStore.format_regulations(regs))

        top_etfs = self.wiki.get_top_by_market_cap(15)
        if top_etfs:
            parts.append(WikiStore.format_products(top_etfs))

        query = " ".join(keywords[:5])
        past = self.vector.search(query, "past_output", top_k=3)
        if past:
            lines = ["[최근 생성 브리프 (중복 방지)]"]
            for r in past:
                lines.append(f"- [{r['post_date']}] {r['title']}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def _for_s4_draft(self, keywords: list[str], cluster_name: str) -> str:
        """S4 초안: ETF 상품 + 세제 + 관련 블로그(톤 참조)."""
        parts = []

        products = self._search_with_theme_fallback(keywords, top_k=8)
        if products:
            parts.append(WikiStore.format_products(products))

        tax_rules = self.wiki.search_tax_rules(keywords)
        if tax_rules:
            parts.append(WikiStore.format_tax_rules(tax_rules))

        query = f"{cluster_name} {' '.join(keywords[:4])}"
        blogs = self.vector.search(query, "blog", top_k=2)
        if blogs:
            lines = ["[참고 블로그 (톤/구성 참조)]"]
            for r in blogs:
                lines.append(f"- {r['title']}: {r['text_preview'][:100]}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def _for_s4_factcheck(self, keywords: list[str]) -> str:
        """S4 팩트체크: ETF 상품 + 세제 + 규제 + 뉴스."""
        parts = []

        products = self.wiki.search_products(keywords, top_k=5)
        if products:
            parts.append(WikiStore.format_products(products))

        tax_rules = self.wiki.search_tax_rules(keywords)
        if tax_rules:
            parts.append(WikiStore.format_tax_rules(tax_rules))

        regs = self.wiki.search_regulations(keywords)
        if regs:
            parts.append(WikiStore.format_regulations(regs))

        query = " ".join(keywords[:5])
        news = self.vector.search(query, "news", top_k=3)
        if news:
            lines = ["[관련 뉴스]"]
            for r in news:
                lines.append(f"- [{r['post_date']}] {r['title']}: {r['text_preview'][:80]}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def _for_s3(self, keywords: list[str], cluster_name: str) -> str:
        """S3 클러스터 설계: ETF 상품(운용사 중립) + 관련 블로그."""
        parts = []

        products = self._search_with_theme_fallback(keywords, top_k=10)
        if products:
            parts.append(WikiStore.format_products(products))

        query = f"{cluster_name} {' '.join(keywords[:4])}"
        blogs = self.vector.search(query, "blog", top_k=3)
        if blogs:
            lines = ["[관련 블로그]"]
            for r in blogs:
                lines.append(f"- {r['title']}: {r['text_preview'][:80]}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def _for_generic(self, keywords: list[str]) -> str:
        """기본: ETF 상품만."""
        products = self._search_with_theme_fallback(keywords, top_k=10)
        return WikiStore.format_products(products) if products else ""

    _KEYWORD_TO_THEME = {
        "레버리지": ["레버리지2X"],
        "커버드콜": ["커버드콜"],
        "월배당": ["월배당"],
        "고배당": ["고배당", "월배당"],
        "배당": ["고배당", "월배당"],
        "반도체": ["K-반도체", "글로벌반도체"],
        "ai": ["AI"],
        "인공지능": ["AI"],
        "나스닥": ["나스닥100"],
        "s&p": ["S&P500"],
        "미국": ["미국", "S&P500", "나스닥100"],
        "중국": ["중국"],
        "친환경": ["친환경"],
        "esg": ["친환경"],
        "헬스케어": ["헬스케어섹터"],
        "바이오": ["헬스케어섹터"],
        "단기": ["단기채", "단기금리"],
        "장기": ["장기채"],
        "회사채": ["회사채"],
        "국채": ["국공채", "장기채"],
        "코스피": ["KOSPI200"],
        "kospi": ["KOSPI200"],
        "방산": ["산업재섹터"],
        "조선": ["산업재섹터"],
        "리츠": ["부동산"],
        "환헤지": ["환헤지"],
    }

    def _keywords_to_themes(self, keywords: list[str]) -> list[str]:
        themes = set()
        for kw in keywords:
            kw_lower = kw.lower().strip()
            for trigger, mapped in self._KEYWORD_TO_THEME.items():
                if trigger in kw_lower or kw_lower in trigger:
                    themes.update(mapped)
        return list(themes)

    def _search_with_theme_fallback(self, keywords: list[str], top_k: int = 10) -> list[dict]:
        """키워드 직접 매칭 + 테마 매핑 검색 결과 병합 (시총순, 중복 제거)."""
        seen_codes = set()
        merged = []

        for p in self.wiki.search_products(keywords, top_k=top_k):
            if p["code"] not in seen_codes:
                seen_codes.add(p["code"])
                merged.append(p)

        themes = self._keywords_to_themes(keywords)
        if themes:
            for p in self.wiki.search_products_by_theme(themes, top_k=top_k):
                if p["code"] not in seen_codes:
                    seen_codes.add(p["code"])
                    merged.append(p)

        merged.sort(key=lambda x: -int(x.get("market_cap", 0)))
        return merged[:top_k]
