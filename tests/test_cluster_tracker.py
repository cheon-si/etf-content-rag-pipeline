"""cluster_tracker.py 단위 테스트 — 실제 임베딩 모델 + 임시 SQLite DB 사용."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.clustering.cluster_tracker import (
    ClusterLineage,
    ClusterRef,
    build_lookback_index,
    classify_topic_status,
    compute_streak,
    embed_cluster_keywords,
    get_cluster_streaks,
    index_period_clusters,
    match_lineage,
)


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def embedding_model():
    """모듈 레벨에서 한 번만 모델 로드."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("jhgan/ko-sroberta-multitask")


@pytest.fixture
def tmp_db(tmp_path):
    """테스트용 임시 SQLite DB (clusters + cluster_lineage 테이블 포함)."""
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period INTEGER NOT NULL,
            cluster_id INTEGER NOT NULL,
            keywords TEXT NOT NULL,
            size INTEGER NOT NULL,
            embedding BLOB
        );
        CREATE TABLE cluster_lineage (
            current_period INTEGER NOT NULL,
            current_cluster_id INTEGER NOT NULL,
            prev_period INTEGER NOT NULL,
            prev_cluster_id INTEGER NOT NULL,
            similarity REAL NOT NULL,
            PRIMARY KEY (current_period, current_cluster_id, prev_period, prev_cluster_id)
        );
        CREATE INDEX idx_lineage_current ON cluster_lineage(current_period);
    """)
    con.commit()
    con.close()
    return db_path


def _insert_cluster(db_path: str, period: int, cluster_id: int,
                    keywords: list[str], size: int = 10, embedding: bytes | None = None):
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO clusters (period, cluster_id, keywords, size, embedding) VALUES (?, ?, ?, ?, ?)",
        (period, cluster_id, ",".join(keywords), size, embedding),
    )
    con.commit()
    con.close()


def _insert_lineage(db_path: str, lineage: ClusterLineage):
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT OR REPLACE INTO cluster_lineage VALUES (?, ?, ?, ?, ?)",
        (lineage.current_period, lineage.current_cluster_id,
         lineage.prev_period, lineage.prev_cluster_id, lineage.similarity),
    )
    con.commit()
    con.close()


# ── 테스트 ────────────────────────────────────────────────────────────────────

class TestEmbedClusterKeywords:
    def test_returns_768d(self, embedding_model):
        """임베딩 결과가 768차원 float32 벡터인지 확인."""
        vec = embed_cluster_keywords(["미국ETF", "S&P500", "나스닥"], embedding_model)
        assert vec.shape == (768,)
        assert vec.dtype == np.float32

    def test_normalized(self, embedding_model):
        """L2 정규화 여부 확인 (||v|| ≈ 1.0)."""
        vec = embed_cluster_keywords(["채권", "금리", "국고채"], embedding_model)
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 1e-5


class TestIndexPeriodClusters:
    def test_stores_blob(self, tmp_db, embedding_model):
        """클러스터 임베딩이 DB BLOB으로 저장되는지 확인."""
        _insert_cluster(tmp_db, period=1, cluster_id=0, keywords=["미국ETF", "S&P500"])
        count = index_period_clusters(1, tmp_db, embedding_model)
        assert count == 1

        con = sqlite3.connect(tmp_db)
        blob = con.execute("SELECT embedding FROM clusters WHERE period=1").fetchone()[0]
        con.close()
        assert blob is not None
        vec = np.frombuffer(blob, dtype=np.float32)
        assert vec.shape == (768,)

    def test_skips_already_indexed(self, tmp_db, embedding_model):
        """이미 임베딩된 클러스터는 재처리하지 않는지 확인."""
        dummy_blob = np.zeros(768, dtype=np.float32).tobytes()
        _insert_cluster(tmp_db, period=2, cluster_id=0,
                        keywords=["채권", "금리"], embedding=dummy_blob)
        count = index_period_clusters(2, tmp_db, embedding_model)
        assert count == 0  # 이미 존재 → 건너뜀


class TestMatchLineage:
    def test_above_threshold_matched(self, tmp_db, embedding_model):
        """동일 키워드 클러스터는 similarity ≥ 0.9 로 매칭되어야 한다."""
        kws = ["미국ETF", "S&P500", "나스닥", "TIGER", "배당"]
        vec = embed_cluster_keywords(kws, embedding_model).tobytes()

        # period 3: 과거
        _insert_cluster(tmp_db, period=3, cluster_id=0, keywords=kws, embedding=vec)
        # period 4: 현재 (같은 키워드)
        _insert_cluster(tmp_db, period=4, cluster_id=0, keywords=kws, embedding=vec)

        lineages = match_lineage(4, tmp_db, lookback=4,
                                 sim_threshold=0.7, model=embedding_model)
        assert len(lineages) >= 1
        assert lineages[0].similarity >= 0.9

    def test_below_threshold_not_matched(self, tmp_db, embedding_model):
        """무관한 키워드 클러스터는 매칭되지 않아야 한다."""
        vec_etf = embed_cluster_keywords(["미국ETF", "S&P500", "나스닥"], embedding_model).tobytes()
        vec_unrelated = embed_cluster_keywords(["요리", "레시피", "음식"], embedding_model).tobytes()

        _insert_cluster(tmp_db, period=5, cluster_id=0,
                        keywords=["미국ETF", "S&P500", "나스닥"], embedding=vec_etf)
        _insert_cluster(tmp_db, period=6, cluster_id=0,
                        keywords=["요리", "레시피", "음식"], embedding=vec_unrelated)

        lineages = match_lineage(6, tmp_db, lookback=4,
                                 sim_threshold=0.7, model=embedding_model)
        assert len(lineages) == 0


class TestComputeStreak:
    def test_consecutive_weeks(self, tmp_db):
        """4주 연속 lineage → streak=4."""
        for p in range(10, 14):  # period 10, 11, 12, 13
            _insert_cluster(tmp_db, period=p, cluster_id=0,
                            keywords=["미국ETF"], size=5)

        # 10→11→12→13 lineage 체인
        for p in range(11, 14):
            _insert_lineage(tmp_db, ClusterLineage(
                current_period=p, current_cluster_id=0,
                prev_period=p - 1, prev_cluster_id=0,
                similarity=0.95,
            ))

        streak = compute_streak(cluster_id=0, period=13, db_path=tmp_db)
        assert streak == 4

    def test_new_topic_streak_one(self, tmp_db):
        """lineage 없는 신규 클러스터 → streak=1."""
        _insert_cluster(tmp_db, period=20, cluster_id=0, keywords=["신규토픽"], size=3)
        streak = compute_streak(cluster_id=0, period=20, db_path=tmp_db)
        assert streak == 1


class TestClassifyTopicStatus:
    def test_partitions_correctly(self, tmp_db):
        """continuing/new/disappeared 분류가 정확한지 확인."""
        # period 30: 클러스터 0, 1
        for cid in [0, 1]:
            _insert_cluster(tmp_db, period=30, cluster_id=cid,
                            keywords=[f"키워드{cid}"], size=5)

        # period 31: 클러스터 1(기존), 2(신규)
        for cid in [1, 2]:
            _insert_cluster(tmp_db, period=31, cluster_id=cid,
                            keywords=[f"키워드{cid}"], size=5)

        # 클러스터1은 31→30 lineage 있음 (continuing)
        _insert_lineage(tmp_db, ClusterLineage(
            current_period=31, current_cluster_id=1,
            prev_period=30, prev_cluster_id=1,
            similarity=0.92,
        ))

        result = classify_topic_status(current_period=31, db_path=tmp_db)
        assert 1 in result["continuing"]
        assert 2 in result["new"]
        assert 0 in result["disappeared"]


class TestLookbackWindow:
    def test_excludes_old_periods(self, tmp_db, embedding_model):
        """lookback=4일 때 5주 전 데이터는 FAISS 인덱스에서 제외되어야 한다."""
        kws = ["미국ETF", "S&P500"]
        vec = embed_cluster_keywords(kws, embedding_model).tobytes()

        # period 40: 5주 전 (current=45, lookback=4 → min_period=41이므로 40은 제외)
        _insert_cluster(tmp_db, period=40, cluster_id=0, keywords=kws, embedding=vec)
        # period 42: lookback 범위 내
        _insert_cluster(tmp_db, period=42, cluster_id=0, keywords=kws, embedding=vec)

        index, refs = build_lookback_index(current_period=45, db_path=tmp_db, lookback=4)
        periods_in_index = {ref.period for ref in refs}

        assert 40 not in periods_in_index
        assert 42 in periods_in_index
