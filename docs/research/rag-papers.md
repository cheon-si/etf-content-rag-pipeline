# RAG 논문 5편 정리 — 본인 시스템 관점

> 운영 중인 ETF Content RAG Pipeline에 비추어 5편의 핵심 RAG 논문을 정리.
> 각 논문의 학술적 기여보다 **"내 시스템에 어디까지 적용 가능/필요한가"** 관점으로 작성.

## 한눈에 보는 비교표

| 논문 | 핵심 메커니즘 | 본 시스템 도입 ROI | 트리거 |
|---|---|---|---|
| HyDE (2022) | 가상 문서 생성 후 임베딩 | ⭐⭐ | 짧은 query 빈발 시 |
| Self-RAG (2023) | reflection token으로 검색·사용 self-evaluate | ⭐⭐⭐ | 비용·품질 더 짜낼 때 |
| **CRAG (2024)** | retrieval evaluator + 동적 fallback | ⭐⭐⭐⭐⭐ | **현재 노이즈 컷의 다음 단계** |
| **GraphRAG (2024)** | KG 추출 + community detection + summary | ⭐⭐⭐⭐⭐ | **다음 주 도입 예정** |
| RAG Survey (2023) | Naive/Advanced/Modular RAG 분류 | ⭐⭐⭐ | 좌표 확인용 |

---

## 1. HyDE — Hypothetical Document Embeddings

**Reference**: Gao et al., *"Precise Zero-Shot Dense Retrieval without Relevance Labels"*, 2022. [arXiv:2212.10496](https://arxiv.org/abs/2212.10496)

### 문제
- Query와 정답 document의 임베딩 분포가 다름 (질문 vs 답변 텍스트)
- Zero-shot dense retrieval에서 query embedding이 정답을 못 찾음

### 해법
```
[기존]  Query → Embedding → FAISS Search
[HyDE] Query → LLM(가상 답변 문서 생성) → Embedding → FAISS Search
```

핵심 통찰: **LLM이 만든 가상 문서는 정답 문서와 임베딩 공간에서 더 가깝다** (둘 다 "답변 형식"이라).

### 본 시스템 적용 분석
- 본 시스템 query는 `{cluster_name} {' '.join(keywords[:5])}` 형태 → 이미 ~10단어, doc-like
- **단어 1~2개짜리 짧은 query가 발생할 때만 효과적**. 현재는 그런 케이스 거의 없음
- 도입 시 비용: LLM 호출 1회 추가 (Sonnet 기준 ~$0.005/회)

### 도입 권장도: ⭐⭐
- **트리거**: cluster_name 추출 실패로 짧은 query만 가능한 케이스 빈발
- **대안**: query 합성 시 LLM에게 "검색 친화적으로 재작성" 한 번만 시키는 게 더 가성비

---

## 2. Self-RAG — Self-Reflective Retrieval-Augmented Generation

**Reference**: Asai et al., *"Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection"*, 2023. [arXiv:2310.11511](https://arxiv.org/abs/2310.11511)

### 문제
- 항상 검색하면 비싸고, 무관한 결과까지 가져와 답이 더 나빠짐
- 검색 안 하면 hallucination

### 해법
LLM이 4가지 **reflection token**을 생성하면서 자기 검열:

| Token | Role |
|---|---|
| `Retrieve` | 이 질문에 검색이 필요한가? |
| `IsRel` | 검색된 문서가 관련 있나? |
| `IsSup` | 답변이 검색 근거에 지지되나? |
| `IsUse` | 답변이 실제로 유용한가? |

원본 논문은 Llama2를 fine-tune해서 토큰을 학습. 본 시스템은 fine-tuning 없이도 prompt로 흉내 가능.

### 본 시스템 적용 분석
- 현재: "**항상 검색 + 항상 사용**" 패턴
- Self-RAG의 정신을 prompt만으로 적용 가능:
  ```
  [기존 prompt에 추가]
  주어진 컨텍스트를 사용하기 전에:
  1. 컨텍스트가 query와 실제로 관련 있는지 평가
  2. 관련 없다면 컨텍스트 무시하고 답변
  3. 답변에 사용한 컨텍스트의 신뢰도를 명시
  ```

### 도입 권장도: ⭐⭐⭐
- **트리거**: 회당 비용이 $5 이상으로 상승 (현재 $2)
- **부분 적용**: prompt 한 줄 추가로 "관련성 자가평가"는 즉시 가능
- **풀 도입**: fine-tuning 필요 → 부담 큼, 보류

---

## 3. CRAG — Corrective Retrieval-Augmented Generation ⭐ 현재 시스템의 자연스러운 다음 단계

**Reference**: Yan et al., *"Corrective Retrieval Augmented Generation"*, 2024. [arXiv:2401.15884](https://arxiv.org/abs/2401.15884)

### 문제
- Retriever가 잘못된 문서 가져와도 LLM은 그대로 신뢰 → hallucination 증폭
- Score만으론 "관련 있어 보이는데 사실 무관"한 결과 거르기 어려움

### 해법
경량 **Retrieval Evaluator** (T5-large)로 검색 결과를 3등급 분류:

```
┌─────────────────────────────────────────────────────┐
│ Query → Retrieve → Evaluator → 분기                 │
├─────────────────────────────────────────────────────┤
│ Correct   (>0.59) → 그대로 사용                     │
│ Ambiguous (mid)   → 내부 결과 + 외부(웹) 검색 결합  │
│ Incorrect (<-0.99)→ 외부 검색으로 fallback          │
└─────────────────────────────────────────────────────┘
```

추가로 "**knowledge refinement**" 단계: 검색된 문서를 strip → 핵심 strip만 추출 후 재조합 (decompose-then-recompose).

### 본 시스템 적용 분석
- 본 시스템의 `min_score=0.4` 컷오프(ADR-003)는 CRAG의 단순화 버전
- 진화 경로:
  ```
  [현재]  score < 0.4 → 버림 (binary)
  [CRAG]  score 평가 → Correct/Ambiguous/Incorrect (ternary)
          + Ambiguous는 wiki와 결합
          + Incorrect는 별도 fallback (예: 다른 keyword로 재검색)
  ```
- Evaluator 모델은 자체 학습 부담 → **LLM(Sonnet) 한 줄 prompt로 대체 가능**

### 도입 권장도: ⭐⭐⭐⭐⭐
- **시기**: 현재 컷오프 1주 운영 후 결과 보고 즉시 도입
- **상세**: [ADR-005](../adr/005-crag-evaluator-fallback.md) 참조

---

## 4. GraphRAG (Microsoft) ⭐⭐ 다음 주 도입 예정 — 필독

**Reference**: Edge et al., *"From Local to Global: A Graph RAG Approach to Query-Focused Summarization"*, 2024. [arXiv:2404.16130](https://arxiv.org/abs/2404.16130)
**Code**: [github.com/microsoft/graphrag](https://github.com/microsoft/graphrag)

### 문제
- Vector RAG는 **multi-hop reasoning** 약함
- "이 테마에 강한 운용사들의 평균 TER" 같은 집계 질문 못 함
- "전체 corpus의 큰 그림" 류 query에 무력 (각각의 chunk만 보니까)

### 해법

**Indexing time**:
```
Documents
  → LLM이 (entity, relation, entity) 트리플 추출
  → Knowledge Graph 구축
  → Leiden 알고리즘으로 community 탐지 (계층적)
  → 각 community에 LLM이 summary 생성
```

**Query time**:
- **Local search**: Entity 중심, KG traversal
- **Global search**: 모든 community summary를 map-reduce 방식으로 종합

### 본 시스템 적용 분석

본 시스템 도메인은 **graph가 자연스럽게 풍부**:
```
ETF ──(운용)── 운용사
 │
 ├──(테마)─── 테마 ──(유사)── 테마
 ├──(기초자산)── 자산군
 ├──(환헤지)── 헤지유형
 └──(언급)── 블로그/뉴스
```

**LSEG 박제로 entity·relationship이 이미 정형화** → GraphRAG의 가장 비싼 단계(LLM entity extraction)가 **거의 공짜**:

| GraphRAG 표준 | 본 시스템 | 비용 절감 |
|---|---|---|
| LLM이 corpus에서 entity 추출 | wiki에 1099 ETF 이미 존재 | ~95% |
| LLM이 relationship 추출 | LSEG 박제에 themes/operator/asset 매핑 존재 | ~90% |
| Community detection | 테마별 자연 grouping (176 themes) | LLM 불필요 |
| Community summary | 시원님 stage별 context builder가 비슷한 역할 | 일부 재활용 |

**상세 PoC 설계**: [docs/poc/graphrag-design.md](../poc/graphrag-design.md)

### 도입 권장도: ⭐⭐⭐⭐⭐
- **시기**: 다음 주
- **구현**: Microsoft 원본 대신 **Kuzu(임베디드 graph DB) + 본 시스템 wiki** 조합 (1주 안에 PoC 가능)
- **트리거**: ADR-001에서 정의한 Graph DB 도입 트리거(다중홉 질의 주 5회)는 미충족이지만, GraphRAG의 **community summary** 패턴은 트리거 무관하게 유용

---

## 5. RAG Survey

**Reference**: Gao et al., *"Retrieval-Augmented Generation for Large Language Models: A Survey"*, 2023. [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)

### 핵심 분류

| 단계 | 특징 | 본 시스템 위치 |
|---|---|---|
| **Naive RAG** | 검색 → 그대로 LLM | 졸업 |
| **Advanced RAG** | Pre/Post-retrieval 최적화, hybrid retrieval | **현재 위치** |
| **Modular RAG** | 라우팅·메모리·iterative retrieval·multi-stage | **다음 단계** |

### Modular RAG 모듈 (본 시스템과 매핑)

| 모듈 | 본 시스템 |
|---|---|
| **Search** (hybrid) | ✅ Wiki + FAISS 구현 완료 |
| **Routing** (질문 유형별 분기) | ✅ stage별 context builder가 비슷 |
| **Memory** (과거 결과 캐싱) | ⚠️ past_output 인덱싱이 비슷, 본격 메모리 X |
| **Predict** (LLM이 검색 전 예측) | ❌ HyDE 도입 시 |
| **Demonstrate** (few-shot 예시) | ❌ |
| **Adapter** (모델 출력 재가공) | ⚠️ stage별 outputs/ 구조가 비슷 |

### 도입 권장도: ⭐⭐⭐
- 좌표 확인용. 구체적 기술은 다른 4편이 더 깊음.
- 본 시스템은 이미 **Advanced RAG의 상위권**, Modular RAG로 진화 중.

---

## 통합 학습 → 적용 로드맵

### 이번 주 (학습)
1. GraphRAG 정독 — Microsoft 원문 어려우면 [Neo4j GraphRAG 시리즈](https://neo4j.com/developer-blog/graphrag-llm-knowledge-graph/)
2. CRAG 정독 — [원문 8페이지](https://arxiv.org/pdf/2401.15884)면 1시간

### 다음 주 (적용)
3. **GraphRAG 미니 PoC** — 설계: [docs/poc/graphrag-design.md](../poc/graphrag-design.md)
4. **CRAG 부분 적용** — 설계: [ADR-005](../adr/005-crag-evaluator-fallback.md)

### 그 다음 (관망)
5. Self-RAG 부분 적용 (prompt 변형, 무료)
6. HyDE는 짧은 query 케이스 발생 시

---

## 부록: 본 시스템에 영원히 도입 안 할 것들

도구는 트리거 충족 시에만 도입한다는 원칙(ADR-001)에 따라, 다음은 명시적으로 보류:

| 기술 | 보류 이유 |
|---|---|
| Self-RAG full fine-tuning | 비용·복잡도 > 효과. Prompt로 80% 효과 가능 |
| HyDE | Query가 이미 충분히 길어 marginal |
| Re-ranking model 별도 (Cohere Rerank 등) | min_score 컷 + CRAG evaluator로 대체 가능 |
| Multi-vector retrieval (ColBERT) | 1099 entity 규모에 과잉 |
| Long-context bypass (RAG 자체 폐기) | 출처 추적·비용·신선도 모두 RAG가 우위 (ADR-004) |

---

## 정리: 5편이 본 시스템에 주는 메시지

> **"이미 Advanced RAG는 했다. 다음은 (1) 검색 결과를 능동적으로 평가·교정 (CRAG), (2) 그래프 구조를 활용한 다중홉 (GraphRAG) 두 트랙."**

이 두 트랙은 서로 직교(orthogonal)하므로 **병렬 도입 가능**.
