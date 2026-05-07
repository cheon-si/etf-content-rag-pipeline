"""네이버 금융 API 기반 ETF 전종목 데이터 수집."""
from __future__ import annotations

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

NAVER_ETF_API = "https://finance.naver.com/api/sise/etfItemList.nhn"

OPERATOR_MAP = {
    "KODEX": "삼성자산운용",
    "TIGER": "Acme Asset Management",
    "KBSTAR": "KB자산운용",
    "ACE": "한국투자신탁운용",
    "HANARO": "NH아문디자산운용",
    "ARIRANG": "한화자산운용",
    "KOSEF": "키움투자자산운용",
    "SOL": "신한자산운용",
    "TIMEFOLIO": "타임폴리오자산운용",
    "PLUS": "한화자산운용",
    "RISE": "KB자산운용",
    "WON": "우리자산운용",
    "BNK": "BNK자산운용",
    "파워": "교보악사자산운용",
    "히어로즈": "키움투자자산운용",
}

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _extract_operator(name: str) -> str:
    for prefix, operator in OPERATOR_MAP.items():
        if name.startswith(prefix):
            return operator
    return "기타"


def fetch_all_etf_products() -> list[dict]:
    """네이버 금융 ETF API에서 전종목 시세 수집 후 표준 포맷으로 반환."""
    try:
        params = {"etfType": "0", "targetColumn": "market_sum", "sortOrder": "desc"}
        resp = requests.get(NAVER_ETF_API, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("result", {}).get("etfItemList", [])
        logger.info("[NaverETF] %d건 수집", len(items))
    except Exception as exc:
        logger.error("[NaverETF] 수집 실패: %s", exc)
        return []

    products = []
    for item in items:
        code = item.get("itemcode", "").strip()
        name = item.get("itemname", "").strip()
        if not code or not name:
            continue

        products.append({
            "code": code,
            "name": name,
            "operator": _extract_operator(name),
            "nav": float(item.get("nav", 0) or 0),
            "market_cap": int(item.get("marketSum", 0) or 0),
            "price": int(item.get("nowVal", 0) or 0),
            "volume": int(item.get("amonut", 0) or 0),
            "change_rate": float(item.get("changeRate", 0) or 0),
            "three_month_return": float(item.get("threeMonthEarnRate", 0) or 0),
            "updated_at": datetime.now().strftime("%Y-%m-%d"),
        })

    logger.info("[NaverETF] ETF 상품 %d개 파싱 완료", len(products))
    return products


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    products = fetch_all_etf_products()
    if products:
        print(f"\n수집 완료: {len(products)}개 ETF")
        operators = {}
        for p in products:
            operators[p["operator"]] = operators.get(p["operator"], 0) + 1
        print("\n운용사별 종목 수:")
        for op, cnt in sorted(operators.items(), key=lambda x: -x[1])[:10]:
            print(f"  {op}: {cnt}개")
        print(f"\n시가총액 상위 10:")
        for p in products[:10]:
            print(f"  {p['code']} {p['name']} ({p['operator']}) 시총={p['market_cap']:,}억")
