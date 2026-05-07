# Case Study: ETF Content RAG Pipeline

> 금융사 인턴 기간 중 ETF 콘텐츠 마케팅 자동화 시스템을 설계·운영한 경험.
> *(회사명·구체 매출/비용 숫자는 일반화. 의사결정·아키텍처·임팩트 메트릭만 기록.)*

---

## 한 줄 요약

> 매주 사람이 ETF 트렌드를 분석하고 콘텐츠 아이디어·브리프를 작성하던 작업을, **ML + LLM + RAG 파이프라인 11단계로 자동화**하여 운영 부담을 한 줄 명령으로 줄이고 콘텐츠 품질 메트릭을 정량적으로 개선한 프로젝트.

## Problem

### Before
- 매주 1회, 사람이 직접 수행:
  1. 네이버 블로그·뉴스에서 ETF 키워드 트렌드 수집·정리
  2. 시장 흐름 해석 → 콘텐츠 주제 선정
  3. 클러스터별 콘텐츠 아이디어 도출
  4. 트렌드 브리프 작성 → 팀장 보고
- 사람 시간 비용 대비 산출물 일관성·확장성 한계
- 자사 상품 위주 추천으로 편향 위험 (88% 비중)

### Why it mattered
- 콘텐츠 마케팅이 매출 채널인 비즈니스에서 사람 시간이 병목
- 도메인(ETF·금융 컴플라이언스) 이해 없이는 자동화 불가능 → 외부 위탁 어려움

## Solution

### High-level Architecture

11.5단계 파이프라인 ([상세 다이어그램](architecture.md)):

```
[1~4] Blog 수집·ML·트렌드·HTML 보고서
[5~8] News 수집·ML·트렌드·HTML 보고서
[9]   Blog × News 교차분석 → LLM 선정 4개 클러스터
[9.5] RAG 데이터 갱신 (Wiki + Vector 증분 인덱싱)
[10]  LLM 다단계 콘텐츠 생성 (Sonnet → Opus → Gemini → Sonnet)
[11]  주간 이메일 발송
```

### Key Components
- **수집·ML**: Naver Blog/News API → ETF 관련성 점수(`proxy_score`, `etf_mentions`) → HDBSCAN 클러스터링
- **RAG (직접 설계)**:
  - Wiki(SQLite): 1099개 ETF 메타 + 세제 6 + 규제 2
  - Vector(FAISS, ko-sroberta-multitask): 블로그 980 + 뉴스 818 + 과거 산출물
  - Stage별 컨텍스트 빌더 (5종)
- **LLM 오케스트레이션**: Claude Sonnet 4.6 + Opus 4.7 + Gemini 2.5 Flash 다단계
- **운영 자동화**: 단일 명령 `python run_all.py`

## Key Decisions (ADR로 기록)

이 프로젝트의 진짜 가치는 **왜 이렇게 만들었는가**에 있음:

| 결정 | 핵심 이유 | ADR |
|---|---|---|
| SQLite + FAISS (Graph DB X) | 현 규모(1099 ETF)는 Graph DB의 1만분의 1 미만. 트리거 조건 명시 후 도입 보류. | [ADR-001](adr/001-storage-choice.md) |
| LSEG 메타데이터 JSON 박제 | 변동/고정값을 분리. 사람이 매주 잊을 수 있는 단계 자체를 제거. | [ADR-002](adr/002-lseg-snapshot-pattern.md) |
| Vector 검색 score 0.4 컷오프 | 임베딩 점수 분포 분석 → 노이즈와 정상 결과의 valley 지점 발견. | [ADR-003](adr/003-vector-noise-cutoff.md) |
| RAG over Fine-tuning | 데이터 신선도·출처 추적·편향 제어·비용 모두 RAG가 우위. | [ADR-004](adr/004-rag-over-finetuning.md) |

## Impact

| Metric | Before | After |
|---|---|---|
| 매주 사람 명령 수 | 4개 (수집·메타·인덱싱·LLM) | **1개** (`python run_all.py`) |
| 매주 LSEG 수동 작업 | 매주 (DRM 환경 다른이름저장) | **연 1~2회** |
| RAG 메타 적용 무결성 | 사람 의존 (잊으면 0% 적용) | **100% 보장** |
| 할루시네이션 위험도 | 60 | **53** |
| 콘텐츠 내 구체 수치 | 8개 | **21개** |
| AIDA/PAS 점수 | 8.7 | **9.2** |
| 운용사 다양성 | TIGER 88% 편향 | **균형** |
| 회당 비용 | ~$1.0 | ~$2.0 (RAG 추가에도 월 한도 내) |

## Engineering Practices

이 프로젝트에서 의도적으로 적용한 것:

- **무결성 검증을 사람 기록(메모리·문서)이 아니라 1차 데이터(SQLite)로 직접 함** — 한 번은 메모리에 "적용 완료" 기록이 있었지만 실제 wiki는 0%였던 사건이 발견됨. 이후 모든 검증은 sqlite 직접 조회로 이동.
- **운영 자동화는 "사람이 잊을 수 있는 단계 자체를 제거"하는 방향으로** — 박제 패턴, Step 9.5 통합 등.
- **모든 비자명한 의사결정은 ADR로 기록** — "왜 이걸 안 했는가"까지 포함.
- **변경은 한 번에 한 변수만** — 노이즈 컷오프 도입 시 검색 컷(저위험)만 적용, 인덱싱 필터(중위험)는 1주 운영 후 결정.
- **트리거 기반 의사결정** — Graph RAG·Postgres·Fine-tuning 모두 영구 폐기가 아니라 "트리거 충족 시 재검토"로 명시.

## My Role

- 도메인 이해(ETF, 금융 컴플라이언스)부터 시스템 아키텍처까지 단독 설계
- 코드 직접 작성은 LLM(Claude) 보조, 그러나 모든 임계값·트레이드오프·아키텍처 결정은 본인이 함
  - 예: RAG 채택 여부, DB 선택, 박제 패턴, 컷오프 임계값(0.4)
- 데이터 무결성 검증, 노이즈 진단, 임팩트 측정도 본인 주도
- "Builder형 DX/AX 전문가" — 컨설팅이 아니라 직접 짓고 운영함

## What I'd Do Differently

- **Quality eval set을 더 일찍 만들었어야 함**: 산출물 품질을 매주 자동 측정할 수 있도록 평가셋·메트릭 자동 수집 체계가 늦게 들어감
- **DB를 처음부터 단일로 합쳤어야 함**: 블로그·뉴스 DB를 분리해 시작했는데, 운영해보니 분리 가치가 없었음
- **Co-occurrence 로깅을 처음부터**: Graph RAG로 확장할 가능성을 미리 알았다면 entity 공출현 데이터를 처음부터 누적했을 것

## What's Next

- Public 데이터셋(KRX, ETF Check)으로 100% 재현 가능한 quickstart
- Quality eval 자동 측정 (할루시네이션·다양성·구체성)
- Graph RAG 확장 (트리거 충족 시 — 현재 0/5)

---

## Stack Summary

`Python` `SQLite` `FAISS` `sentence-transformers (ko-sroberta)` `HDBSCAN` `Anthropic Claude (Sonnet/Opus)` `Google Gemini` `Naver Finance/Blog/News API`
