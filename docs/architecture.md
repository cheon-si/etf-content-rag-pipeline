# Architecture

전체 파이프라인은 단일 진입점 `python run_all.py` 로 11.5단계가 순차 실행됩니다. 각 단계는 독립적이며, 한 단계가 실패해도 다음 단계는 계속 시도합니다 (`_run_step` 래퍼).

## High-level Flow

```mermaid
flowchart TD
    subgraph Collection["Step 1~8: 수집·ML·트렌드"]
        A1[1. Naver Blog 수집 + ETF 필터링] --> A2[2. DataLab 검색량]
        A2 --> A3[3. YouTube 트렌드<br/>API 키 있을 때만]
        A3 --> A4[4. 블로그 HTML 보고서]
        A4 --> B1[5. Naver News 수집 + ML]
        B1 --> B2[6. DataLab 검색량 뉴스]
        B2 --> B3[7. YouTube 트렌드 뉴스]
        B3 --> B4[8. 뉴스 HTML 보고서]
    end

    subgraph Cluster["Step 9: 교차분석"]
        C1[블로그 × 뉴스 클러스터링] --> C2[LLM 선정 4개 클러스터<br/>공통 2 + 블로그단독 1 + 뉴스단독 1]
    end

    subgraph RAG["Step 9.5: RAG 데이터 갱신"]
        R1[Wiki 시드<br/>네이버 ETF 1099개 UPSERT]
        R2[LSEG 고정 메타<br/>JSON 박제 → wiki 주입]
        R3[Vector 증분 인덱싱<br/>blog/news/past_output → FAISS]
    end

    subgraph LLM["Step 10: LLM 다단계 생성"]
        L1[S1 Intent<br/>Sonnet] --> L2[S2 JTBD<br/>Opus]
        L2 --> L3[S3 Pillar + Gemini<br/>Opus]
        L3 --> L4[Content Ideas<br/>Sonnet]
        L4 --> L5[Content Brief<br/>Gemini→Opus]
    end

    Collection --> Cluster
    Cluster --> RAG
    RAG --> LLM
    LLM --> S11[11. 이메일 발송<br/>SMTP]
```

## RAG Layer Detail

```mermaid
flowchart LR
    subgraph Wiki["Wiki Store (SQLite)"]
        W1[product<br/>1099 ETFs]
        W2[tax_rule<br/>6건]
        W3[regulation<br/>2건]
    end

    subgraph Vector["Vector Store (FAISS + SQLite metadata)"]
        V1[blog<br/>~980건]
        V2[news<br/>~818건]
        V3[past_output<br/>증분 누적]
    end

    subgraph Sources["External / Static Sources"]
        S1[Naver Finance ETF API<br/>매주 자동 시세 갱신]
        S2[LSEG static metadata<br/>JSON 박제, 연 1~2회만 갱신]
        S3[Tax/Regulation<br/>코드 내 시드]
    end

    S1 --> W1
    S2 --> W1
    S3 --> W2
    S3 --> W3

    subgraph Builder["Context Builder (stage별)"]
        CB1[s3_cluster<br/>products + blogs]
        CB2[s4_draft<br/>products + tax + blogs]
        CB3[s4_factcheck<br/>products + tax + reg + news]
        CB4[content_ideas<br/>products + past_output]
        CB5[content_brief<br/>tax + reg + top_etfs + past]
    end

    Wiki --> Builder
    Vector --> Builder
    Builder --> LLM[LLM Pipeline<br/>Stage별 컨텍스트 주입]
```

## Vector Search Quality Cutoff

```mermaid
flowchart LR
    Q[Query<br/>cluster_name + keywords] --> E[ko-sroberta<br/>embedding]
    E --> F[FAISS IndexFlatIP<br/>top_k 검색]
    F --> C{score >= 0.4?}
    C -->|Yes| R[검색 결과 반환]
    C -->|No| X[제거<br/>노이즈 컷오프]
```

자세한 컷오프 임계값 결정 근거: [ADR-003](adr/003-vector-noise-cutoff.md)

## Storage Layout

| Path | Purpose | Lifecycle |
|---|---|---|
| `etf_trend.db` | Blog ML + Wiki + RAG metadata 통합 | 매주 갱신 (UPSERT) |
| `etf_trend_news.db` | News ML | 매주 갱신 |
| `data/rag/{blog,news,past_output}.faiss` | Vector 인덱스 | 증분 누적 |
| `data/lseg_static_metadata.json` | LSEG 고정 메타 (1099 종목) | 연 1~2회 갱신 |
| `data/processed/filtered_docs.json` | ETF 관련 필터링된 블로그 코퍼스 | 매주 갱신 |
| `output/YYYY-MM-DD/` | 주간 산출물 (HTML + JSON) | 매주 누적 |
| `logs/run_*.log` | 실행 로그 | 매주 누적 |

## Key Architecture Decisions

각 결정의 trade-off와 이유:

- [ADR-001: SQLite + FAISS 조합 (Graph DB 미도입 이유 포함)](adr/001-storage-choice.md)
- [ADR-002: LSEG 메타데이터 JSON 박제 패턴](adr/002-lseg-snapshot-pattern.md)
- [ADR-003: Vector 검색 score 0.4 컷오프](adr/003-vector-noise-cutoff.md)
- [ADR-004: 왜 RAG, 왜 Fine-tuning이 아닌가](adr/004-rag-over-finetuning.md)

## Run Topology

```mermaid
sequenceDiagram
    participant Cron as cron / 수동
    participant Run as run_all.py
    participant Step as 11.5 Steps
    participant Log as logs/

    Cron->>Run: python run_all.py
    Run->>Log: 새 로그 파일 생성
    loop 11.5단계 순차 실행
        Run->>Step: _run_step(name, fn)
        Step-->>Run: True/False (예외 catch)
        Run->>Log: STEP DONE / FAILED
    end
    Run->>Log: 최종 요약
    Run-->>Cron: exit 0/1
```
