# ETF Content RAG Pipeline

> Korean ETF market content automation with RAG (Wiki + Vector) and multi-stage LLM pipeline.
> 한국 ETF 시장의 1,099개 종목 데이터와 블로그·뉴스 코퍼스를 활용해 주간 콘텐츠 아이디어와 마케팅 브리프를 자동 생성하는 ML + LLM + RAG 파이프라인.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## TL;DR

- **What**: Naver Blog + News에서 ETF 관련 키워드를 ML로 발굴하고, RAG 기반 LLM 파이프라인으로 주간 콘텐츠 아이디어와 트렌드 브리프를 자동 생성.
- **Why**: 매주 ETF 콘텐츠 기획에 들어가는 사람 시간을 줄이고, 콘텐츠 품질의 일관성을 확보.
- **How**: 11단계 파이프라인 (수집 → ML 클러스터링 → RAG 컨텍스트 빌드 → LLM 다단계 프롬프트 → 이메일 발송).

## Stack

| Layer | Tech |
|---|---|
| Data | Naver Finance ETF API, Naver Blog/News API, KRX/공개 ETF 메타 |
| Storage | SQLite (Wiki) + FAISS (Vector) |
| ML | sentence-transformers (`jhgan/ko-sroberta-multitask`), HDBSCAN clustering |
| LLM | Anthropic Claude (Sonnet/Opus) + Google Gemini |
| Orchestration | Python, single-file `run_all.py` (11 steps) |

## Architecture

```
[1~4] Blog 수집·ML·트렌드·HTML 보고서
[5~8] News 수집·ML·트렌드·HTML 보고서
[9]   Blog × News 교차분석 → 4개 클러스터 선정
[9.5] RAG 데이터 갱신 (Wiki 시드 + 벡터 증분 인덱싱)
[10]  LLM 콘텐츠 아이디어 + 트렌드 브리프 생성
[11]  주간 이메일 발송
```

자세한 다이어그램: [docs/architecture.md](docs/architecture.md) (TBA)

## Key Design Decisions

이 프로젝트의 진짜 가치는 **왜 이렇게 만들었나**에 있습니다. 자세한 설계 결정 기록:

- [ADR-001: Why SQLite + FAISS instead of Graph DB](docs/adr/001-storage-choice.md) (TBA)
- [ADR-002: Why snapshot static metadata to JSON](docs/adr/002-static-snapshot-pattern.md) (TBA)
- [ADR-003: Why min_score=0.4 for vector search cutoff](docs/adr/003-vector-noise-cutoff.md) (TBA)
- [ADR-004: Why RAG, not fine-tuning](docs/adr/004-rag-over-finetuning.md) (TBA)

## Impact Numbers

| Metric | Before | After |
|---|---|---|
| 주간 콘텐츠 기획 사람 시간 | TBA | TBA |
| LLM 산출물 할루시네이션 위험도 | 60 | 53 |
| 콘텐츠 내 구체 수치 등장 횟수 | 8 | 21 |
| 운용사 다양성 (자사 편향) | 88% | 균형 |
| 회당 비용 (USD) | ~$1.0 | ~$2.0 (RAG 추가) |
| 운영 자동화 후 매주 사람 명령 수 | 4개 | 1개 |

## Quick Start

```bash
# 환경 준비
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env에 API 키 설정 (Anthropic, Naver, Gemini)
cp .env.example .env

# 전체 파이프라인 실행
python run_all.py
```

## Project Structure

```
etf-content-rag-pipeline/
├── app/                    # 수집·전처리·ML 분석
│   ├── ingestion/          # Naver Blog/News API
│   ├── filtering/          # ETF 관련성 점수
│   └── pipeline/           # ML 파이프라인
├── llm_pipeline/
│   ├── rag/                # Wiki + Vector RAG
│   │   ├── wiki.py         # SQLite Wiki Store
│   │   ├── vector_store.py # FAISS index
│   │   ├── embedder.py     # ko-sroberta singleton
│   │   ├── context_builder.py
│   │   └── ...
│   ├── prompts.py          # LLM 프롬프트
│   └── main.py             # 콘텐츠 아이디어 + 브리프 생성
├── data/                   # (gitignored) 로컬 데이터
├── docs/                   # 아키텍처·ADR·케이스 스터디
└── run_all.py              # 11단계 진입점
```

## Roadmap

- [ ] Public 데이터셋 기반 재현 가능한 quickstart
- [ ] 아키텍처 다이어그램 (Excalidraw)
- [ ] ADR 4건
- [ ] Demo notebook
- [ ] Optional: Graph RAG 확장 (Kuzu)

## Background

이 프로젝트는 **금융권 인턴 기간 중 ETF 콘텐츠 마케팅 자동화** 과제를 수행한 경험을 일반화·재현 가능하게 정리한 것입니다. 사내 데이터·코드는 일절 포함하지 않으며, 모든 데이터는 공개 API/소스로 대체했습니다.

## License

MIT
