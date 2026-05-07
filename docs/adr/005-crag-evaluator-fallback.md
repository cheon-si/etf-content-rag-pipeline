# ADR-005: CRAG-style Retrieval Evaluator + 동적 Fallback

**Status**: Proposed
**Date**: 2026-05-07
**Decision makers**: 시원 (DX/AX)

## Context

[ADR-003](003-vector-noise-cutoff.md)에서 vector 검색에 `min_score=0.4` 컷오프를 도입해 무관 결과를 제거했다. 1주 운영 후 다음 두 케이스가 잠재 이슈로 남아있다:

1. **False positive (관련 있어 보이는데 사실 무관)**: FAISS score가 0.4를 넘지만 실제 ETF 콘텐츠가 아닌 일반 시황·블로그가 통과될 수 있음. 점수만으론 의미 평가 불가.
2. **Empty fallback (검색 결과 0건)**: 컷오프로 모든 결과가 잘리면 RAG 컨텍스트가 비어 LLM이 자기 지식만으로 답변 → hallucination 위험.

CRAG (Yan et al., 2024)는 같은 문제를 retrieval evaluator + 동적 fallback으로 해결. 본 시스템에 단순화·적용한다.

## Decision

`vector_store.search()` 결과를 받은 직후 **3단계 처리**:

```
검색 결과 (min_score=0.4 통과한 N건)
   │
   ▼
[1] LLM Evaluator (Sonnet 1회 호출)
   "이 query에 대해 각 결과의 관련도를 high/mid/low로 분류"
   │
   ▼
[2] 분류별 처리
   high (≥1건)    → 그대로 사용 (현재 동작)
   mid only       → wiki에서 query 키워드로 추가 ETF lookup → 결합
   low or 0건     → fallback: keyword 단순화 또는 wiki only
   │
   ▼
[3] 최종 컨텍스트 → LLM
```

## Implementation Plan

### 변경 파일
1. **`llm_pipeline/rag/vector_store.py`**
   - `search()` 시그니처 유지 (호환성)
   - 새 메서드 `search_with_evaluation(query, collection, top_k, evaluator_fn)` 추가

2. **`llm_pipeline/rag/evaluator.py`** (신규)
   - `evaluate_relevance(query: str, results: list[dict]) -> list[Literal['high', 'mid', 'low']]`
   - Anthropic Sonnet 호출, JSON 응답
   - 입력당 ~$0.001 (소량 토큰)

3. **`llm_pipeline/rag/context_builder.py`**
   - 5개 stage 빌더 모두 `search()` → `search_with_evaluation()` 전환
   - mid/low 케이스 fallback 로직 추가

### 평가 prompt 초안

```python
EVALUATOR_PROMPT = """주어진 query에 대해 각 검색 결과의 관련도를 분류하시오.

Query: {query}

검색 결과:
{results}

각 결과를 다음 중 하나로 분류:
- high: query 주제와 직접 관련, 콘텐츠 작성에 유용
- mid: 관련은 있으나 보조 자료 수준
- low: query와 무관하거나 노이즈

JSON 배열로만 응답: [{"id": 0, "label": "high"}, ...]
"""
```

### Fallback 로직

```python
def _resolve_results(query, results, labels):
    high = [r for r, l in zip(results, labels) if l == "high"]
    mid  = [r for r, l in zip(results, labels) if l == "mid"]

    if high:
        return high  # CRAG: Correct → 그대로
    if mid:
        # CRAG: Ambiguous → wiki 보강
        wiki_extra = wiki.search_products(query.split()[:3], top_k=3)
        return mid + [_to_doc(p) for p in wiki_extra]
    # CRAG: Incorrect → fallback
    # 옵션 a: query 단순화 후 재검색
    # 옵션 b: wiki only로 컨텍스트 채우기 (안전)
    return [_to_doc(p) for p in wiki.get_top_by_market_cap(5)]
```

## Rationale

### 왜 LLM evaluator인가 (T5/BERT가 아니라)
- CRAG 원본은 T5-large fine-tune. 학습 비용·인프라 부담.
- 본 시스템은 이미 Sonnet 사용 중 → 추가 모델 운영 X
- 1 회당 evaluator 비용 ~$0.001 (입력 ~500 토큰, 출력 ~50 토큰)
- 4 클러스터 × stage 4~5개 호출 = **회당 ~$0.02 추가** (전체 $2 대비 1%)

### 왜 ternary(3등급)인가
- Binary(0/1)는 현재 `min_score=0.4`와 동일 → 추가 가치 없음
- 5등급은 LLM 분류 정확도·일관성 떨어짐
- 3등급(high/mid/low)이 실용적 sweet spot

### 왜 mid 케이스에 wiki 결합인가
- 본 시스템 강점은 **wiki(structured) + vector(unstructured) hybrid**
- mid 결과만으론 약하지만 wiki 1099 ETF로 보강 가능
- 외부 web search fallback(CRAG 원본)은 컴플라이언스·비용 모두 부담

### 핵심 원칙
> **"검색 결과를 신뢰할지 LLM이 결정한다 — score는 첫 게이트, 의미 평가가 두 번째 게이트."**

## Consequences

**Positive**:
- 노이즈 통과 비율 추가 감소 (예상: 95% → 99%)
- 결과 0건 케이스에서도 wiki fallback으로 컨텍스트 보장
- 향후 다른 컬렉션(news, past_output) 도입 시 동일 패턴 재사용

**Negative**:
- 회당 비용 ~1% 증가 ($2 → $2.02)
- 검색 latency 증가 (현재 ~50ms → ~500ms, evaluator LLM 호출)
- prompt-based evaluator는 LLM 변경 시 재검증 필요

**Neutral**:
- min_score=0.4 컷오프는 유지 (1차 필터). evaluator는 2차 게이트.

## Validation Plan

배포 후 다음 메트릭 추적 (1주):

| Metric | Baseline (ADR-003) | Target |
|---|---|---|
| 검색 결과 0건 → LLM 답변 hallucination 사례 | TBA | 0 |
| 노이즈 통과율 (수동 검수 기준) | ~5% | <1% |
| 회당 비용 | $2.0 | <$2.10 |
| 검색 latency p95 | ~50ms | <800ms |

## Trigger to Revisit

- 회당 비용이 $0.5 이상 추가 증가 (LLM 가격 상승 등)
- LLM evaluator 응답이 일관되지 않음 (label flip rate >10%)
- T5/BERT-based reranker 오픈소스 충분히 성숙 → 자체 모델로 교체 검토

## Related

- [ADR-003: Vector noise cutoff (이 ADR의 전 단계)](003-vector-noise-cutoff.md)
- [CRAG 논문 정리](../research/rag-papers.md#3-crag--corrective-retrieval-augmented-generation--현재-시스템의-자연스러운-다음-단계)
- 향후 [ADR-006: GraphRAG hybrid retrieval] 와 결합 시 evaluator는 graph traversal 결과에도 적용
