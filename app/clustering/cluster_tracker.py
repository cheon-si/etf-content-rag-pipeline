"""FAISS 기반 주차간 클러스터 토픽 추적 모듈.

매주 클러스터 키워드를 임베딩해 저장하고, 직전 4주 클러스터와
코사인 유사도로 매칭해 "지속 토픽 / 신규 토픽 / 사라진 토픽"을 분류한다.

사용 예:
    from app.clustering.cluster_tracker import run_tracker
    run_tracker(period=5, db_path="etf_trend.db")
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import faiss
import numpy as np

logger = logging.getLogger(__name__)

# ── 임베딩 모델 싱글톤 (llm_pipeline.rag.embedder 에서 공유) ──────────────────
def _get_model():
    from llm_pipeline.rag.embedder import get_model
    return get_model()


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class ClusterRef:
    period: int
    cluster_id: int
    keywords: list[str]


@dataclass
class ClusterLineage:
    current_period: int
    current_cluster_id: int
    prev_period: int
    prev_cluster_id: int
    similarity: float


# ── 핵심 함수 ──────────────────────────────────────────────────────────────────

def embed_cluster_keywords(keywords: list[str], model=None) -> np.ndarray:
    """키워드 리스트를 하나의 문장으로 join해 768차원 벡터로 임베딩한다.

    Returns:
        shape (768,) float32 numpy 벡터 (L2 정규화됨)
    """
    if model is None:
        model = _get_model()
    text = " ".join(keywords)
    vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return vec.astype(np.float32)


def index_period_clusters(period: int, db_path: str, model=None) -> int:
    """해당 period의 클러스터를 임베딩해 DB의 clusters.embedding 컬럼에 저장한다.

    Returns:
        처리한 클러스터 수
    """
    if model is None:
        model = _get_model()

    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT id, keywords FROM clusters WHERE period=? AND (embedding IS NULL OR embedding='')",
            (period,),
        ).fetchall()

        if not rows:
            logger.info("[Tracker] period=%d: 임베딩할 클러스터 없음 (이미 처리됨)", period)
            return 0

        count = 0
        for row_id, kw_str in rows:
            keywords = [k.strip() for k in kw_str.split(",") if k.strip()]
            vec = embed_cluster_keywords(keywords, model)
            blob = vec.tobytes()
            con.execute(
                "UPDATE clusters SET embedding=? WHERE id=?",
                (blob, row_id),
            )
            count += 1

        con.commit()
        logger.info("[Tracker] period=%d: %d개 클러스터 임베딩 저장", period, count)
        return count
    finally:
        con.close()


def build_lookback_index(
    current_period: int,
    db_path: str,
    lookback: int = 4,
) -> tuple[faiss.IndexFlatIP, list[ClusterRef]]:
    """직전 lookback 주차의 클러스터를 FAISS IndexFlatIP에 적재한다.

    Returns:
        (faiss_index, cluster_refs) — 인덱스 순서와 refs 순서가 1:1 대응
    """
    min_period = current_period - lookback
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT period, cluster_id, keywords, embedding
               FROM clusters
               WHERE period >= ? AND period < ? AND embedding IS NOT NULL
               ORDER BY period, cluster_id""",
            (min_period, current_period),
        ).fetchall()
    finally:
        con.close()

    if not rows:
        logger.warning("[Tracker] lookback 범위 내 임베딩 데이터 없음 (period %d~%d)",
                       min_period, current_period - 1)
        index = faiss.IndexFlatIP(768)
        return index, []

    refs: list[ClusterRef] = []
    vecs: list[np.ndarray] = []
    for period, cluster_id, kw_str, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float32).copy()
        if vec.shape[0] != 768:
            logger.warning("[Tracker] 비정상 임베딩 차원=%d, 건너뜀", vec.shape[0])
            continue
        keywords = [k.strip() for k in kw_str.split(",")]
        refs.append(ClusterRef(period=period, cluster_id=cluster_id, keywords=keywords))
        vecs.append(vec)

    index = faiss.IndexFlatIP(768)
    if vecs:
        matrix = np.stack(vecs, axis=0)  # (N, 768)
        index.add(matrix)

    logger.info("[Tracker] FAISS 인덱스 구축: %d개 벡터 (period %d~%d)",
                len(vecs), min_period, current_period - 1)
    return index, refs


def match_lineage(
    current_period: int,
    db_path: str,
    lookback: int = 4,
    sim_threshold: float = 0.7,
    model=None,
) -> list[ClusterLineage]:
    """현재 period 클러스터와 직전 lookback 주 클러스터를 매칭해 lineage를 반환한다.

    각 현재 클러스터에 대해 similarity > sim_threshold인 과거 클러스터를 모두 기록한다.
    결과는 cluster_lineage 테이블에도 upsert된다.
    """
    if model is None:
        model = _get_model()

    # 현재 period 임베딩 로드
    con = sqlite3.connect(db_path)
    try:
        current_rows = con.execute(
            "SELECT cluster_id, keywords, embedding FROM clusters WHERE period=? AND embedding IS NOT NULL",
            (current_period,),
        ).fetchall()
    finally:
        con.close()

    if not current_rows:
        logger.warning("[Tracker] period=%d: 임베딩 없음 — lineage 매칭 불가", current_period)
        return []

    index, refs = build_lookback_index(current_period, db_path, lookback)
    if index.ntotal == 0:
        logger.info("[Tracker] lookback 데이터 없음 — 전체 신규 처리")
        return []

    lineages: list[ClusterLineage] = []
    con = sqlite3.connect(db_path)
    try:
        for cluster_id, kw_str, blob in current_rows:
            vec = np.frombuffer(blob, dtype=np.float32).copy().reshape(1, 768)
            sims, idxs = index.search(vec, k=min(5, index.ntotal))

            for sim, idx in zip(sims[0], idxs[0]):
                if idx < 0 or sim < sim_threshold:
                    continue
                ref = refs[idx]
                lineage = ClusterLineage(
                    current_period=current_period,
                    current_cluster_id=cluster_id,
                    prev_period=ref.period,
                    prev_cluster_id=ref.cluster_id,
                    similarity=float(sim),
                )
                lineages.append(lineage)

                # upsert
                con.execute(
                    """INSERT OR REPLACE INTO cluster_lineage
                       (current_period, current_cluster_id, prev_period, prev_cluster_id, similarity)
                       VALUES (?, ?, ?, ?, ?)""",
                    (current_period, cluster_id, ref.period, ref.cluster_id, float(sim)),
                )

        con.commit()
    finally:
        con.close()

    logger.info("[Tracker] period=%d: %d개 lineage 매칭 완료", current_period, len(lineages))
    return lineages


def compute_streak(cluster_id: int, period: int, db_path: str) -> int:
    """해당 클러스터로부터 lineage를 역추적해 연속 등장 주차 수를 반환한다.

    streak=1이면 이번 주만 등장 (신규), streak=N이면 N주 연속.
    """
    con = sqlite3.connect(db_path)
    try:
        streak = 1
        cur_period = period
        cur_cluster = cluster_id

        for _ in range(52):  # 무한루프 방지
            row = con.execute(
                """SELECT prev_period, prev_cluster_id FROM cluster_lineage
                   WHERE current_period=? AND current_cluster_id=?
                   ORDER BY similarity DESC LIMIT 1""",
                (cur_period, cur_cluster),
            ).fetchone()

            if row is None:
                break

            prev_period, prev_cluster = row
            # 연속 주차 확인 (period 차이가 1이면 연속)
            if cur_period - prev_period != 1:
                break

            streak += 1
            cur_period = prev_period
            cur_cluster = prev_cluster

        return streak
    finally:
        con.close()


def classify_topic_status(
    current_period: int,
    db_path: str,
) -> dict[str, list[int]]:
    """현재 period 클러스터를 continuing / new / disappeared로 분류한다.

    Returns:
        {"continuing": [cluster_id, ...], "new": [...], "disappeared": [...]}
        disappeared: 직전 period에 있었지만 현재 period에 매칭되지 않은 클러스터
    """
    con = sqlite3.connect(db_path)
    try:
        # 현재 period 클러스터
        current_ids = {
            row[0] for row in con.execute(
                "SELECT cluster_id FROM clusters WHERE period=?", (current_period,)
            ).fetchall()
        }

        # lineage가 있는 현재 클러스터 (continuing)
        matched_ids = {
            row[0] for row in con.execute(
                "SELECT DISTINCT current_cluster_id FROM cluster_lineage WHERE current_period=?",
                (current_period,),
            ).fetchall()
        }

        # 직전 period 클러스터
        prev_period = current_period - 1
        prev_ids = {
            row[0] for row in con.execute(
                "SELECT cluster_id FROM clusters WHERE period=?", (prev_period,)
            ).fetchall()
        }

        # 직전 period 중 현재에 매칭된 클러스터 (disappeared 계산용)
        matched_prev_ids = {
            row[0] for row in con.execute(
                "SELECT DISTINCT prev_cluster_id FROM cluster_lineage WHERE current_period=? AND prev_period=?",
                (current_period, prev_period),
            ).fetchall()
        }
    finally:
        con.close()

    continuing = sorted(matched_ids)
    new_topics = sorted(current_ids - matched_ids)
    disappeared = sorted(prev_ids - matched_prev_ids)

    return {"continuing": continuing, "new": new_topics, "disappeared": disappeared}


def get_cluster_streaks(current_period: int, db_path: str) -> dict[int, int]:
    """현재 period의 모든 클러스터에 대해 streak 딕셔너리를 반환한다.

    Returns:
        {cluster_id: streak_count}
    """
    con = sqlite3.connect(db_path)
    try:
        cluster_ids = [
            row[0] for row in con.execute(
                "SELECT cluster_id FROM clusters WHERE period=?", (current_period,)
            ).fetchall()
        ]
    finally:
        con.close()

    return {cid: compute_streak(cid, current_period, db_path) for cid in cluster_ids}


def run_tracker(period: int, db_path: str, lookback: int = 4, sim_threshold: float = 0.7) -> dict:
    """period 하나에 대한 임베딩 + lineage 매칭을 일괄 실행한다.

    Returns:
        {"matched": int, "continuing": [...], "new": [...], "disappeared": [...], "streaks": {...}}
    """
    model = _get_model()

    # 1. 임베딩 저장
    index_period_clusters(period, db_path, model)

    # 2. lineage 매칭
    lineages = match_lineage(period, db_path, lookback=lookback,
                             sim_threshold=sim_threshold, model=model)

    # 3. 분류
    status = classify_topic_status(period, db_path)
    streaks = get_cluster_streaks(period, db_path)

    logger.info(
        "[Tracker] period=%d — matched=%d continuing=%d new=%d disappeared=%d",
        period, len(lineages),
        len(status["continuing"]), len(status["new"]), len(status["disappeared"]),
    )
    return {
        "matched": len(lineages),
        "continuing": status["continuing"],
        "new": status["new"],
        "disappeared": status["disappeared"],
        "streaks": streaks,
    }
