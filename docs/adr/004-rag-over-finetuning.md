# ADR-004: 왜 RAG, 왜 Fine-tuning이 아닌가

**Status**: Accepted
**Date**: 2026-05-06
**Decision makers**: 시원 (DX/AX)

## Context

LLM이 ETF 도메인에 정확한 콘텐츠를 만들도록 하는 데 두 가지 방법:

1. **Fine-tuning**: ETF 도메인 데이터로 base 모델을 재학습
2. **RAG (Retrieval-Augmented Generation)**: 매 호출 시 관련 컨텍스트를 검색해서 프롬프트에 주입

초기 프롬프트만 사용한 LLM 호출 결과:
- 할루시네이션 위험도 60 (자체 측정)
- 자사(TIGER) 상품으로 강하게 편향 (88% 비중)
- 구체적 수치(시총·TER·수익률) 등장 빈도 낮음 (8개)

## Decision

**RAG 채택**. Fine-tuning은 다음 조건 충족 시까지 보류.

RAG 구성:
- **Wiki(SQLite)**: 1099개 ETF 메타 + 세제 6건 + 규제 2건 → key 기반 lookup
- **Vector(FAISS)**: 블로그·뉴스·과거 산출물 → 시맨틱 검색
- **Stage별 컨텍스트 빌더**: LLM 단계별로 다른 종류의 컨텍스트 조합

## Rationale

### 왜 Fine-tuning이 아닌가

1. **데이터 신선도 요구 vs Fine-tuning의 학습 비용**
   - ETF 시세·시총·신상품은 매주 변함
   - Fine-tuning은 학습 데이터 시점에 stuck → 매주 재학습은 비용·시간 면에서 비현실적
   - RAG는 매주 wiki/vector만 갱신하면 LLM은 그대로 사용

2. **Source attribution (출처 추적)**
   - 금융 콘텐츠는 "왜 이렇게 추천했는가"의 출처가 중요 (컴플라이언스)
   - RAG는 검색된 문서를 그대로 노출 가능 → 검수자가 검증 가능
   - Fine-tuning은 모델 가중치에 녹아들어 출처 불투명

3. **편향 제어**
   - "TIGER 우선 추천" 같은 프롬프트 하드코딩이 있던 시절 → fine-tuning 했으면 더 깊이 박힘
   - RAG로 바꾸면서 컨텍스트 자체에 균형 잡힌 ETF 풀을 주입 → 운용사 다양성 자연스럽게 확보

4. **변경 비용**
   - 새로운 도메인 지식 추가가 wiki에 INSERT 한 줄 (vs 재학습)
   - 잘못 들어간 정보 제거가 DELETE 한 줄 (vs 재학습)

5. **현재 모델의 base 성능**
   - Claude Opus/Sonnet은 한국어 + 금융 일반 지식이 이미 충분
   - 부족한 건 "최신 ETF 종목별 디테일" → 정확히 RAG로 보완 가능한 영역

### 왜 RAG의 어떤 패턴인가

- **Hybrid retrieval (Wiki + Vector)**: 구조화 데이터(ETF 메타)와 비정형 문서(블로그/뉴스)가 모두 필요 → 단일 벡터 검색으로는 부족
- **Stage별 다른 컨텍스트**: Intent 단계엔 과거 산출물, Draft 단계엔 ETF + 세제, Factcheck 단계엔 뉴스 — 단계별 RAG context builder
- **Cost-aware**: 회당 ~$2 (Sonnet + Opus + Gemini 조합)로 fine-tuning + 추론 인프라 대비 압도적으로 저렴

### 핵심 원칙
> **"학습보다 검색이 싸고 빠르고 추적 가능하다 — 최신성·투명성이 중요한 도메인에선 RAG가 거의 항상 정답."**

## Consequences

**Positive**:
- 할루시네이션 위험도 60 → 53 (LSEG 메타 통합 후)
- 구체적 수치 등장 8개 → 21개
- 운용사 다양성: TIGER 88% 편향 → 균형
- AIDA/PAS 점수 8.7 → 9.2
- 매주 데이터 갱신만으로 LLM 산출물 자동으로 최신화

**Negative**:
- 회당 비용 ~$1.0 → ~$2.0 (RAG 컨텍스트 토큰 증가)
- 프롬프트 길이가 LLM 컨텍스트 한도에 더 가까워짐 → 큰 모델 필요
- 검색 품질이 곧 답변 품질 → 검색 노이즈 관리 필요 ([ADR-003](003-vector-noise-cutoff.md))

**Neutral**:
- Fine-tuning은 영구 폐기가 아니라 보류. 트리거 충족 시 재검토.

## Trigger to Revisit (Fine-tuning 도입 시점)

- 회당 비용이 $5 이상으로 상승 + 동일 패턴 반복 (캐시·축약 한계 도달)
- RAG 컨텍스트로 해결 안 되는 도메인 특이 표현 (예: 회사 고유 콘텐츠 톤)
- 도메인 어휘가 base 모델에 너무 부족해서 검색 컨텍스트로도 보완 안 됨
- 응답 latency가 RAG 검색 + LLM 추론 합쳐 비즈니스 SLA 초과

## Related

- [ADR-001: SQLite + FAISS](001-storage-choice.md)
- [ADR-002: LSEG 박제 패턴](002-lseg-snapshot-pattern.md)
- [ADR-003: Vector 컷오프](003-vector-noise-cutoff.md)
