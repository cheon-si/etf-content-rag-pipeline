# GraphRAG PoC 설계 — Kuzu + 본 시스템 wiki 활용

**Status**: Design / Pre-implementation
**Date**: 2026-05-07
**Target sprint**: 다음 주 (2026-05-12 ~ 2026-05-18)

## 한 줄 요약

> Microsoft GraphRAG의 정신을 본 시스템에 적용하되, **이미 가진 자산(LSEG 박제 1099 ETF + 메타 6필드)을 활용해 가장 비싼 단계인 entity·relationship 추출을 90% 생략**한 경량 버전.

## 목표

- ETF 콘텐츠 생성 시 **다중 홉·집계 query**를 효과적으로 처리
  - 예: "K-반도체 테마에서 환헤지 + TER 0.5% 이하 ETF의 운용사 다양성"
  - 예: "이번 주 키워드와 자주 함께 등장한 운용사들의 신상품 비교"
- 현재 stage별 context builder의 **product 검색을 graph traversal로 강화**

## Non-goals

- Microsoft GraphRAG 라이브러리 그대로 사용 X (무겁고 비쌈)
- LLM entity extraction 단계 X (이미 wiki에 정형 데이터 있음)
- 실시간 graph mutation X (주간 배치로 충분)

---

## 설계

### 데이터 소스 → Graph 매핑

```
[Wiki (SQLite)]                       [Knowledge Graph (Kuzu)]
─────────────────                     ─────────────────────
product (1099)        ────────►       :ETF (1099 nodes)
  - operator                            properties: code, name,
  - market_cap                          market_cap, ter, etc.
  - themes []
  - replication                       :Operator (~30 nodes)
  - hedge_type                          (TIGER → 미래에셋자산운용 등)
  - base_asset

tax_rule (6)          ────────►       :TaxRule (6 nodes)
regulation (2)        ────────►       :Regulation (2 nodes)

[Vector (FAISS)]
─────────────────
blog (980)
news (818)            ────────►       :Document (~1800 nodes)
past_output (19)                        properties: collection, doc_id,
                                        title, post_date

[Edges (자동 도출)]
ETF -[:OPERATED_BY]-> Operator
ETF -[:HAS_THEME]-> Theme         (M:N, 평균 5.1개/ETF)
ETF -[:BASE_ASSET]-> AssetClass
ETF -[:HEDGE_TYPE]-> HedgeType
Document -[:MENTIONS]-> ETF       (코드/이름 매칭)
Document -[:MENTIONS]-> Theme     (간단 keyword 매칭)
Theme -[:RELATED_TO]-> Theme      (co-occurrence 기반, weight)
```

### 엔티티·관계 도출 방식 (LLM 호출 0회)

| 엔티티/관계 | 도출 소스 | 비용 |
|---|---|---|
| `:ETF` 노드 | wiki product 1099개 그대로 | 0 |
| `:Operator` 노드 | wiki의 `operator` 필드 distinct | 0 |
| `:Theme` 노드 | LSEG 박제의 `themes` 배열 distinct | 0 |
| `:AssetClass`, `:HedgeType` | 박제 `base_asset`, `hedge_type` distinct | 0 |
| `:OPERATED_BY` 엣지 | product[operator] | 0 |
| `:HAS_THEME` 엣지 | product[themes] 풀어서 | 0 |
| `:BASE_ASSET`, `:HEDGE_TYPE` 엣지 | 동일 | 0 |
| `:MENTIONS` 엣지 (Doc → ETF) | 본문에 ETF 코드/이름 정규식 매칭 | 0 (코드만) |
| `:RELATED_TO` 엣지 (Theme co-occurrence) | LSEG에서 같은 ETF가 가진 테마 쌍 카운트 | 0 |

→ **모든 엣지 도출이 결정론적, LLM 0회**. Microsoft GraphRAG는 LLM extraction에 회당 수백 달러 쓰는데, 본 케이스는 0원.

---

## 컴포넌트

### 신규 파일

```
llm_pipeline/rag/
├── graph/                          # NEW
│   ├── __init__.py
│   ├── builder.py                  # Wiki → Kuzu 그래프 빌드 (1회/주)
│   ├── store.py                    # KuzuStore: open/query 래퍼
│   ├── queries.py                  # 자주 쓰는 Cypher 쿼리 모음
│   └── community.py                # 테마/자산군 community summary
├── context_builder.py              # MODIFIED: graph_search 추가
└── ...
```

### Kuzu 스키마

```cypher
-- Node tables
CREATE NODE TABLE ETF(
    code STRING PRIMARY KEY,
    name STRING,
    market_cap INT64,
    ter DOUBLE,
    three_month_return DOUBLE
);
CREATE NODE TABLE Operator(name STRING PRIMARY KEY);
CREATE NODE TABLE Theme(name STRING PRIMARY KEY, etf_count INT64);
CREATE NODE TABLE AssetClass(name STRING PRIMARY KEY);
CREATE NODE TABLE HedgeType(name STRING PRIMARY KEY);
CREATE NODE TABLE Document(
    doc_id STRING PRIMARY KEY,
    collection STRING,
    title STRING,
    post_date STRING
);

-- Rel tables
CREATE REL TABLE OPERATED_BY(FROM ETF TO Operator);
CREATE REL TABLE HAS_THEME(FROM ETF TO Theme);
CREATE REL TABLE BASE_ASSET(FROM ETF TO AssetClass);
CREATE REL TABLE HEDGE_TYPE(FROM ETF TO HedgeType);
CREATE REL TABLE MENTIONS(FROM Document TO ETF);
CREATE REL TABLE MENTIONS_THEME(FROM Document TO Theme);
CREATE REL TABLE RELATED_TO(FROM Theme TO Theme, weight DOUBLE);
```

### 핵심 Cypher 쿼리 예시

**Q1. 특정 테마의 환헤지 ETF, TER 정렬**
```cypher
MATCH (e:ETF)-[:HAS_THEME]->(t:Theme {name: 'K-반도체'}),
      (e)-[:HEDGE_TYPE]->(h:HedgeType {name: '환헤지'})
RETURN e.code, e.name, e.ter, e.market_cap
ORDER BY e.ter ASC LIMIT 10;
```

**Q2. 운용사 다양성 (테마 기준)**
```cypher
MATCH (o:Operator)<-[:OPERATED_BY]-(e:ETF)-[:HAS_THEME]->(t:Theme {name: 'AI'})
RETURN o.name, count(e) AS etf_count
ORDER BY etf_count DESC;
```

**Q3. 키워드와 함께 자주 등장하는 ETF (multi-hop)**
```cypher
MATCH (d:Document)-[:MENTIONS]->(e:ETF)-[:HAS_THEME]->(t:Theme),
      (d2:Document)-[:MENTIONS]->(e)
WHERE d.post_date >= '2026-04-01'
RETURN t.name, count(DISTINCT d) AS doc_count
ORDER BY doc_count DESC LIMIT 5;
```

---

## Stage별 통합

기존 `context_builder.py`의 5개 stage를 다음과 같이 강화:

| Stage | 현재 | + Graph |
|---|---|---|
| `s3_cluster` | wiki.search_products + vector blog | + 키워드→테마→ETF 그래프 traversal |
| `s4_draft` | wiki + 세제 + blog | + 같은 테마의 다른 운용사 ETF (다양성 보강) |
| `s4_factcheck` | wiki + 세제 + 규제 + news | + ETF↔뉴스 :MENTIONS 관계로 정확한 출처 |
| `content_ideas` | wiki + past_output | + community summary (테마별 거시 동향) |
| `content_brief` | 세제 + 규제 + 시총상위 | + 테마 RELATED_TO 그래프 (확장 주제 발굴) |

---

## 구현 단계 (1주 sprint)

### Day 1 — Kuzu 환경 + 스키마
- `pip install kuzu`
- `KuzuStore` 클래스 (open, query, close)
- 위 스키마 생성 스크립트
- 검증: 빈 DB에 sample 노드 5개 추가/조회

### Day 2 — Wiki → Kuzu 빌더
- `builder.py`: WikiStore에서 product 1099개 읽어 ETF + Operator + Theme + AssetClass + HedgeType 노드/엣지 생성
- 검증: count(ETF)=1099, count(Theme)=176, sum(HAS_THEME)≈5610

### Day 3 — Document → ETF mention 엣지
- 블로그·뉴스 본문에서 ETF 코드(6자리) 정규식 매칭 → `:MENTIONS` 엣지
- 검증: 톱5 멘션 ETF가 시총 상위와 일치하는지

### Day 4 — Theme co-occurrence + community
- 같은 ETF가 가진 테마 쌍 → `:RELATED_TO` 엣지 (weight=co-occurrence count)
- Theme별 ETF 그룹화 → community summary (LLM 1회씩, ~$0.5)

### Day 5 — context_builder 통합
- 5개 stage 중 `s3_cluster` + `content_brief` 먼저 graph 호출 추가
- A/B 비교: graph 사용/미사용 콘텐츠 품질 측정

### Day 6-7 — 검증 + 정리
- 회당 비용·latency 측정
- ADR-006 작성 (도입 결과 기반 정식 결정)

---

## 비용 예측

| 항목 | 예상값 |
|---|---|
| Kuzu 디스크 사용 | ~50 MB (1099 ETF + ~1800 doc + 엣지) |
| 빌드 시간 (주 1회) | ~30초 |
| Query latency (단일 hop) | <10ms |
| Query latency (3-hop) | <50ms |
| Community summary LLM 비용 (주 1회) | ~$0.5 (테마 30개 × Sonnet) |
| 회당 추가 비용 | ~$0.5/주 (community refresh) + $0.05/회 (LLM에 graph context 추가) |

→ **현재 회당 $2 → 약 $2.05** (2.5% 증가). LLM 호출 1회 추가 vs 다중홉 query 능력 확보.

---

## 성공 기준

PoC 종료 시 다음 중 **3개 이상** 충족 시 정식 도입:

- [ ] 다중홉 query 5종이 단일 Cypher로 처리됨
- [ ] 본 시스템 stage 1개라도 graph 활용 후 콘텐츠 품질 메트릭 향상
  - 운용사 다양성 추가 개선
  - 또는 구체 수치 등장 빈도 추가 증가
- [ ] 회당 비용 증가 <5%
- [ ] Query latency p95 <100ms
- [ ] community summary가 콘텐츠 브리프 품질에 기여 (수동 검수)

---

## 위험과 대응

| 위험 | 대응 |
|---|---|
| Kuzu가 한국어 노드 이름에 약함 | latin 코드 사용, 한국어는 properties로만 |
| Document → ETF 매칭 정확도 (오탐) | ETF 코드(6자리)만 1차 사용, 이름 매칭은 2단계 |
| 그래프 빌드가 매주 실패 | run_all.py Step 9.6으로 추가, 실패해도 vector RAG로 fallback |
| Kuzu 의존성 추가에 따른 운영 부담 | 임베디드라 단일 파일, 백업 단순 |

---

## ADR-001과의 일관성

[ADR-001](../adr/001-storage-choice.md)에서 Graph DB 도입 트리거 4개를 명시했다:
- 사용자 5명 이상 동시 조회
- 데이터 규모 > 100만 건
- 다중 홉 그래프 질의 주 5회 이상
- 클라우드 대시보드 요구

**현재 트리거 충족률 0/4**. 그러나 GraphRAG의 핵심 가치는 단순 graph DB가 아니라 **community summary 패턴**이고, 이는 트리거와 무관하게 콘텐츠 품질에 기여 가능. PoC로 효과 검증 후 정식 도입 결정.

---

## Related

- [RAG Papers Review § 4. GraphRAG](../research/rag-papers.md#4-graphrag-microsoft--다음-주-도입-예정--필독)
- [ADR-001: Storage choice — Graph DB 미도입 사유](../adr/001-storage-choice.md)
- [ADR-002: LSEG 박제 패턴 — Graph node 데이터 소스](../adr/002-lseg-snapshot-pattern.md)
- [Microsoft GraphRAG 원본](https://github.com/microsoft/graphrag)
- [Kuzu DB](https://kuzudb.com/)
