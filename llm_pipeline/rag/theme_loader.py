"""LSEG 엑셀 → Wiki product entries에 themes/총보수/복제방법/기초자산/환헤지 주입.

운영 모델:
  - 1회: snapshot_lseg_to_json(엑셀)로 고정 메타만 JSON으로 박제
  - 매주: load_etf_metadata_from_snapshot()로 JSON에서 wiki 주입 (엑셀 불필요)
  - 변동값(순자산총액·거래량)은 박제하지 않음 — 네이버 API가 매주 갱신함
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llm_pipeline.rag.wiki import WikiStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")
# 1회용 박제 시 엑셀 경로. 매주 운영은 SNAPSHOT_JSON_PATH에서 로드 (이 경로는 평소엔 미사용).
# 신규 ETF 반영 등 재박제 필요 시 이 경로에 LSEG 엑셀 두고
# `python -m llm_pipeline.rag.theme_loader snapshot` 실행.
EXCEL_PATH = str(_PROJECT_ROOT / "data" / "raw" / "lseg.xlsx")
SNAPSHOT_JSON_PATH = _PROJECT_ROOT / "data" / "lseg_static_metadata.json"

STATIC_FIELDS = ("themes", "ter", "replication", "base_market", "base_asset", "hedge_type")

_HEDGE_PATTERN = re.compile(r"\((?:합성)?H\)|\(H\)")
_SYNTHETIC_PATTERN = re.compile(r"\(합성\)|\(합성H\)")


def _detect_hedge_type(name: str) -> str:
    """종목명에서 환헤지/합성 분류 추출."""
    if _HEDGE_PATTERN.search(name):
        return "환헤지"
    if _SYNTHETIC_PATTERN.search(name):
        return "합성"
    return "환노출"


def load_etf_metadata_from_excel(excel_path: str = EXCEL_PATH) -> dict[str, dict]:
    """엑셀에서 종목코드 → 메타데이터(themes, ter, 복제방법, 기초자산 등) 추출."""
    df = pd.read_excel(excel_path)
    df["code"] = df["종목번호"].astype(str).str.lstrip("A")
    df["theme"] = df["테마중분류한글명"].astype(str).str.strip()

    metadata: dict[str, dict] = {}
    themes_map: dict[str, set[str]] = defaultdict(set)

    for _, row in df.iterrows():
        code = row["code"]
        if not code:
            continue
        theme = row["theme"]
        if theme and theme != "nan":
            themes_map[code].add(theme)

        if code not in metadata:
            metadata[code] = {
                "ter": float(row["총보수"]) if pd.notna(row["총보수"]) else None,
                "replication": str(row["복제방법"]) if pd.notna(row["복제방법"]) else None,
                "base_market": str(row["기초시장분류"]) if pd.notna(row["기초시장분류"]) else None,
                "base_asset": str(row["기초자산분류"]) if pd.notna(row["기초자산분류"]) else None,
                "lseg_aum": int(row["순자산총액"]) if pd.notna(row["순자산총액"]) else None,
                "lseg_volume": int(row["거래량"]) if pd.notna(row["거래량"]) else None,
                "hedge_type": _detect_hedge_type(str(row["종목명"])),
            }

    for code, themes in themes_map.items():
        if code in metadata:
            metadata[code]["themes"] = sorted(themes)

    return metadata


def snapshot_lseg_to_json(
    excel_path: str = EXCEL_PATH,
    json_path: Path = SNAPSHOT_JSON_PATH,
) -> int:
    """LSEG 엑셀 → 고정 메타데이터만 추출해서 프로젝트 내 JSON으로 박제.

    1회만 실행. 변동값(순자산총액·거래량) 제외.
    """
    metadata = load_etf_metadata_from_excel(excel_path)
    static_only = {
        code: {k: meta[k] for k in STATIC_FIELDS if meta.get(k) is not None}
        for code, meta in metadata.items()
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(static_only, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[Snapshot] %d개 종목 → %s", len(static_only), json_path)
    return len(static_only)


def load_etf_metadata_from_snapshot(
    json_path: Path = SNAPSHOT_JSON_PATH,
) -> dict[str, dict]:
    """박제된 JSON에서 종목코드 → 고정 메타데이터 로드. 파일 없으면 FileNotFoundError."""
    if not json_path.exists():
        raise FileNotFoundError(f"LSEG 스냅샷 JSON 없음: {json_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def main() -> None:
    print("=" * 60)
    print("LSEG 메타데이터 → Wiki 주입 (테마 + TER + 복제방법 + 환헤지)")
    print("=" * 60)

    metadata = load_etf_metadata_from_excel()
    print(f"\n엑셀 로드: {len(metadata)}개 종목")

    wiki = WikiStore(DB_PATH)
    n_updated = wiki.update_product_metadata(metadata)
    print(f"\nWiki 업데이트: {n_updated}개 상품에 메타데이터 주입 완료")

    # 검증
    print("\n검증 - '레버리지2X' 테마 + 총보수/복제방법 표시:")
    for p in wiki.search_products_by_theme(["레버리지2X"], top_k=5):
        print(f"  {p['code']} {p['name']}")
        print(f"    TER={p.get('ter')}% | 복제={p.get('replication')} | "
              f"환헤지={p.get('hedge_type')} | 자산={p.get('base_asset')}")
        print(f"    테마: {p.get('themes', [])[:5]}")

    print("\n검증 - 환헤지 ETF 검색:")
    hedged = wiki.search_by_hedge_type("환헤지", top_k=5)
    for p in hedged:
        print(f"  {p['code']} {p['name']} | TER={p.get('ter')}%")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        excel = sys.argv[2] if len(sys.argv) > 2 else str(_PROJECT_ROOT / "data" / "raw" / "lseg.xlsx")
        n = snapshot_lseg_to_json(excel, SNAPSHOT_JSON_PATH)
        print(f"[snapshot] {n}개 종목 → {SNAPSHOT_JSON_PATH}")
    else:
        main()
