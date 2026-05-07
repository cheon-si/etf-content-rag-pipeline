"""Wiki 초기 시드: 네이버 금융 ETF 전종목 + 세제/규제 정보 로드."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llm_pipeline.rag.krx_fetcher import fetch_all_etf_products
from llm_pipeline.rag.wiki import WikiStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")

TAX_RULES = [
    {
        "key": "ISA_2026",
        "rule_name": "ISA 비과세 한도",
        "description": "납입한도 연 2,000만원(총 1억원), 비과세 한도 200만원(서민형 400만원), 초과분 9.9% 분리과세",
        "effective_year": 2026,
        "source": "금융위원회",
    },
    {
        "key": "IRP_2026",
        "rule_name": "IRP 세액공제",
        "description": "연간 납입한도 1,800만원, 세액공제 한도 900만원(연금저축 포함), 공제율 13.2%(총급여 5,500만원 이하 16.5%)",
        "effective_year": 2026,
        "source": "국세청",
    },
    {
        "key": "GIFT_TAX_MINOR_2026",
        "rule_name": "미성년자 증여재산공제",
        "description": "만 19세 미만 미성년자 10년간 2,000만원 비과세, 성인 10년간 5,000만원 비과세",
        "effective_year": 2026,
        "source": "국세청",
    },
    {
        "key": "ETF_DOMESTIC_TAX_2026",
        "rule_name": "국내 주식형 ETF 과세",
        "description": "매매차익 비과세 (2025년 이후 금투세 폐지 확정), 분배금 배당소득세 15.4%",
        "effective_year": 2026,
        "source": "국세청",
    },
    {
        "key": "ETF_OVERSEAS_TAX_2026",
        "rule_name": "해외 ETF 과세 (국내 상장)",
        "description": "매매차익 배당소득세 15.4%, 분배금 배당소득세 15.4%, 연 2,000만원 초과 시 종합과세",
        "effective_year": 2026,
        "source": "국세청",
    },
    {
        "key": "PENSION_ETF_2026",
        "rule_name": "연금계좌 ETF 과세",
        "description": "운용 중 과세 이연, 수령 시 연금소득세 3.3~5.5% (연 1,500만원 이하), 초과 시 종합과세 또는 16.5% 분리과세 선택",
        "effective_year": 2026,
        "source": "국세청",
    },
]

REGULATIONS = [
    {
        "key": "FIN_AD_RULE",
        "name": "금융투자협회 광고 규정",
        "summary": "투자 권유 표현 금지, 확정 수익 보장 금지, 원금 손실 가능성 고지 의무",
        "applicable_to": "ETF 콘텐츠 마케팅",
        "source": "금융투자협회",
    },
    {
        "key": "ETF_LEVERAGE_EDUCATION",
        "name": "레버리지 ETF 의무교육",
        "summary": "레버리지·인버스 ETF 최초 매수 시 투자자 의무교육 이수 필요 (증권사별 온라인 교육 제공)",
        "applicable_to": "레버리지/인버스 ETF",
        "source": "금융위원회",
    },
]


def seed_products(wiki: WikiStore) -> int:
    products = fetch_all_etf_products()
    if not products:
        logger.error("ETF 상품 수집 실패")
        return 0
    return wiki.upsert_products_from_api(products)


def seed_tax_rules(wiki: WikiStore) -> int:
    count = 0
    for rule in TAX_RULES:
        wiki.upsert("tax_rule", rule["key"], rule, source=rule["source"])
        count += 1
    logger.info("[Wiki] 세제 정보 %d개 저장", count)
    return count


def seed_regulations(wiki: WikiStore) -> int:
    count = 0
    for reg in REGULATIONS:
        wiki.upsert("regulation", reg["key"], reg, source=reg["source"])
        count += 1
    logger.info("[Wiki] 규제 정보 %d개 저장", count)
    return count


def main() -> None:
    wiki = WikiStore(DB_PATH)

    print("=" * 60)
    print("ETF Wiki 시드 시작")
    print("=" * 60)

    n_products = seed_products(wiki)
    n_tax = seed_tax_rules(wiki)
    n_reg = seed_regulations(wiki)

    print(f"\n완료:")
    print(f"  ETF 상품: {n_products}개")
    print(f"  세제 정보: {n_tax}개")
    print(f"  규제 정보: {n_reg}개")

    # 검증
    print(f"\n검증 -시총 상위 5:")
    for p in wiki.get_top_by_market_cap(5):
        print(f"  {p['code']} {p['name']} ({p['operator']}) 시총={p.get('market_cap', 0):,}억")

    print(f"\n검증 -'레버리지' 검색:")
    for p in wiki.search_products(["레버리지"], top_k=5):
        print(f"  {p['code']} {p['name']} ({p['operator']})")

    print(f"\n검증 -세제:")
    for r in wiki.get_all("tax_rule"):
        print(f"  {r['rule_name']}: {r['description'][:50]}...")


if __name__ == "__main__":
    main()
