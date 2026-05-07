"""
run_youtube_trend.py — YouTube ETF 트렌드 분석

ML로 발굴한 ETF 클러스터 키워드 → YouTube 영상 수집 → 키워드 분석 → 차트 저장
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, ".")

from app.config.constants import GENERIC_KEYWORDS, NOISE_KEYWORDS, SOURCE_DB_CONFIG
from app.config.settings import load_settings
from app.ingestion.youtube_search import collect_youtube_videos
from etf_trend import _init_db, _tokenize, engine
from sqlalchemy import text
from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from app.utils import week_folder as _week_folder
RESULTS_DIR = Path("./results") / _week_folder()
DB_PATH = "etf_trend.db"

def load_cluster_keywords(top_n: int = 5) -> list[str]:
    """DB에서 최신 period 상위 클러스터의 distinctive 키워드 목록 반환."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT period FROM collections WHERE status='done' ORDER BY period DESC LIMIT 1"
    ).fetchone()
    if not row:
        con.close()
        return []
    period = row[0]
    clusters = con.execute(
        "SELECT keywords FROM clusters WHERE period=? ORDER BY size DESC",
        (period,),
    ).fetchall()
    con.close()

    keywords: list[str] = []
    for (kws_str,) in clusters:
        kw_list = [k.strip() for k in kws_str.split(",")]
        if any(n in kw_list for n in NOISE_KEYWORDS):
            continue
        distinctive = [k for k in kw_list[:5] if k.lower() not in GENERIC_KEYWORDS]
        keywords.extend(distinctive[:2])
        if len(keywords) >= top_n * 2:
            break

    # 중복 제거, 상위 N개
    seen: set[str] = set()
    unique = [k for k in keywords if not (k in seen or seen.add(k))]  # type: ignore[func-returns-value]
    logger.info("클러스터 키워드 %d개 추출: %s", len(unique[:top_n]), unique[:top_n])
    return unique[:top_n]


def _get_current_period() -> int:
    """DB의 최신 period 번호 반환."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT period FROM collections WHERE status='done' ORDER BY period DESC LIMIT 1"
    ).fetchone()
    con.close()
    return row[0] if row else 1


def save_youtube_keywords(period: int, df: pd.DataFrame) -> None:
    """youtube_keywords 테이블에 저장."""
    _init_db()
    # 기존 period 데이터 삭제 후 재저장
    with engine.connect() as conn:
        conn.execute(text(f"DELETE FROM youtube_keywords WHERE period={period}"))
        conn.commit()

    from etf_trend import YoutubeKeyword
    with Session(engine) as session:
        for _, row in df.iterrows():
            session.add(YoutubeKeyword(
                period=period,
                keyword=str(row["keyword"]),
                frequency=int(row["frequency"]),
                avg_view_count=float(row.get("avg_view_count", 0)),
                video_count=int(row.get("video_count", 0)),
            ))
        session.commit()
    logger.info("youtube_keywords 테이블 저장 완료 (period=%d, rows=%d)", period, len(df))


def extract_keywords_from_videos(videos: list[dict]) -> pd.DataFrame:
    """영상 제목+설명에서 키워드 추출 후 빈도 집계."""
    from collections import Counter
    freq: Counter[str] = Counter()
    view_by_kw: dict[str, list[int]] = {}

    for v in videos:
        text = f"{v.get('title', '')} {v.get('description', '')}"
        tokenized = _tokenize(text)
        view = int(v.get("view_count", 0))
        for kw in tokenized.split():
            freq[kw] += 1
            view_by_kw.setdefault(kw, []).append(view)

    rows = []
    for kw, cnt in freq.most_common(30):
        views = view_by_kw.get(kw, [0])
        rows.append({
            "keyword": kw,
            "frequency": cnt,
            "avg_view_count": round(sum(views) / len(views), 0),
            "video_count": len(views),
        })
    return pd.DataFrame(rows)


def generate_charts(videos: list[dict], kw_df: pd.DataFrame) -> None:
    """조회수 상위 10 영상 + 키워드 빈도 차트 저장."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 조회수 상위 10 영상 막대 차트 ─────────────────────────────────────
    top10 = sorted(videos, key=lambda v: int(v.get("view_count", 0)), reverse=True)[:10]
    if top10:
        titles = [v["title"][:40] + "..." if len(v["title"]) > 40 else v["title"] for v in top10]
        views = [v["view_count"] for v in top10]
        channels = [v["channel_title"] for v in top10]

        fig = go.Figure(go.Bar(
            x=views[::-1],
            y=[f"{t}<br><sub>{c}</sub>" for t, c in zip(titles[::-1], channels[::-1])],
            orientation="h",
            marker_color="#e74c3c",
            text=[f"{v:,}" for v in views[::-1]],
            textposition="outside",
        ))
        fig.update_layout(
            title="ETF 관련 YouTube 조회수 상위 10개 영상 (최근 1주)",
            height=520,
            margin=dict(l=300, r=100),
            xaxis_title="조회수",
            plot_bgcolor="#f8f9fa",
        )
        fig.write_html(str(RESULTS_DIR / "youtube_top_videos.html"))
        logger.info("Saved youtube_top_videos.html")

    # ── 2. YouTube 키워드 빈도 Top 20 ────────────────────────────────────────
    if not kw_df.empty:
        top20_kw = kw_df.head(20)
        fig2 = go.Figure(go.Bar(
            x=top20_kw["frequency"].tolist()[::-1],
            y=top20_kw["keyword"].tolist()[::-1],
            orientation="h",
            marker_color="#9b59b6",
            text=top20_kw["frequency"].tolist()[::-1],
            textposition="outside",
        ))
        fig2.update_layout(
            title="YouTube ETF 영상 추출 키워드 Top 20 (빈도수)",
            height=520,
            margin=dict(l=100, r=60),
            xaxis_title="빈도수",
            plot_bgcolor="#f8f9fa",
        )
        fig2.write_html(str(RESULTS_DIR / "youtube_keywords.html"))
        logger.info("Saved youtube_keywords.html")


def main(source: str = "blog") -> None:
    global DB_PATH, RESULTS_DIR
    cfg = SOURCE_DB_CONFIG[source]
    DB_PATH = cfg["db"]
    _week = _week_folder()
    RESULTS_DIR = Path("results") / _week / "news" if source == "news" else Path("results") / _week
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("YouTube 소스: %s | DB=%s | 결과 경로=%s", source, DB_PATH, RESULTS_DIR)

    settings = load_settings()
    api_key = settings.get("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.error("YOUTUBE_API_KEY가 .env에 설정되지 않았습니다.")
        return

    # 클러스터 키워드 로드
    keywords = load_cluster_keywords(top_n=5)
    if not keywords:
        logger.error("DB에서 클러스터 키워드를 불러올 수 없습니다. run_weekly_track.py 먼저 실행하세요.")
        return

    # YouTube 수집
    logger.info("YouTube 수집 시작 (keywords=%d, days=7)", len(keywords))
    search_queries = [f"{kw} ETF" for kw in keywords]
    videos = collect_youtube_videos(
        keywords=search_queries,
        days=7,
        max_per_keyword=50,
        api_key=api_key,
    )
    if not videos:
        logger.warning("수집된 YouTube 영상이 없습니다.")
        return

    # CSV 저장
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df_videos = pd.DataFrame(videos)
    df_videos.to_csv(RESULTS_DIR / "youtube_raw.csv", index=False, encoding="utf-8-sig")
    logger.info("Saved youtube_raw.csv (%d영상)", len(df_videos))

    # 키워드 추출
    kw_df = extract_keywords_from_videos(videos)
    if not kw_df.empty:
        kw_df.to_csv(RESULTS_DIR / "youtube_top_keywords.csv", index=False, encoding="utf-8-sig")
        logger.info("Saved youtube_top_keywords.csv (%d키워드)", len(kw_df))

    # DB 저장
    period = _get_current_period()
    save_youtube_keywords(period, kw_df)

    # 차트 생성
    generate_charts(videos, kw_df)

    print(f"\n결과 저장 완료: {RESULTS_DIR.resolve()}")
    print(f"  - youtube_raw.csv          : 수집 영상 {len(videos)}개")
    print(f"  - youtube_top_keywords.csv : 상위 키워드 {len(kw_df)}개")
    print("  - youtube_top_videos.html  : 조회수 상위 10 차트")
    print("  - youtube_keywords.html    : 키워드 빈도 차트")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["blog", "news"], default="blog",
                        help="분석 소스 DB (기본값: blog)")
    args = parser.parse_args()
    main(source=args.source)
