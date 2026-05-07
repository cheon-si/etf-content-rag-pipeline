"""
run_datalab_trend.py — 네이버 DataLab API로 ETF 테마별 검색량 트렌드 분석

ML로 발굴한 ETF 테마 키워드 → DataLab 주간 검색량 → 선형회귀 → 시각화
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from scipy.stats import linregress

sys.path.insert(0, ".")
from app.config.constants import GENERIC_KEYWORDS, NOISE_KEYWORDS, SOURCE_DB_CONFIG
from app.config.settings import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from app.utils import week_folder as _week_folder
RESULTS_DIR = Path("./results") / _week_folder()
DB_PATH = "etf_trend.db"

def _get_date_range() -> tuple[str, str]:
    """DB의 수집 기간 기준으로 DataLab 조회 범위를 자동 계산.
    collections 테이블이 없거나 비어있으면 최근 90일을 기본값으로 사용."""
    import sqlite3
    from datetime import datetime, timedelta
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT MIN(rowid), MAX(rowid) FROM collections WHERE status='done'"
        ).fetchone()
        con.close()
    except Exception:
        row = None

    end = datetime.now()
    # DataLab은 현재일 기준 최대 1년치 제공 → 연초부터 현재까지
    start = end.replace(month=1, day=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def load_top_clusters(top_n: int = 5) -> list[dict]:
    """DB에서 최신 period 상위 N개 클러스터 로드 (노이즈 제외)."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT period FROM collections WHERE status='done' ORDER BY period DESC LIMIT 1"
    ).fetchone()
    if not row or row[0] is None:
        con.close()
        return []
    period = row[0]
    logger.info("DataLab 클러스터 기준 period=%d", period)
    clusters = con.execute(
        "SELECT cluster_id, size, keywords FROM clusters WHERE period=? ORDER BY size DESC",
        (period,),
    ).fetchall()
    con.close()

    result = []
    for cid, size, kws in clusters:
        kw_list = [k.strip() for k in kws.split(",")]
        # 노이즈 키워드 포함 클러스터 제외
        if any(n in kw_list for n in NOISE_KEYWORDS):
            continue
        # 상위 5개 키워드가 전부 범용어면 제외 (의미없는 클러스터)
        distinctive = [k for k in kw_list[:5] if k.lower() not in GENERIC_KEYWORDS]
        if len(distinctive) < 2:
            logger.info("  C%d 범용 클러스터 스킵 (distinctive=%d)", cid, len(distinctive))
            continue
        result.append({"cluster_id": cid, "size": size, "keywords": kw_list})
        if len(result) >= top_n:
            break
    return result


def build_keyword_groups(clusters: list[dict]) -> list[dict]:
    """클러스터 키워드 → DataLab keyword_groups 형식으로 변환."""
    groups = []
    for c in clusters:
        distinctive = [k for k in c["keywords"] if k.lower() not in GENERIC_KEYWORDS]
        top = distinctive[:3] if distinctive else c["keywords"][:3]
        group_name = "/".join(top)
        keywords = [f"{k} ETF" for k in top[:2]]
        groups.append({"groupName": group_name, "keywords": keywords})
        logger.info("  클러스터 C%d (size=%d) → %s | DataLab: %s",
                    c["cluster_id"], c["size"], group_name, keywords)
    return groups


def call_datalab(
    keyword_groups: list[dict],
    start_date: str,
    end_date: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """네이버 DataLab 검색어 트렌드 API 호출."""
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "week",
        "keywordGroups": keyword_groups,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_datalab_response(response: dict, batch: str) -> pd.DataFrame:
    """DataLab 응답을 DataFrame으로 변환."""
    records = []
    for result in response.get("results", []):
        group_name = result["title"]
        for point in result.get("data", []):
            records.append({
                "theme": group_name,
                "date": point["period"],
                "ratio": point["ratio"],
                "batch": batch,
            })
    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def run_linear_regression(df: pd.DataFrame) -> pd.DataFrame:
    """테마별 선형회귀 — 기울기, R², 방향 계산."""
    results = []
    for theme, group in df.groupby("theme"):
        group = group.sort_values("date")
        x = np.arange(len(group))
        y = group["ratio"].values
        if len(x) < 3:
            continue
        slope, intercept, r_value, p_value, _ = linregress(x, y)
        results.append({
            "theme": theme,
            "slope": round(slope, 4),
            "r_squared": round(r_value ** 2, 4),
            "p_value": round(p_value, 4),
            "avg_ratio": round(y.mean(), 2),
            "direction": "상승 ↑" if slope > 0 else "하락 ↓",
            "significant": "O" if p_value < 0.05 else "X",
        })
    return pd.DataFrame(results).sort_values("slope", ascending=False)


def generate_charts(df: pd.DataFrame, regression_df: pd.DataFrame, batch_labels: dict[str, str]) -> None:
    """트렌드 라인 + 선형회귀 차트 생성."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 상위/하위 그룹별 주간 검색량 트렌드 ────────────────────────────
    for batch_name, label in batch_labels.items():
        batch_df = df[df["batch"] == batch_name]

        fig = go.Figure()
        for theme, group in batch_df.groupby("theme"):
            group = group.sort_values("date")
            # 선형회귀 추세선 추가
            x_num = np.arange(len(group))
            slope, intercept, _, _, _ = linregress(x_num, group["ratio"].values)
            trend_y = intercept + slope * x_num

            fig.add_trace(go.Scatter(
                x=group["date"], y=group["ratio"],
                mode="lines+markers", name=theme,
            ))
            fig.add_trace(go.Scatter(
                x=group["date"], y=trend_y,
                mode="lines", name=f"{theme} 추세",
                line=dict(dash="dash", width=1),
                showlegend=False,
            ))

        fig.update_layout(
            title=f"ETF 테마 검색량 트렌드 [{label}] (네이버 DataLab, 2026-01~04)<br><sub>점선=선형회귀 추세선, 같은 배치 내 상대 비교 가능</sub>",
            xaxis_title="날짜",
            yaxis_title="상대 검색량 (0~100, 배치 내 최고=100)",
            height=550,
        )
        fname = f"datalab_trend_{batch_name}.html"
        fig.write_html(str(RESULTS_DIR / fname))
        logger.info("Saved %s", fname)

    # ── 2. 선형회귀 기울기 바 차트 ────────────────────────────────────────
    reg = regression_df.sort_values("slope")
    colors = ["#e74c3c" if s < 0 else "#2ecc71" for s in reg["slope"]]

    fig_reg = go.Figure(go.Bar(
        x=reg["slope"],
        y=reg["theme"],
        orientation="h",
        marker_color=colors,
        text=[f"slope={s:.4f} R²={r:.3f} p={p:.3f}"
              for s, r, p in zip(reg["slope"], reg["r_squared"], reg["p_value"])],
        textposition="outside",
    ))
    fig_reg.update_layout(
        title="ETF 테마 검색 트렌드 선형회귀 기울기 (양수=상승, 음수=하락)",
        xaxis_title="기울기 (slope)",
        height=600,
        margin=dict(l=200),
    )
    fig_reg.write_html(str(RESULTS_DIR / "datalab_regression.html"))
    logger.info("Saved datalab_regression.html")

    # ── 3. 상승/하락 히트맵 ──────────────────────────────────────────────
    pivot = df.pivot_table(index="theme", columns="date", values="ratio")
    pivot.columns = [str(c.date()) for c in pivot.columns]

    fig_heatmap = go.Figure(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale="RdYlGn",
        hoverongaps=False,
    ))
    fig_heatmap.update_layout(
        title="ETF 테마별 검색량 히트맵 (빨강=낮음, 초록=높음)",
        height=500,
        yaxis=dict(autorange="reversed"),
    )
    fig_heatmap.write_html(str(RESULTS_DIR / "datalab_heatmap.html"))
    logger.info("Saved datalab_heatmap.html")


def main(source: str = "blog") -> None:
    global DB_PATH, RESULTS_DIR
    cfg = SOURCE_DB_CONFIG[source]
    DB_PATH = cfg["db"]
    _week = _week_folder()
    RESULTS_DIR = Path("results") / _week / "news" if source == "news" else Path("results") / _week
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("DataLab 소스: %s | DB=%s | 결과 경로=%s", source, DB_PATH, RESULTS_DIR)

    settings = load_settings()
    client_id = settings["NAVER_CLIENT_ID"]
    client_secret = settings["NAVER_CLIENT_SECRET"]
    START_DATE, END_DATE = _get_date_range()
    logger.info("DataLab 조회 기간: %s ~ %s", START_DATE, END_DATE)

    # ML 클러스터 상위 5개 로드
    clusters = load_top_clusters(top_n=5)
    if not clusters:
        logger.error("DB에서 클러스터를 불러올 수 없습니다. run_weekly_track.py 먼저 실행하세요.")
        return
    logger.info("상위 %d개 클러스터 로드 완료", len(clusters))
    keyword_groups = build_keyword_groups(clusters)

    all_dfs = []
    batch_labels = {"clusters": "ML 클러스터 상위 5"}

    logger.info("DataLab API 호출 (groups=%d)...", len(keyword_groups))
    try:
        resp = call_datalab(keyword_groups, START_DATE, END_DATE, client_id, client_secret)
        df_batch = parse_datalab_response(resp, batch="clusters")
        logger.info("  → %d개 데이터 포인트 수신", len(df_batch))
        all_dfs.append(df_batch)
    except Exception as exc:
        logger.error("DataLab API 실패: %s", exc)

    if not all_dfs:
        logger.error("DataLab 데이터 없음. API 키 확인 필요.")
        return

    df = pd.concat(all_dfs, ignore_index=True)
    logger.info("전체 데이터: %d행, %d개 테마", len(df), df["theme"].nunique())

    # CSV 저장
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "datalab_raw.csv", index=False, encoding="utf-8-sig")
    logger.info("Saved datalab_raw.csv")

    # 선형회귀
    regression_df = run_linear_regression(df)
    regression_df.to_csv(RESULTS_DIR / "datalab_regression.csv", index=False, encoding="utf-8-sig")

    print("\n=== ETF 테마 검색 트렌드 선형회귀 결과 ===")
    print(f"{'테마':<20} {'기울기':>8} {'R²':>8} {'p값':>8} {'방향':>6} {'유의':>4}")
    print("-" * 60)
    for _, row in regression_df.iterrows():
        print(f"{row['theme']:<20} {row['slope']:>8.4f} {row['r_squared']:>8.4f} "
              f"{row['p_value']:>8.4f} {row['direction']:>6} {row['significant']:>4}")

    # 차트 생성
    generate_charts(df, regression_df, batch_labels)

    print(f"\n결과 저장 완료: {RESULTS_DIR.resolve()}")
    print("  - datalab_trend_clusters.html : ML 클러스터 상위 5 트렌드 (배치 내 상대비교)")
    print("  - datalab_regression.html     : 전체 선형회귀 기울기 차트")
    print("  - datalab_heatmap.html        : 테마별 히트맵")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["blog", "news"], default="blog",
                        help="분석 소스 DB (기본값: blog)")
    args = parser.parse_args()
    main(source=args.source)
