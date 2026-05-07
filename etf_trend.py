"""
etf_trend.py — ML-based ETF keyword trend analyzer.

Entry point:
    run_period(period: int, posts: list[dict])
    posts = [{"text": "...", "post_date": "YYYYMMDD or YYYY-MM-DD"}, ...]
    period: 1 이상 (상한 없음, 매 수집 주기마다 1씩 증가)

Integration with existing pipeline:
    from app.storage.json_store import load_json  # or just json.load
    rows = json.load(open("data/processed/filtered_docs.json"))
    posts = [{"text": r["clean_text"], "post_date": r["post_date"]} for r in rows]
    run_period(1, posts)

CLI:
    python etf_trend.py status   # print saved periods and post counts
    python etf_trend.py report   # regenerate charts from existing DB data
    python etf_trend.py test     # run with 50 dummy posts for period 1
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from kiwipiepy import Kiwi
from scipy.sparse import issparse
from scipy.stats import linregress
from sklearn.cluster import KMeans
from sklearn.decomposition import LatentDirichletAllocation, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import Normalizer
from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

# ─── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── constants ────────────────────────────────────────────────────────────────
from app.config.constants import (
    KMEANS_K_MIN, KMEANS_K_MAX, KMEANS_N_INIT, KMEANS_RANDOM_STATE,
    SVD_N_COMPONENTS, SVD_RANDOM_STATE,
    LDA_N_COMPONENTS, LDA_RANDOM_STATE,
)

# 프로젝트 루트: etf_trend.py가 루트에 위치
_PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")

from app.utils import week_folder as _week_folder
RESULTS_DIR = _PROJECT_ROOT / "results" / _week_folder()

# TF-IDF 파라미터
TFIDF_MAX_DF: float = 0.60  # 전체 문서의 60% 이상에 나타나는 단어 제외
TFIDF_MIN_DF: int = 3
TFIDF_MAX_FEATURES: int = 300

STOPWORDS: set[str] = {
    "etf", "블로그", "포스트", "오늘", "이번", "지금", "관련", "경우",
    "생각", "정도", "현재", "사용", "제공", "가능", "필요", "결과",
    "방법", "통해", "위해", "대한", "하나", "모든", "다음", "부분",
}

# ─── SQLAlchemy ORM ────────────────────────────────────────────────────────────
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def set_db(path: str) -> None:
    """DB 경로를 전환한다. blog/news 분리 실행 시 사용.

    상대경로로 넘기면 프로젝트 루트 기준 절대경로로 자동 변환한다.

    Example:
        etf_trend.set_db("etf_trend_news.db")
        etf_trend.run_period(1, posts)
    """
    global engine, DB_PATH
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = _PROJECT_ROOT / resolved
    DB_PATH = str(resolved)
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
    logger.info("DB switched to: %s", DB_PATH)


class Base(DeclarativeBase):
    pass


class Collection(Base):
    __tablename__ = "collections"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False)
    post_count = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="done")
    run_date = Column(String(10), nullable=True)   # YYYY-MM-DD (실행일)
    week_start = Column(String(10), nullable=True)  # YYYY-MM-DD (해당 주 월요일)


class Keyword(Base):
    __tablename__ = "keywords"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False)
    keyword = Column(String(100), nullable=False)
    frequency = Column(Integer, nullable=False)
    tfidf_rank = Column(Integer, nullable=False)  # 1 = highest mean TF-IDF; 9999 = not in top list
    novelty_score = Column(Float, nullable=True)  # (freq - prev_freq) / (prev_freq + 1); high = new/burst keyword


class ClusterRun(Base):
    __tablename__ = "cluster_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False)
    k = Column(Integer, nullable=False)
    silhouette = Column(Float, nullable=False)


class Cluster(Base):
    __tablename__ = "clusters"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False)
    cluster_id = Column(Integer, nullable=False)
    keywords = Column(Text, nullable=False)  # comma-separated top 10
    size = Column(Integer, nullable=False)


class YoutubeKeyword(Base):
    __tablename__ = "youtube_keywords"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False)
    keyword = Column(String(100), nullable=False)
    frequency = Column(Integer, nullable=False)
    avg_view_count = Column(Float, nullable=True)
    video_count = Column(Integer, nullable=True)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _init_db() -> None:
    """테이블 생성 및 기존 DB 스키마 마이그레이션."""
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE keywords ADD COLUMN novelty_score REAL",
            "ALTER TABLE collections ADD COLUMN run_date TEXT",
            "ALTER TABLE collections ADD COLUMN week_start TEXT",
            "ALTER TABLE clusters ADD COLUMN embedding BLOB",
            """CREATE TABLE IF NOT EXISTS cluster_lineage (
                current_period INTEGER NOT NULL,
                current_cluster_id INTEGER NOT NULL,
                prev_period INTEGER NOT NULL,
                prev_cluster_id INTEGER NOT NULL,
                similarity REAL NOT NULL,
                PRIMARY KEY (current_period, current_cluster_id, prev_period, prev_cluster_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_lineage_current ON cluster_lineage(current_period)",
        ]:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # 이미 존재하면 무시


def _is_week_done(week_start: str) -> bool:
    """해당 week_start(YYYY-MM-DD)가 이미 완료된 주인지 확인한다."""
    with Session(engine) as session:
        row = session.query(Collection).filter_by(week_start=week_start, status="done").first()
        return row is not None


def _is_period_done(period: int) -> bool:
    """하위 호환용: period 번호로 완료 여부 확인 (week_start 방식 권장)."""
    with Session(engine) as session:
        row = session.query(Collection).filter_by(period=period, status="done").first()
        return row is not None


def _save_collection(period: int, post_count: int, week_start: str | None = None) -> None:
    """period 완료 기록을 collections 테이블에 저장한다."""
    import datetime
    today = datetime.date.today().isoformat()
    with Session(engine) as session:
        session.add(Collection(
            period=period,
            post_count=post_count,
            status="done",
            run_date=today,
            week_start=week_start,
        ))
        session.commit()


def _save_keywords(period: int, freq_dict: dict[str, int], tfidf_top: list[str]) -> None:
    """키워드 빈도·TF-IDF 순위·novelty_score를 keywords 테이블에 저장한다."""
    # Fetch previous period frequencies to calculate novelty score
    prev_freq: dict[str, int] = {}
    if period > 1:
        with Session(engine) as session:
            prev_rows = session.query(Keyword).filter_by(period=period - 1).all()
            prev_freq = {r.keyword: r.frequency for r in prev_rows}

    tfidf_rank_map = {kw: rank for rank, kw in enumerate(tfidf_top, 1)}
    with Session(engine) as session:
        for kw, freq in freq_dict.items():
            prev = prev_freq.get(kw, 0)
            novelty = round((freq - prev) / (prev + 1), 4)
            session.add(Keyword(
                period=period,
                keyword=kw,
                frequency=freq,
                tfidf_rank=tfidf_rank_map.get(kw, 9999),
                novelty_score=novelty,
            ))
        session.commit()


def _save_cluster_run(period: int, k: int, silhouette: float) -> None:
    """K-Means 실행 결과(best_k, silhouette)를 cluster_runs 테이블에 저장한다."""
    with Session(engine) as session:
        session.add(ClusterRun(period=period, k=k, silhouette=silhouette))
        session.commit()


def _save_clusters(period: int, clusters: list[dict[str, Any]]) -> None:
    """클러스터별 대표 키워드와 크기를 clusters 테이블에 저장한다."""
    with Session(engine) as session:
        for c in clusters:
            session.add(Cluster(
                period=period,
                cluster_id=c["cluster_id"],
                keywords=",".join(c["keywords"]),
                size=c["size"],
            ))
        session.commit()


# ─── Keyword extraction ───────────────────────────────────────────────────────
_kiwi: Kiwi | None = None


def _get_kiwi() -> Kiwi:
    global _kiwi
    if _kiwi is None:
        logger.info("Loading Kiwi tokenizer...")
        _kiwi = Kiwi()
    return _kiwi


def _tokenize(text: str) -> str:
    """Tokenize with kiwipiepy; keep nouns (NN*) and foreign words (SL) ≥ 2 chars."""
    kiwi = _get_kiwi()
    tokens: list[str] = []
    try:
        for token in kiwi.tokenize(text):
            if token.tag.startswith("NN") or token.tag == "SL":
                word = token.form
                if len(word) >= 2 and word.lower() not in STOPWORDS:
                    tokens.append(word)
    except Exception as exc:
        logger.warning("Tokenization error: %s", exc)
    return " ".join(tokens)


def _extract_keywords(
    posts: list[dict[str, Any]],
) -> tuple[dict[str, int], list[str], Any, list[str]]:
    """
    Tokenize posts, build TF-IDF matrix.

    Returns:
        freq_dict      — raw keyword frequency across all posts
        tfidf_top      — top 50 keywords sorted by mean TF-IDF score
        tfidf_matrix   — sparse matrix (n_docs x n_features), or None on failure
        feature_names  — vocabulary list matching matrix columns
    """
    texts = [p.get("text", "") for p in posts]
    tokenized = [_tokenize(t) for t in texts]
    logger.info("Tokenized %d documents.", len(tokenized))

    # Frequency count
    freq: Counter[str] = Counter()
    for doc in tokenized:
        freq.update(doc.split())

    vectorizer = TfidfVectorizer(
        min_df=TFIDF_MIN_DF,
        max_df=TFIDF_MAX_DF,
        max_features=TFIDF_MAX_FEATURES,
        token_pattern=r"(?u)\b\w+\b",
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(tokenized)
        feature_names: list[str] = vectorizer.get_feature_names_out().tolist()
    except ValueError as exc:
        logger.warning("TF-IDF failed (%s). Too few documents?", exc)
        return dict(freq), [], None, []

    mean_scores = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
    top_idx = mean_scores.argsort()[::-1][:50]
    tfidf_top = [feature_names[i] for i in top_idx]

    logger.info("TF-IDF matrix: %s | vocab size: %d", tfidf_matrix.shape, len(feature_names))
    return dict(freq), tfidf_top, tfidf_matrix, feature_names


# ─── K-Means clustering ───────────────────────────────────────────────────────

def _run_kmeans(
    tfidf_matrix: Any,
    feature_names: list[str],
) -> tuple[int, float, list[dict[str, Any]]]:
    """
    TF-IDF + SVD(LSA) 기반 K-Means 클러스터링. k=KMEANS_K_MIN~KMEANS_K_MAX 전수 탐색, 실루엣 최대화.

    Returns:
        best_k, best_silhouette, clusters
        clusters = [{"cluster_id": int, "keywords": list[str], "size": int}, ...]
    """
    if tfidf_matrix is None or tfidf_matrix.shape[0] < 10:
        logger.warning("Not enough documents for K-Means (n=%s).",
                       tfidf_matrix.shape[0] if tfidf_matrix is not None else 0)
        return 0, 0.0, []

    X_tfidf = tfidf_matrix.toarray() if issparse(tfidf_matrix) else tfidf_matrix

    # TF-IDF + SVD(LSA) 차원 축소
    n_components = min(SVD_N_COMPONENTS, X_tfidf.shape[1] - 1, X_tfidf.shape[0] - 1)
    svd = TruncatedSVD(n_components=n_components, random_state=SVD_RANDOM_STATE)
    X_svd = svd.fit_transform(tfidf_matrix)
    X_cluster = Normalizer(copy=False).fit_transform(X_svd)
    explained = svd.explained_variance_ratio_.sum()
    logger.info("SVD(LSA): %d→%d차원 | 설명된 분산: %.1f%%",
                X_tfidf.shape[1], n_components, explained * 100)

    best_k, best_score, best_labels = KMEANS_K_MIN, -1.0, None
    for k in range(KMEANS_K_MIN, min(KMEANS_K_MAX + 1, X_cluster.shape[0])):
        try:
            km = KMeans(n_clusters=k, random_state=KMEANS_RANDOM_STATE, n_init=KMEANS_N_INIT)
            labels = km.fit_predict(X_cluster)
            score = silhouette_score(X_cluster, labels, sample_size=min(1000, X_cluster.shape[0]))
            logger.info("  k=%d  silhouette=%.4f", k, score)
            if score > best_score:
                best_k, best_score, best_labels = k, score, labels
        except Exception as exc:
            logger.warning("KMeans k=%d failed: %s", k, exc)

    if best_labels is None:
        return 0, 0.0, []

    # Extract representative keywords via mean TF-IDF within each cluster
    clusters: list[dict[str, Any]] = []
    for cid in range(best_k):
        mask = best_labels == cid
        if not mask.any():
            continue
        cluster_tfidf_mean = np.asarray(X_tfidf[mask].mean(axis=0)).flatten()
        top_idx = cluster_tfidf_mean.argsort()[::-1][:10]
        kws = [feature_names[i] for i in top_idx if i < len(feature_names)]
        size = int(np.sum(mask))
        clusters.append({"cluster_id": cid, "keywords": kws, "size": size})
        logger.info("  Cluster %d (n=%d): %s", cid, size, ", ".join(kws))

    return best_k, best_score, clusters


# ─── LDA topic modeling ───────────────────────────────────────────────────────

def _run_lda(tfidf_matrix: Any, feature_names: list[str]) -> list[list[str]]:
    """
    LDA with n_components=LDA_N_COMPONENTS, random_state=LDA_RANDOM_STATE.

    Returns:
        list of LDA_N_COMPONENTS topics, each topic = top 10 keywords
    """
    if tfidf_matrix is None or tfidf_matrix.shape[0] < 10:
        logger.warning("Not enough documents for LDA.")
        return []

    lda = LatentDirichletAllocation(n_components=LDA_N_COMPONENTS, random_state=LDA_RANDOM_STATE)
    try:
        lda.fit(tfidf_matrix)
    except Exception as exc:
        logger.warning("LDA failed: %s", exc)
        return []

    topics: list[list[str]] = []
    for i, comp in enumerate(lda.components_):
        top_idx = comp.argsort()[::-1][:10]
        kws = [feature_names[j] for j in top_idx if j < len(feature_names)]
        topics.append(kws)
        logger.info("  LDA Topic %d: %s", i, ", ".join(kws))

    return topics


# ─── Trend analysis (period == 8) ─────────────────────────────────────────────

def _run_trend_analysis() -> None:
    """Load all periods from DB, generate CSV and HTML outputs to ./results/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        kw_rows = session.query(Keyword).all()
        cl_rows = session.query(Cluster).all()

    if not kw_rows:
        logger.warning("No keyword data in DB. Run run_period() first.")
        return

    # ── keyword_trend.csv: keyword x period frequency matrix (top 50) ────────
    kw_df = pd.DataFrame(
        [(r.keyword, r.period, r.frequency) for r in kw_rows],
        columns=["keyword", "period", "frequency"],
    )
    pivot = kw_df.pivot_table(index="keyword", columns="period", values="frequency", fill_value=0)
    pivot["_total"] = pivot.sum(axis=1)
    top50 = pivot.nlargest(50, "_total").drop(columns=["_total"])
    top50.to_csv(RESULTS_DIR / "keyword_trend.csv")
    logger.info("Saved keyword_trend.csv (%d keywords)", len(top50))

    # ── rising_keywords.csv: positive slope by linear regression ─────────────
    period_cols = sorted([c for c in top50.columns if isinstance(c, (int, float))])
    rising: list[dict[str, Any]] = []
    for kw, row in top50.iterrows():
        vals = [float(row.get(p, 0)) for p in period_cols]
        if len(period_cols) >= 2 and any(v > 0 for v in vals):
            slope, _, r_value, p_value, _ = linregress(period_cols, vals)
            if slope > 0:
                rising.append({"keyword": kw, "slope": round(slope, 4), "r_squared": round(r_value ** 2, 4)})
    df_rising = pd.DataFrame(rising)
    if not df_rising.empty and "slope" in df_rising.columns:
        df_rising = df_rising.sort_values("slope", ascending=False)
    df_rising.to_csv(RESULTS_DIR / "rising_keywords.csv", index=False)
    logger.info("Saved rising_keywords.csv (%d rising keywords)", len(rising))

    # ── burst_keywords.csv: top 20 newly appeared / spiking keywords ─────────
    latest_period = int(kw_df["period"].max())
    with Session(engine) as session:
        novelty_rows = (
            session.query(Keyword)
            .filter_by(period=latest_period)
            .order_by(Keyword.novelty_score.desc())
            .limit(20)
            .all()
        )
    if novelty_rows and novelty_rows[0].novelty_score is not None:
        burst_df = pd.DataFrame([
            {"keyword": r.keyword, "frequency": r.frequency,
             "novelty_score": r.novelty_score, "period": r.period}
            for r in novelty_rows
        ])
        burst_df.to_csv(RESULTS_DIR / "burst_keywords.csv", index=False)
        logger.info("Saved burst_keywords.csv (%d burst keywords)", len(burst_df))

    # ── cluster_summary.csv ───────────────────────────────────────────────────
    pd.DataFrame(
        [(r.period, r.cluster_id, r.keywords, r.size) for r in cl_rows],
        columns=["period", "cluster_id", "keywords", "size"],
    ).to_csv(RESULTS_DIR / "cluster_summary.csv", index=False)
    logger.info("Saved cluster_summary.csv")

    # ── heatmap.html ──────────────────────────────────────────────────────────
    fig_heatmap = go.Figure(go.Heatmap(
        z=top50.values,
        x=[f"P{p}" for p in top50.columns],
        y=top50.index.tolist(),
        colorscale="Blues",
        hoverongaps=False,
    ))
    fig_heatmap.update_layout(
        title="Keyword Frequency Heatmap (top 50 keywords × 8 periods)",
        height=1000,
        yaxis=dict(autorange="reversed"),
    )
    fig_heatmap.write_html(str(RESULTS_DIR / "heatmap.html"))
    logger.info("Saved heatmap.html")

    # ── trend_lines.html ──────────────────────────────────────────────────────
    top20 = top50.head(20)
    fig_trend = go.Figure()
    for kw in top20.index:
        fig_trend.add_trace(go.Scatter(
            x=[f"P{p}" for p in top20.columns],
            y=top20.loc[kw].tolist(),
            mode="lines+markers",
            name=str(kw),
        ))
    fig_trend.update_layout(
        title="Top 20 Keyword Trends Over 8 Periods",
        xaxis_title="Period",
        yaxis_title="Frequency",
    )
    fig_trend.write_html(str(RESULTS_DIR / "trend_lines.html"))
    logger.info("Saved trend_lines.html")

    # ── cluster_flow.html (Sankey) ────────────────────────────────────────────
    _generate_sankey(cl_rows)


def _generate_sankey(cl_rows: list) -> None:
    """Sankey diagram showing cluster keyword overlap between adjacent periods."""
    by_period: dict[int, list] = {}
    for r in cl_rows:
        by_period.setdefault(r.period, []).append(r)

    periods = sorted(by_period.keys())
    if len(periods) < 2:
        logger.warning("Need at least 2 periods for Sankey. Skipping.")
        return

    # Build node index
    node_labels: list[str] = []
    node_idx: dict[tuple[int, int], int] = {}
    for p in periods:
        for c in by_period.get(p, []):
            key = (p, c.cluster_id)
            node_idx[key] = len(node_labels)
            top_kws = c.keywords.split(",")[:3]
            node_labels.append(f"P{p}·C{c.cluster_id}: {' / '.join(top_kws)}")

    # Build links by keyword overlap between adjacent periods
    sources: list[int] = []
    targets: list[int] = []
    values: list[int] = []
    for i in range(len(periods) - 1):
        p1, p2 = periods[i], periods[i + 1]
        for c1 in by_period.get(p1, []):
            kws1 = set(c1.keywords.split(","))
            for c2 in by_period.get(p2, []):
                kws2 = set(c2.keywords.split(","))
                overlap = len(kws1 & kws2)
                if overlap > 0:
                    sources.append(node_idx[(p1, c1.cluster_id)])
                    targets.append(node_idx[(p2, c2.cluster_id)])
                    values.append(overlap)

    if not sources:
        logger.warning("No cluster keyword overlap found. Sankey skipped.")
        return

    fig = go.Figure(go.Sankey(
        node=dict(label=node_labels, pad=15, thickness=20),
        link=dict(source=sources, target=targets, value=values),
    ))
    fig.update_layout(title="Cluster Keyword Flow Between Periods (keyword overlap)")
    fig.write_html(str(RESULTS_DIR / "cluster_flow.html"))
    logger.info("Saved cluster_flow.html")


# ─── Public entry point ───────────────────────────────────────────────────────

def get_next_period() -> int:
    """Return MAX(period) + 1 from completed collections."""
    _init_db()
    with Session(engine) as session:
        max_period = session.query(Collection).filter_by(status="done").with_entities(
            Collection.period
        ).order_by(Collection.period.desc()).first()
    return (max_period[0] + 1) if max_period else 1


def run_period(period: int, posts: list[dict[str, Any]], week_start: str | None = None) -> None:
    """
    Run one period of the ML pipeline.

    Args:
        period:      1 이상 정수. 수집 주기마다 1씩 증가 (상한 없음).
        posts:       List of dicts: [{"text": str, "post_date": "YYYYMMDD"}, ...]
                     "text" should be pre-cleaned plain text (HTML already stripped).
        week_start:  해당 주 월요일 날짜 (YYYY-MM-DD). 지정 시 날짜 기준으로 중복 체크.

    Behavior:
        - Idempotent: week_start 지정 시 해당 주 날짜로, 미지정 시 period 번호로 중복 체크.
        - Saves keywords, clusters, and LDA topics to SQLite (etf_trend.db).
        - 매 period 완료 후 트렌드 분석 결과를 ./results/ 에 저장한다.
    """
    _init_db()

    if week_start and _is_week_done(week_start):
        logger.info("Week %s already processed (status=done). Skipping.", week_start)
        return
    if not week_start and _is_period_done(period):
        logger.info("Period %d already processed (status=done). Skipping.", period)
        return

    if not posts:
        logger.warning("No posts provided for period %d. Skipping.", period)
        return

    logger.info("=== Period %d | %d posts ===", period, len(posts))

    # Step 1: Keyword extraction + TF-IDF
    freq_dict, tfidf_top, tfidf_matrix, feature_names = _extract_keywords(posts)
    logger.info("Keyword extraction done. unique=%d, tfidf_vocab=%d", len(freq_dict), len(feature_names))
    _save_keywords(period, freq_dict, tfidf_top)

    # Step 2: K-Means clustering (TF-IDF + SVD)
    best_k, best_score, clusters = _run_kmeans(tfidf_matrix, feature_names)
    if best_k > 0:
        _save_cluster_run(period, best_k, best_score)
        _save_clusters(period, clusters)
        logger.info("K-Means done. best_k=%d silhouette=%.4f", best_k, best_score)

    # Step 3: LDA topic modeling
    topics = _run_lda(tfidf_matrix, feature_names)
    logger.info("LDA done. topics=%d", len(topics))

    # Step 4: Mark period as done
    _save_collection(period, len(posts), week_start=week_start)
    logger.info("Period %d (week_start=%s) saved to DB.", period, week_start)

    # Step 5: 주차간 클러스터 토픽 추적 (FAISS lineage)
    if best_k > 0:
        try:
            from app.clustering.cluster_tracker import run_tracker
            result = run_tracker(period, DB_PATH, lookback=4)
            logger.info(
                "[Tracker] period=%d — matched=%d continuing=%d new=%d disappeared=%d",
                period,
                result["matched"],
                len(result["continuing"]),
                len(result["new"]),
                len(result["disappeared"]),
            )
        except Exception as exc:
            logger.warning("[Tracker] 토픽 추적 실패 (파이프라인 계속): %s", exc)

    # Step 6: 매 period 완료 후 트렌드 분석 실행
    logger.info("Period %d complete — running trend analysis.", period)
    _run_trend_analysis()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_status() -> None:
    _init_db()
    with Session(engine) as session:
        rows = session.query(Collection).order_by(Collection.period).all()
    if not rows:
        print("No periods saved yet.")
        return
    print(f"{'Period':<8} {'Posts':<8} {'Date':<12} {'Status'}")
    print("-" * 40)
    for r in rows:
        print(f"{r.period:<8} {r.post_count:<8} {r.run_date or 'N/A':<12} {r.status}")


def _cmd_report() -> None:
    _init_db()
    logger.info("Regenerating all charts from existing DB data.")
    _run_trend_analysis()
    print(f"Report files written to {RESULTS_DIR.resolve()}")


def _cmd_test() -> None:
    import random

    ETF_TERMS = [
        "삼성 ETF 나스닥 분산투자", "미국 ETF 배당 수익률 월배당",
        "S&P500 ETF 장기투자 복리", "채권 ETF 금리 듀레이션 전략",
        "레버리지 ETF 리스크 단기", "인버스 ETF 경기침체 대응",
        "리츠 ETF 부동산 수익", "원자재 ETF 금 헤지",
        "AI 반도체 ETF 성장주 테마", "연금저축 ETF 세금 절세",
        "환율 달러 ETF 포트폴리오", "배당성장 ETF 고배당 함정",
        "지수 ETF 수수료 비교", "국내 ETF 코스피 코스닥",
        "글로벌 ETF 자산배분 리밸런싱",
    ]

    posts: list[dict[str, Any]] = []
    for _ in range(50):
        combined = " ".join(random.choices(ETF_TERMS, k=4))
        posts.append({
            "text": combined,
            "post_date": f"2024{random.randint(1, 12):02d}{random.randint(1, 28):02d}",
        })

    print("Running test: 50 dummy posts → period 1")
    run_period(1, posts)
    print("Test complete. Run 'python etf_trend.py status' to verify.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "status":
        _cmd_status()
    elif cmd == "report":
        _cmd_report()
    elif cmd == "test":
        _cmd_test()
    else:
        print("Usage: python etf_trend.py [status|report|test]")
        sys.exit(1)
