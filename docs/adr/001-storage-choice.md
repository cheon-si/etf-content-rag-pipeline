# ADR-001: SQLite + FAISS 조합 (Graph DB 미도입)

**Status**: Accepted
**Date**: 2026-05
**Decision makers**: 시원 (DX/AX)

## Context

ETF 콘텐츠 자동화 파이프라인에서 두 종류의 데이터를 저장·검색해야 했다:

1. **구조화 데이터**: ETF 종목 1,099개의 메타(시세, 운용사, 테마, TER, 기초자산 등) + 세제 6건 + 규제 2건 → key-value 스타일 lookup이 주
2. **비정형 데이터**: 블로그 ~980건, 뉴스 ~818건, 과거 LLM 산출물 → 시맨틱 유사도 검색이 주

검토한 후보:
- **A. Postgres + pgvector**: 단일 DB로 모두 처리, 운영 표준
- **B. SQLite + FAISS** (선택)
- **C. Neo4j / Kuzu (Graph DB)**: ETF↔테마↔운용사 관계 모델링
- **D. Pinecone / Weaviate**: SaaS 벡터 DB

## Decision

**SQLite (Wiki) + FAISS (Vector) 조합** 채택.

- Wiki(SQLite): `wiki_entries(domain, key, data JSON)` 단일 테이블 + UPSERT 기반
- Vector(FAISS): collection(blog/news/past_output)별 IndexFlatIP, 메타데이터는 SQLite `rag_documents` 테이블에 별도 보관

## Rationale

### 왜 Postgres가 아니었나
- 단일 사용자 + 주 1회 배치 워크로드 → 동시성·서버 운영 불필요
- 운영 부담(Postgres 인스턴스 관리, 백업, 권한)이 가치를 능가
- 데이터 규모(수천 건)가 SQLite 활용 영역의 1만분의 1 미만

### 왜 Graph DB가 아니었나 (가장 많이 고민한 선택지)
ETF 도메인은 그래프와 궁합이 매우 좋다:
- `ETF ─운용─ 운용사`, `ETF ─테마─ 테마`, `ETF ─기초자산─ 자산군`
- "이 클러스터에 자주 함께 등장하는 운용사 + 환헤지 ETF만, TER 0.5% 이하" 같은 다중 홉 질의에 강함

**그럼에도 도입하지 않은 이유**:
1. 현재 질의 패턴 분석 결과, 다중 홉 질의가 **0회/주** — 모두 단순 lookup 또는 시맨틱 검색
2. JSON 필드 + SQL CTE만으로도 2홉까지는 충분
3. Kuzu는 매력적이나 의존성 추가 + 마이그레이션 비용 > 현 시점 가치
4. **트리거 조건을 정의해두고 도입 시점만 늦췄다**:
   - LLM이 다중 조건 ETF 추천을 자주 잘못함
   - 키워드↔ETF↔운용사 연관 분석이 반복적으로 필요
   - 코퍼스가 1만 건 이상 누적
   - 위 중 2개 이상 발생 시 Kuzu(임베디드 그래프 DB)로 전환

### 왜 SaaS 벡터 DB가 아니었나
- 데이터 외부 전송에 따른 컴플라이언스 검토 필요 (금융 도메인)
- 월 비용 vs 로컬 FAISS 무료
- 1만 벡터 미만 규모에선 IndexFlatIP가 정확도·속도 모두 충분

### 핵심 원칙
> **"규모가 도구를 정당화할 때까지 기다린다."**
> 미래에 필요할지도 모를 도구를 미리 도입하면 운영 부채만 늘어난다. 트리거 기준을 명시해두고, 그 기준이 충족되는 순간 옮긴다.

## Consequences

**Positive**:
- 단일 파일 DB → 백업·이관·재현이 `cp etf_trend.db backup.db` 한 줄
- 의존성 최소: SQLite 표준 + FAISS 1개 라이브러리
- 인턴 종료 후 인계받는 사람도 바로 이해 가능

**Negative**:
- 수평 확장 불가 (필요 시점에 Postgres로 마이그레이션 필요)
- 다중 홉 그래프 질의 못 함 (트리거 시 Kuzu 추가)
- 동시 쓰기 불가 (현재 워크로드에선 무관)

**Neutral**:
- DB 2개로 분리되어 있음 (`etf_trend.db`, `etf_trend_news.db`) — 통합은 별도 결정으로 유보

## Trigger to Revisit

- 사용자 5명 이상 동시 조회 발생
- 데이터 규모 > 100만 건
- 다중 홉 그래프 질의 주 5회 이상
- 클라우드 대시보드 요구
