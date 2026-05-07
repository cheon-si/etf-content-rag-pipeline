# ADR-002: LSEG 메타데이터 JSON 박제 패턴

**Status**: Accepted
**Date**: 2026-05-07
**Decision makers**: 시원 (DX/AX)

## Context

LSEG ETF 메타데이터(테마, TER, 복제방법, 환헤지 등)를 매주 갱신하던 운영 모델에 두 가지 문제:

1. **운영 부담**: LSEG 엑셀이 회사 DRM 환경에 묶여있어, 사람이 매주 수동으로 다른이름저장한 뒤 D 드라이브에 둬야 함
2. **무결성 위험**: 사람이 한 번이라도 잊으면 RAG가 LSEG 메타 없이 동작. 검증 결과 실제로 **LSEG 적용률이 0%인 상태로 한동안 운영되고 있었음** (메모리에는 적용됐다고 기록되어 있었음에도)

LSEG 데이터를 분해해보면:
- **고정값** (themes, ter, replication, base_market, base_asset, hedge_type) — 종목 신규 상장/상폐 외엔 변하지 않음
- **변동값** (lseg_aum, lseg_volume) — 매주 변하지만 네이버 금융 API가 이미 제공

## Decision

LSEG 엑셀에서 **고정값만 JSON으로 박제**하여 git에 커밋. 매주 파이프라인은 박제 JSON에서 wiki에 주입.

```
1회 (또는 연 1~2회 신규 ETF 반영 시):
  data/raw/lseg.xlsx 둠
  python -m llm_pipeline.rag.theme_loader snapshot
  → data/lseg_static_metadata.json 생성 (1099 종목, 6 필드, 320KB)

매주 (자동):
  Step 9.5에서 load_etf_metadata_from_snapshot() 호출
  → wiki에 주입
```

변동값은 박제하지 않음. 네이버 API가 매주 시세·시총·거래량을 갱신.

## Rationale

### "변동값/고정값을 분리한다"는 인사이트
- 운영 부담의 원인이 데이터 자체가 아니라 **데이터의 변경 빈도와 공급 채널의 미스매치**였음
- LSEG 전체를 매주 받으려 하니 부담. 하지만 매주 변하는 부분은 어차피 다른 채널이 더 잘 줌.
- 변동성에 따라 채널을 분리:
  - 고정값 → 박제 (1회)
  - 변동값 → API (매주)

### 왜 git에 커밋하는가
- JSON 320KB. git이 처리하기에 충분히 작음
- 데이터·코드 함께 버전 관리 → 재현성 확보
- 인계받는 사람이 clone 후 바로 실행 가능

### 왜 엑셀을 매주 자동 다운로드하지 않는가
- LSEG는 사내 DRM에 묶여있어 자동화 자체가 불가능
- 자동화하려면 별도 시스템 도입(권한, 보안 검토) → 가치 대비 과잉

### 핵심 원칙
> **"운영 부담의 원인이 데이터인지, 데이터의 변경 빈도인지 분리해서 본다."**
> 모든 데이터를 같은 빈도로 갱신할 필요는 없다. 변동성이 다른 데이터는 다른 채널·다른 주기로 처리한다.

## Implementation

```python
STATIC_FIELDS = ("themes", "ter", "replication", "base_market", "base_asset", "hedge_type")

def snapshot_lseg_to_json(excel_path, json_path):
    """LSEG 엑셀 → 고정 메타만 추출해서 JSON으로 박제. 1회만 실행."""
    metadata = load_etf_metadata_from_excel(excel_path)
    static_only = {
        code: {k: meta[k] for k in STATIC_FIELDS if meta.get(k) is not None}
        for code, meta in metadata.items()
    }
    json_path.write_text(json.dumps(static_only, ensure_ascii=False, indent=2))

def load_etf_metadata_from_snapshot(json_path):
    """매주 호출: 박제 JSON → wiki 주입용 dict."""
    return json.loads(json_path.read_text(encoding="utf-8"))
```

## Consequences

**Positive**:
- 매주 운영 작업 1개 제거 (엑셀 다른이름저장 → 불필요)
- 무결성 위험 영구 제거 (사람이 잊을 수 있는 단계 자체가 사라짐)
- 인계 용이 (`git clone` 후 바로 동작)
- 검증 결과: 적용률 0% → 100% (1099/1099)

**Negative**:
- 신규 ETF 상장 시(연 1~2회) 박제 갱신 필요 — `data/raw/lseg.xlsx` 두고 1줄 명령
- 박제 시점과 현재 시점 사이에 신규 상장된 ETF는 메타 누락 (다음 박제까지 기다려야 함)

**Neutral**:
- JSON 파일이 git에 들어감 → 데이터 변경 추적 가능 (장점)이지만 PR 시 diff가 큼 (단점)

## Validation

박제 직후 wiki 검증 결과:

| Field | Coverage |
|---|---|
| TER | 1099/1099 (100%) |
| Themes | 1099/1099 (100%) |
| Replication | 1099/1099 (100%) |
| Base market/asset | 1099/1099 (100%) |
| Hedge type | 환헤지 63 / 환노출 966 / 합성 70 |

테마 검색(`레버리지2X`, `K-반도체`, `AI`) 모두 정상 결과 반환 (박제 전: 0건).

## Related

- [ADR-001: SQLite + FAISS 조합](001-storage-choice.md)
