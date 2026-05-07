"""
run_generate_report.py — ETF 키워드 트렌드 분석 팀장 보고서 생성기
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from scipy.stats import linregress

sys.path.insert(0, ".")

import logging

from app.config.constants import GENERIC_KEYWORDS, NOISE_KEYWORDS

logger = logging.getLogger(__name__)

from app.utils import week_folder as _week_folder

_PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = _PROJECT_ROOT / "results" / _week_folder()
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")
REPORT_PATH = RESULTS_DIR / "etf_trend_report.html"

_SOURCE_CONFIG = {
    "blog": {
        "db":          str(_PROJECT_ROOT / "etf_trend.db"),
        "report":      RESULTS_DIR / "etf_trend_report.html",
        "results_dir": RESULTS_DIR,
        "label":       "블로그",
    },
    "news": {
        "db":          str(_PROJECT_ROOT / "etf_trend_news.db"),
        "report":      RESULTS_DIR / "news" / "etf_trend_news_report.html",
        "results_dir": RESULTS_DIR / "news",
        "label":       "뉴스",
    },
}


# ── 데이터 로드 ────────────────────────────────────────────────────────────────

def _get_latest_done_period(con: sqlite3.Connection) -> int:
    """status='done' 중 가장 최신 period 번호를 반환한다. 데이터 없으면 1 반환."""
    row = con.execute(
        "SELECT period FROM collections WHERE status='done' ORDER BY period DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else 1


def load_db_data():
    con = sqlite3.connect(DB_PATH)
    period = _get_latest_done_period(con)
    clusters = con.execute(
        "SELECT cluster_id, size, keywords FROM clusters WHERE period=? ORDER BY size DESC",
        (period,),
    ).fetchall()
    keywords = con.execute(
        "SELECT keyword, frequency FROM keywords WHERE period=? ORDER BY frequency DESC LIMIT 30",
        (period,),
    ).fetchall()
    cluster_run = con.execute(
        "SELECT k, silhouette FROM cluster_runs WHERE period=?",
        (period,),
    ).fetchone()
    collection = con.execute(
        "SELECT post_count, run_date FROM collections WHERE period=?",
        (period,),
    ).fetchone()
    con.close()
    return clusters, keywords, cluster_run, collection


def load_lineage_info(period: int) -> dict[int, dict]:
    """해당 period 클러스터의 lineage 정보를 반환한다.

    Returns:
        {cluster_id: {"streak": int, "status": "continuing"|"new"}}
    """
    try:
        from app.clustering.cluster_tracker import classify_topic_status, get_cluster_streaks
        status = classify_topic_status(period, DB_PATH)
        streaks = get_cluster_streaks(period, DB_PATH)
        result = {}
        for cid, streak in streaks.items():
            if cid in status["continuing"]:
                topic_status = "continuing"
            else:
                topic_status = "new"
            result[cid] = {"streak": streak, "status": topic_status}
        return result
    except Exception:
        return {}


def load_latest_clusters() -> list[dict]:
    """Load clusters from the most recent period for content idea generation."""
    con = sqlite3.connect(DB_PATH)
    latest_period = _get_latest_done_period(con)
    clusters = con.execute(
        "SELECT cluster_id, size, keywords FROM clusters WHERE period=? ORDER BY size DESC",
        (latest_period,),
    ).fetchall()
    con.close()
    return [{"cluster_id": cid, "size": size, "keywords": kws.split(",")}
            for cid, size, kws in clusters]


def load_datalab_data():
    raw_path = RESULTS_DIR / "datalab_raw.csv"
    reg_path = RESULTS_DIR / "datalab_regression.csv"
    if not raw_path.exists() or not reg_path.exists():
        logger.warning("DataLab CSV 없음 — 빈 DataFrame 반환 (datalab_raw.csv / datalab_regression.csv)")
        return pd.DataFrame(), pd.DataFrame()
    raw = pd.read_csv(raw_path)
    raw["date"] = pd.to_datetime(raw["date"])
    reg = pd.read_csv(reg_path)
    return raw, reg


def load_period_trend_data() -> pd.DataFrame:
    """
    모든 period의 keywords 테이블을 로드하여 기간별 키워드 빈도 피벗 반환.
    period가 1개뿐이면 빈 DataFrame 반환.
    """
    try:
        con = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT period, keyword, frequency FROM keywords WHERE frequency >= 5"
            " ORDER BY period, frequency DESC",
            con,
        )
        con.close()
        if df.empty or df["period"].nunique() < 2:
            return pd.DataFrame()

        # period별 상위 200개로 제한 (노이즈 단어 제거)
        chunks = []
        for p, grp in df.groupby("period"):
            chunks.append(grp.head(200))
        return pd.concat(chunks, ignore_index=True)
    except Exception as exc:
        logger.warning("기간별 트렌드 데이터 로드 실패: %s", exc)
        return pd.DataFrame()


_LDA_STOPWORDS = {
    "합니다", "있습니다", "됩니다", "입니다", "있는", "있는데", "하지만", "그리고",
    "또한", "이러한", "다양한", "통해", "있어요", "많은", "많은데", "하면",
    "경우", "위해", "이후", "전에", "다시", "있고", "보는", "보면", "같이",
    "때문", "사람", "정말", "모든", "우리", "정도", "이상", "이하", "기준",
    "내용", "관련", "부분", "정보", "확인", "때문", "또는", "하여", "가장",
    "현재", "이번", "지금", "다음", "매우", "특히", "이미", "아직", "그냥",
}


def load_lda_topics(source: str = "blog") -> list[list[str]]:
    """filtered_docs.json의 clean_text에서 명사를 추출해 LDA 토픽 10개를 반환한다."""
    try:
        import json
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import LatentDirichletAllocation

        cfg = _SOURCE_CONFIG[source]
        json_path = _PROJECT_ROOT / "data" / "processed" / "filtered_docs.json"
        if not json_path.exists():
            logger.warning("LDA: filtered_docs.json 없음 — %s", json_path)
            return []

        with open(json_path, encoding="utf-8") as f:
            docs = json.load(f)

        raw_texts = [d.get("clean_text", "") for d in docs if d.get("clean_text")]
        if len(raw_texts) < 10:
            return []

        # kiwipiepy로 명사(NN*) + 외래어(SL) 2자 이상만 추출
        try:
            from kiwipiepy import Kiwi
            kiwi = Kiwi()
            noun_texts = []
            for text in raw_texts:
                nouns = [
                    tok.form for tok in kiwi.tokenize(text)
                    if (tok.tag.startswith("NN") or tok.tag == "SL")
                    and len(tok.form) >= 2
                    and tok.form.lower() not in _LDA_STOPWORDS
                ]
                noun_texts.append(" ".join(nouns))
            texts = noun_texts
            logger.info("LDA: kiwipiepy 명사 추출 완료 (%d docs)", len(texts))
        except Exception as kiwi_exc:
            logger.warning("LDA: kiwipiepy 실패, 한국어 정규식 폴백: %s", kiwi_exc)
            import re
            ko_re = re.compile(r"[가-힣]{2,}")
            texts = [
                " ".join(w for w in ko_re.findall(t) if w not in _LDA_STOPWORDS)
                for t in raw_texts
            ]

        vec = TfidfVectorizer(min_df=3, max_df=0.60, max_features=300)
        X = vec.fit_transform(texts)
        feature_names = vec.get_feature_names_out()

        lda = LatentDirichletAllocation(n_components=10, random_state=42)
        lda.fit(X)

        topics = []
        for comp in lda.components_:
            top_idx = comp.argsort()[::-1][:10]
            topics.append([feature_names[i] for i in top_idx])
        return topics
    except Exception as exc:
        logger.warning("LDA 실행 실패: %s", exc)
        return []


def load_youtube_data() -> tuple["pd.DataFrame", "pd.DataFrame"]:
    """YouTube raw/keywords CSV 로드. 파일 없으면 빈 DataFrame 반환."""
    raw_path = RESULTS_DIR / "youtube_raw.csv"
    kw_path = RESULTS_DIR / "youtube_top_keywords.csv"
    try:
        df_raw = pd.read_csv(raw_path) if raw_path.exists() else pd.DataFrame()
        df_kw = pd.read_csv(kw_path) if kw_path.exists() else pd.DataFrame()
        return df_raw, df_kw
    except Exception as exc:
        logger.warning("YouTube 데이터 로드 실패: %s", exc)
        return pd.DataFrame(), pd.DataFrame()


# ── 차트 생성 (인라인 삽입용) ─────────────────────────────────────────────────

def make_keyword_bar(keywords):
    kws = [k[0] for k in keywords[:20]]
    freqs = [k[1] for k in keywords[:20]]
    fig = go.Figure(go.Bar(
        x=freqs[::-1], y=kws[::-1],
        orientation="h",
        marker_color="#4A90D9",
        text=freqs[::-1], textposition="outside",
    ))
    fig.update_layout(
        title="Top 20 추출 키워드 (빈도수)",
        height=520,
        margin=dict(l=120, r=60),
        xaxis_title="빈도수",
        plot_bgcolor="#f8f9fa",
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def cluster_name(keywords_str: str) -> str:
    """상위 키워드에서 범용어를 제거하고 의미 있는 클러스터 이름 반환."""
    kws = [k.strip() for k in keywords_str.split(",")]
    distinctive = [k for k in kws if k.lower() not in GENERIC_KEYWORDS]
    top = distinctive[:3] if distinctive else kws[:3]
    return "/".join(top)


def make_cluster_pie(clusters):
    # 노이즈 클러스터 제외 (naver, blog, com 등 포함)
    clean_clusters = []
    for cid, size, kws in clusters:
        kw_list = kws.split(",")
        if not any(n in kw_list for n in NOISE_KEYWORDS):
            clean_clusters.append((cid, size, kws))

    labels = []
    values = []
    for cid, size, kws in clean_clusters:
        labels.append(cluster_name(kws))
        values.append(size)

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.35,
        textinfo="label+percent",
        textposition="outside",
    ))
    fig.update_layout(
        title="클러스터별 포스트 분포 (노이즈 클러스터 제외)",
        height=500,
        showlegend=False,
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def make_trend_chart(df, batch, title):
    batch_df = df[df["batch"] == batch]
    fig = go.Figure()
    colors = ["#e74c3c","#3498db","#2ecc71","#f39c12","#9b59b6"]
    for i, (theme, group) in enumerate(batch_df.groupby("theme")):
        group = group.sort_values("date")
        x_num = np.arange(len(group))
        slope, intercept, _, _, _ = linregress(x_num, group["ratio"].values)
        trend_y = intercept + slope * x_num
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=group["date"], y=group["ratio"],
            mode="lines+markers", name=theme,
            line=dict(color=color, width=2),
            marker=dict(size=6),
        ))
        fig.add_trace(go.Scatter(
            x=group["date"], y=trend_y,
            mode="lines", showlegend=False,
            line=dict(color=color, width=1, dash="dash"),
        ))
    fig.update_layout(
        title=title,
        xaxis_title="날짜",
        yaxis_title="상대 검색량 (배치 내 최고=100)",
        height=420,
        plot_bgcolor="#f8f9fa",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def make_regression_bar(reg):
    reg_sorted = reg.sort_values("slope")
    colors = ["#e74c3c" if s < 0 else "#2ecc71" for s in reg_sorted["slope"]]
    sig_mark = ["★" if p < 0.05 else "  " for p in reg_sorted["p_value"]]
    labels = [f"{m} {t}" for m, t in zip(sig_mark, reg_sorted["theme"])]

    fig = go.Figure(go.Bar(
        x=reg_sorted["slope"],
        y=labels,
        orientation="h",
        marker_color=colors,
        text=[f"slope={s:.3f}  R²={r:.3f}  p={p:.4f}"
              for s, r, p in zip(reg_sorted["slope"], reg_sorted["r_squared"], reg_sorted["p_value"])],
        textposition="outside",
    ))
    fig.update_layout(
        title="ETF 테마별 선형회귀 기울기 (★ = p<0.05 통계적 유의)",
        xaxis_title="기울기 (slope)",
        height=500,
        margin=dict(l=220, r=150),
        plot_bgcolor="#f8f9fa",
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


# ── 기간별 키워드 추이 섹션 HTML 빌드 ─────────────────────────────────────────

def _build_period_trend_section_html(df: pd.DataFrame) -> str:
    """Section 8 — 기간별 키워드 추이 HTML 빌드."""
    if df.empty:
        return """
        <div class="insight">
          데이터가 2개 이상의 period 쌓이면 자동으로 분석됩니다.<br>
          매주 run_all.py 실행 후 다음 주 보고서에서 확인 가능합니다.
        </div>"""

    periods = sorted(df["period"].unique())
    latest = periods[-1]
    prev = periods[-2]

    latest_kws = set(df[df["period"] == latest]["keyword"])
    prev_kws   = set(df[df["period"] == prev]["keyword"])

    # 분류
    recurring = latest_kws & prev_kws          # 반복 등장
    new_kws   = latest_kws - prev_kws          # 신규
    fading    = prev_kws - latest_kws          # 소멸

    # 반복 키워드: 최신 빈도 기준 정렬, 상위 20개
    df_latest  = df[df["period"] == latest].set_index("keyword")["frequency"]
    df_prev    = df[df["period"] == prev].set_index("keyword")["frequency"]

    recurring_rows = []
    for kw in sorted(recurring, key=lambda k: df_latest.get(k, 0), reverse=True)[:20]:
        f_now  = df_latest.get(kw, 0)
        f_prev = df_prev.get(kw, 0)
        delta  = f_now - f_prev
        arrow  = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        color  = "#27ae60" if delta > 0 else ("#e74c3c" if delta < 0 else "#888")
        recurring_rows += [f"""
        <tr>
          <td><strong>{kw}</strong></td>
          <td style="text-align:center">{f_prev}</td>
          <td style="text-align:center">{f_now}</td>
          <td style="text-align:center;color:{color};font-weight:bold">{arrow} {delta:+d}</td>
        </tr>"""]

    recurring_html = "".join(recurring_rows) or "<tr><td colspan=4 style='color:#999'>해당 없음</td></tr>"

    # 신규/소멸 뱃지
    def _badges(kws_set, color):
        return "".join(
            f'<span style="background:{color}20;border:1px solid {color};border-radius:12px;'
            f'padding:2px 8px;margin:2px;display:inline-block;font-size:0.85em">{k}</span>'
            for k in sorted(kws_set)[:30]
        ) or '<span style="color:#999">없음</span>'

    new_badges    = _badges(new_kws,  "#27ae60")
    fading_badges = _badges(fading,   "#e74c3c")

    return f"""
    <div class="cards" style="margin-bottom:20px">
      <div class="card"><div class="num">{len(periods)}</div><div class="lbl">누적 수집 횟수</div></div>
      <div class="card"><div class="num">{len(recurring)}</div><div class="lbl">반복 등장 키워드</div></div>
      <div class="card"><div class="num">{len(new_kws)}</div><div class="lbl">이번 주 신규</div></div>
      <div class="card"><div class="num">{len(fading)}</div><div class="lbl">소멸 (전주 대비)</div></div>
    </div>

    <h3 style="font-size:1em;color:#0f3460;margin:16px 0 8px">반복 등장 키워드 Top 20 (빈도 변화)</h3>
    <table>
      <thead>
        <tr><th>키워드</th><th>이전 period 빈도</th><th>최신 period 빈도</th><th>변화</th></tr>
      </thead>
      <tbody>{recurring_html}</tbody>
    </table>

    <h3 style="font-size:1em;color:#27ae60;margin:20px 0 8px">이번 주 신규 등장 키워드</h3>
    <div>{new_badges}</div>

    <h3 style="font-size:1em;color:#e74c3c;margin:20px 0 8px">소멸 키워드 (전주 대비)</h3>
    <div>{fading_badges}</div>

    <div class="insight" style="margin-top:16px">
      <strong>해석 가이드:</strong>
      반복 등장 키워드 = 지속적 관심 주제 (핵심 콘텐츠 후보) ·
      신규 키워드 = 이번 주 새로 부상한 이슈 ·
      소멸 키워드 = 관심 소멸 또는 계절성 이벤트 종료 신호
    </div>"""


# ── YouTube 섹션 HTML 빌드 ────────────────────────────────────────────────────

def make_youtube_top_videos_chart(df_raw: "pd.DataFrame") -> str:
    """조회수 상위 10 영상 인라인 차트."""
    if df_raw.empty:
        return ""
    top10 = df_raw.nlargest(10, "view_count")
    titles = [
        (t[:40] + "...") if len(str(t)) > 40 else str(t)
        for t in top10["title"]
    ]
    views = top10["view_count"].tolist()
    channels = top10["channel_title"].tolist()

    fig = go.Figure(go.Bar(
        x=views[::-1],
        y=[f"{t} ({c})" for t, c in zip(titles[::-1], channels[::-1])],
        orientation="h",
        marker_color="#e74c3c",
        text=[f"{v:,}" for v in views[::-1]],
        textposition="outside",
    ))
    fig.update_layout(
        title="ETF 관련 YouTube 조회수 상위 10개 영상 (최근 1주)",
        height=480,
        margin=dict(l=360, r=80),
        xaxis_title="조회수",
        plot_bgcolor="#f8f9fa",
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def make_youtube_keyword_chart(df_kw: "pd.DataFrame", blog_keywords: list, source_label: str = "블로그") -> str:
    """YouTube 키워드 Top 20 차트. 소스 키워드와 겹치는 키워드 강조."""
    if df_kw.empty:
        return ""
    top20 = df_kw.head(20)
    blog_kw_set = {k[0] for k in blog_keywords}
    colors = [
        "#e74c3c" if kw in blog_kw_set else "#9b59b6"
        for kw in top20["keyword"].tolist()
    ]
    fig = go.Figure(go.Bar(
        x=top20["frequency"].tolist()[::-1],
        y=top20["keyword"].tolist()[::-1],
        orientation="h",
        marker_color=colors[::-1],
        text=top20["frequency"].tolist()[::-1],
        textposition="outside",
    ))
    fig.update_layout(
        title=f"YouTube ETF 영상 키워드 Top 20 (빨강={source_label}와 겹치는 핵심 키워드)",
        height=500,
        margin=dict(l=100, r=60),
        xaxis_title="빈도수",
        plot_bgcolor="#f8f9fa",
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _build_youtube_section_html(df_raw: "pd.DataFrame", df_kw: "pd.DataFrame", blog_keywords: list, source_label: str = "블로그") -> str:
    """Section 7 전체 HTML 빌드."""
    if df_raw.empty:
        return """<div style="color:#888;padding:20px;text-align:center">
          YOUTUBE_API_KEY를 .env에 설정하고 run_youtube_trend.py를 실행하면 YouTube 트렌드가 표시됩니다.
        </div>"""

    chart_top_videos = make_youtube_top_videos_chart(df_raw)
    chart_keywords = make_youtube_keyword_chart(df_kw, blog_keywords, source_label)

    blog_kw_set = {k[0] for k in blog_keywords}
    if not df_kw.empty:
        yt_kw_set = set(df_kw["keyword"].tolist())
        overlap = sorted(blog_kw_set & yt_kw_set)
        overlap_html = "".join(
            f'<span style="background:#fdecea;border:1px solid #e74c3c;border-radius:12px;'
            f'padding:3px 10px;margin:3px;display:inline-block;font-weight:bold">{k}</span>'
            for k in overlap[:15]
        ) if overlap else '<span style="color:#888">공통 키워드 없음</span>'
    else:
        overlap_html = '<span style="color:#888">데이터 없음</span>'

    video_count = len(df_raw)
    return f"""
    <div class="cards" style="margin-bottom:20px">
      <div class="card"><div class="num">{video_count:,}</div><div class="lbl">수집 영상 수</div></div>
      <div class="card"><div class="num">{len(df_kw) if not df_kw.empty else 0}</div><div class="lbl">추출 키워드 수</div></div>
      <div class="card"><div class="num">{len(blog_kw_set & set(df_kw['keyword'].tolist())) if not df_kw.empty else 0}</div><div class="lbl">{source_label}-YouTube 공통</div></div>
    </div>
    {chart_top_videos}
    {chart_keywords}
    <div class="insight" style="margin-top:16px">
      <strong>{source_label} + YouTube 공통 핵심 키워드 (양쪽에서 동시 주목):</strong><br>
      <div style="margin-top:8px">{overlap_html}</div>
    </div>"""


# ── 콘텐츠 아이디어 HTML 빌드 ─────────────────────────────────────────────────

def _build_content_ideas_html(ideas: list[dict]) -> str:
    """Build Section 7 inner HTML from content idea dicts."""
    if not ideas:
        return """<div style="color:#888;padding:20px;text-align:center">
          ANTHROPIC_API_KEY를 .env에 설정하면 AI가 클러스터 키워드 기반 콘텐츠 아이디어를 자동 생성합니다.
        </div>"""

    parts: list[str] = []
    for idea in ideas:
        kw_badges = "".join(
            f'<span style="background:#e8f4fd;border:1px solid #4A90D9;border-radius:12px;'
            f'padding:2px 8px;margin:2px;display:inline-block;font-size:0.82em">{k}</span>'
            for k in idea.get("keywords", [])
        )
        blog_items = "".join(f"<li>{t}</li>" for t in idea.get("blog_titles", []))
        yt_items   = "".join(f"<li>{t}</li>" for t in idea.get("youtube_titles", []))
        sns_items  = "".join(f"<li>{t}</li>" for t in idea.get("sns_messages", []))

        parts.append(f"""
        <div style="border:1px solid #e9ecef;border-radius:10px;padding:20px;margin-bottom:20px">
          <div style="font-weight:700;color:#0f3460;margin-bottom:8px">
            {cluster_name(",".join(idea.get("keywords", [])))}
            <span style="font-weight:400;color:#888;font-size:0.85em">({idea.get("size",0)}개 포스트)</span>
          </div>
          <div style="margin-bottom:12px">{kw_badges}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
            <div>
              <div style="font-size:0.82em;font-weight:700;color:#4A90D9;margin-bottom:6px">블로그 제목</div>
              <ol style="padding-left:18px;font-size:0.88em;line-height:1.7">{blog_items}</ol>
            </div>
            <div>
              <div style="font-size:0.82em;font-weight:700;color:#e74c3c;margin-bottom:6px">유튜브 제목</div>
              <ol style="padding-left:18px;font-size:0.88em;line-height:1.7">{yt_items}</ol>
            </div>
            <div>
              <div style="font-size:0.82em;font-weight:700;color:#27ae60;margin-bottom:6px">SNS 한줄 메시지</div>
              <ol style="padding-left:18px;font-size:0.88em;line-height:1.7">{sns_items}</ol>
            </div>
          </div>
        </div>""")

    return "\n".join(parts)


# ── HTML 섹션 빌더 ────────────────────────────────────────────────────────────

def _build_lda_section_html(source: str = "blog") -> str:
    """Section 5 — LDA 토픽 HTML 빌드."""
    lda_topics = load_lda_topics(source)
    if not lda_topics:
        return "<div style='color:#888;padding:20px;text-align:center'>LDA 분석 데이터를 불러올 수 없습니다. data/processed/filtered_docs.json 를 확인하세요.</div>"

    lda_rows = ""
    for i, topic in enumerate(lda_topics):
        kw_badges = "".join(
            f'<span style="background:#f0f4ff;border:1px solid #7b9fd4;border-radius:12px;'
            f'padding:2px 8px;margin:2px;display:inline-block;font-size:0.85em">{k}</span>'
            for k in topic
        )
        lda_rows += f"""
        <tr>
          <td style="text-align:center;font-weight:bold">토픽 {i+1}</td>
          <td>{kw_badges}</td>
        </tr>"""

    return f"""
  <table style="margin-top:8px">
    <thead>
      <tr>
        <th width="80">토픽</th>
        <th>상위 10개 키워드</th>
      </tr>
    </thead>
    <tbody>{lda_rows}
    </tbody>
  </table>
  <div class="insight">
    <strong>LDA 해석 가이드:</strong>
    각 토픽은 블로그 본문에서 함께 등장하는 키워드 묶음입니다.
    K-Means 클러스터와 비교해 겹치는 토픽은 <strong>복수 관점에서 검증된 핵심 주제</strong>,
    클러스터에 없는 토픽은 숨겨진 서브 이슈일 수 있습니다.
  </div>"""


def _build_key_findings_html(clusters, noise_keywords: set, generic_keywords: set) -> str:
    lines = []
    for cid, size, kws in clusters:
        kw_list = kws.split(",")
        if any(n in kw_list for n in noise_keywords):
            continue
        distinctive = [k for k in kw_list[:5] if k.lower() not in generic_keywords]
        if len(distinctive) < 2:
            continue
        name = cluster_name(kws)
        lines.append(f'· <strong>{name} ({size}개)</strong> — 상위 키워드: {", ".join(kw_list[:5])}')
    return "<br>\n    ".join(lines)


def _build_cluster_rows_html(clusters, noise_keywords: set, lineage_info: dict) -> str:
    rows = ""
    for cid, size, kws in clusters:
        kw_list = kws.split(",")
        tag = '<span style="color:#999;font-size:0.85em">[노이즈]</span>' if any(n in kw_list for n in noise_keywords) else ""

        info = lineage_info.get(cid, {})
        streak = info.get("streak", 1)
        topic_status = info.get("status", "new")
        if topic_status == "continuing" and streak >= 2:
            lineage_badge = (
                f'<span style="background:#d97706;color:#fff;border-radius:10px;'
                f'padding:2px 8px;font-size:0.8em;font-weight:700;margin-left:6px;">'
                f'🔥 {streak}주 연속</span>'
            )
        elif topic_status == "new":
            lineage_badge = (
                '<span style="background:#16a34a;color:#fff;border-radius:10px;'
                'padding:2px 8px;font-size:0.8em;font-weight:700;margin-left:6px;">'
                '🆕 신규</span>'
            )
        else:
            lineage_badge = ""

        kw_badges = "".join(
            f'<span style="background:#e8f4fd;border:1px solid #4A90D9;border-radius:12px;'
            f'padding:2px 8px;margin:2px;display:inline-block;font-size:0.85em">{k}</span>'
            for k in kw_list
        )
        rows += f"""
        <tr>
          <td style="text-align:center;font-weight:bold">{cluster_name(kws)}{lineage_badge} {tag}</td>
          <td style="text-align:center">{size}</td>
          <td>{kw_badges}</td>
        </tr>"""
    return rows


def _build_regression_components(df_reg: "pd.DataFrame") -> tuple[str, str, str, str]:
    """선형회귀 관련 HTML 4개를 반환: (insight, reg_rows, summary_rows, action)."""
    def _classify(row) -> str:
        if row["p_value"] >= 0.05:
            return "추세 불분명"
        if row["slope"] > 0.3:
            return "관심 증가"
        if row["slope"] < -1.0:
            return "급격 감소"
        return "완만 감소"

    def _reg_insight_line(row) -> str:
        slope_str = f"slope={row['slope']:.2f}, R²={row['r_squared']:.2f}"
        sig = "★ " if row["p_value"] < 0.05 else ""
        if row["slope"] > 0.5 and row["p_value"] < 0.05:
            comment = "뚜렷한 상승 추세 — 관심 증가 중"
        elif row["slope"] < -1.0 and row["p_value"] < 0.05:
            comment = "검색량 급감 — 이벤트성 관심 소멸 또는 시장 회피"
        elif row["p_value"] >= 0.05:
            comment = "추세 불분명 — 변동성 구간, 지속 모니터링 필요"
        else:
            comment = "완만한 하락 — 기저 관심층 유지"
        return f'· <strong>{sig}{row["theme"]} ({slope_str})</strong> — {comment}'

    if df_reg.empty:
        fallback = "DataLab 데이터가 없습니다. datalab_raw.csv / datalab_regression.csv를 생성한 후 다시 실행하세요."
        return fallback, "<tr><td colspan='7' style='color:#999;text-align:center'>DataLab 데이터 없음</td></tr>", "", ""

    regression_insight = "<br>\n    ".join(
        _reg_insight_line(row) for _, row in df_reg.sort_values("slope").iterrows()
    )

    reg_rows = ""
    for _, r in df_reg.sort_values("slope", ascending=False).iterrows():
        sig_color = "#27ae60" if r["p_value"] < 0.05 else "#e74c3c"
        sig_text  = "유의" if r["p_value"] < 0.05 else "불확실"
        slope_color = "#e74c3c" if r["slope"] < 0 else "#27ae60"
        reg_rows += f"""
        <tr>
          <td><strong>{r["theme"]}</strong></td>
          <td style="color:{slope_color};font-weight:bold">{r["slope"]:.4f}</td>
          <td>{r["r_squared"]:.4f}</td>
          <td>{r["p_value"]:.4f}</td>
          <td>{r["avg_ratio"]:.1f}</td>
          <td>{r["direction"]}</td>
          <td style="color:{sig_color};font-weight:bold">{sig_text}</td>
        </tr>"""

    classified = df_reg.copy()
    classified["분류"] = classified.apply(_classify, axis=1)

    category_order = ["관심 증가", "추세 불분명", "완만 감소", "급격 감소"]
    category_meta = {
        "관심 증가":  ("↑ 상승 (유의)", "신규 관심 유입 — 콘텐츠 선점 기회"),
        "추세 불분명":("추세 불분명",    "변동성 구간, 방향성 미결정 — 지속 모니터링 필요"),
        "완만 감소":  ("↓ 하락 (유의)",  "기저 관심층은 유지, 신규 유입 감소세"),
        "급격 감소":  ("↓↓ 급락 (유의)", "이벤트성 관심 소멸 또는 시장 불안 회피"),
    }
    summary_rows = ""
    for cat in category_order:
        themes_in_cat = classified[classified["분류"] == cat]["theme"].tolist()
        if not themes_in_cat:
            continue
        trend_label, interpretation = category_meta[cat]
        tag_html = "".join(f'<span class="tag">{t}</span>' for t in themes_in_cat)
        summary_rows += f"""
        <tr>
          <td>{cat}</td>
          <td>{tag_html}</td>
          <td>{trend_label}</td>
          <td>{interpretation}</td>
        </tr>"""

    action_items = []
    rising    = classified[classified["분류"] == "관심 증가"]["theme"].tolist()
    uncertain = classified[classified["분류"] == "추세 불분명"]["theme"].tolist()
    declining = classified[classified["분류"] == "급격 감소"]["theme"].tolist()
    if rising:
        action_items.append(f'<strong>{", ".join(rising[:2])}</strong> — 상승 추세 확인. 관련 콘텐츠 즉시 제작 권장')
    if uncertain:
        action_items.append(f'<strong>{", ".join(uncertain[:3])}</strong> — 추세 불분명. 다음 수집 시 방향성 재확인 필요')
    if declining:
        action_items.append(f'<strong>{", ".join(declining[:2])}</strong> — 급락 구간. 계절성 또는 이벤트 종료 여부 확인')
    action_items.append('<strong>매주 run_all.py 자동 실행</strong> → period 누적 시 기간별 비교 차트 자동 생성됨')
    action_html = "<br>\n    ".join(f"{i+1}. {item}" for i, item in enumerate(action_items))

    return regression_insight, reg_rows, summary_rows, action_html


def _assemble_full_html(
    source_label: str, run_date_str: str, report_date: str,
    blog_start: str, blog_end: str, datalab_start: str, datalab_end: str,
    datalab_weeks: int, post_count: int, best_k: int, silhouette: float,
    df_raw: "pd.DataFrame", df_yt_raw: "pd.DataFrame",
    chart_keyword_bar: str, chart_cluster_pie: str, chart_regression: str,
    lda_section_html: str, youtube_section_html: str,
    period_trend_html: str, content_ideas_html: str,
    key_findings_html: str, cluster_rows_html: str,
    reg_rows_html: str, regression_insight_html: str,
    summary_rows_html: str, action_html: str,
    keywords: list,
) -> str:
    """전체 HTML 보고서를 조립하여 반환한다."""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>ETF 키워드 트렌드 분석 보고서 [{source_label}]{f" | {run_date_str}" if run_date_str else ""}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
         background: #f0f2f5; color: #1a1a2e; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 40px 24px; }}

  /* 표지 */
  .cover {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
            color: white; border-radius: 16px; padding: 48px 40px; margin-bottom: 32px; }}
  .cover h1 {{ font-size: 2em; font-weight: 700; margin-bottom: 8px; }}
  .cover .sub {{ font-size: 1.05em; opacity: 0.75; margin-bottom: 24px; }}
  .cover .meta {{ display: flex; gap: 32px; flex-wrap: wrap; }}
  .cover .meta-item {{ background: rgba(255,255,255,0.1); border-radius: 10px;
                       padding: 12px 20px; }}
  .cover .meta-item .label {{ font-size: 0.75em; opacity: 0.7; margin-bottom: 4px; }}
  .cover .meta-item .value {{ font-size: 1em; font-weight: 600; }}

  /* 섹션 */
  .section {{ background: white; border-radius: 12px; padding: 32px;
              margin-bottom: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
  .section h2 {{ font-size: 1.25em; font-weight: 700; margin-bottom: 4px;
                 color: #0f3460; border-left: 4px solid #4A90D9;
                 padding-left: 12px; }}
  .section .desc {{ font-size: 0.88em; color: #666; margin-bottom: 20px;
                    padding-left: 16px; }}

  /* 요약 카드 */
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }}
  .card {{ flex: 1; min-width: 150px; background: #f8f9fa; border-radius: 10px;
           padding: 16px 20px; text-align: center; border: 1px solid #e9ecef; }}
  .card .num {{ font-size: 2em; font-weight: 800; color: #0f3460; }}
  .card .lbl {{ font-size: 0.8em; color: #888; margin-top: 4px; }}

  /* 테이블 */
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  th {{ background: #0f3460; color: white; padding: 10px 14px; text-align: left; }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #f0f2f5; vertical-align: middle; }}
  tr:hover td {{ background: #f8f9fb; }}

  /* 인사이트 박스 */
  .insight {{ background: #fffbea; border-left: 4px solid #f39c12;
              border-radius: 0 8px 8px 0; padding: 14px 18px; margin-top: 16px;
              font-size: 0.92em; line-height: 1.7; }}
  .insight strong {{ color: #e67e22; }}

  .tag {{ background: #e8f4fd; border: 1px solid #4A90D9; border-radius: 12px;
          padding: 2px 10px; font-size: 0.82em; display: inline-block; margin: 2px; }}

  footer {{ text-align: center; color: #aaa; font-size: 0.8em; margin-top: 32px; padding: 16px; }}
</style>
</head>
<body>
<div class="wrap">

<!-- 표지 -->
<div class="cover">
  <div class="sub">네이버 {source_label} ETF 키워드 자동 발굴 · 트렌드 분석</div>
  <h1>ETF 키워드 트렌드 분석 보고서 [{source_label}]{f" | {run_date_str}" if run_date_str else ""}</h1>
  <div class="meta">
    <div class="meta-item">
      <div class="label">보고서 작성일</div>
      <div class="value">{report_date}</div>
    </div>
    <div class="meta-item">
      <div class="label">{source_label} 수집 기간</div>
      <div class="value">{blog_start} ~ {blog_end} (1주)</div>
    </div>
    <div class="meta-item">
      <div class="label">DataLab 트렌드 기간</div>
      <div class="value">{datalab_start} ~ {datalab_end} ({datalab_weeks}주)</div>
    </div>
    <div class="meta-item">
      <div class="label">YouTube 수집</div>
      <div class="value">{len(df_yt_raw):,}개 영상 (한국어, 최근 7일)</div>
    </div>
    <div class="meta-item">
      <div class="label">분석 방법</div>
      <div class="value">TF-IDF · K-Means · LDA · DataLab 회귀 · YouTube</div>
    </div>
  </div>
</div>

<!-- 1. 분석 개요 -->
<div class="section">
  <h2>1. 분석 개요 및 방법론</h2>
  <div class="desc">데이터 소스 · 수집 조건 · ML 파이프라인 · 트렌드 검증 구조 설명</div>

  <table>
    <tr><th width="220" colspan="2" style="background:#16213e;font-size:0.85em;letter-spacing:0.05em">① 데이터 수집</th></tr>
    <tr><td>투입 시드 키워드</td>
        <td><span class="tag">ETF</span> 단일 키워드 — ML이 연관 키워드 자동 발굴</td></tr>
    <tr><td>{source_label} 수집</td><td>네이버 {source_label} 검색 API · sort=date 최신순 · 중복 sha1 제거<br>
        <span style="color:#666;font-size:0.9em">수집 기간 {blog_start} ~ {blog_end} | 수집 포스트 {post_count:,}개</span></td></tr>
    <tr><td>YouTube 수집</td><td>YouTube Data API v3 (search + statistics) · 한국어 영상만 수집 (제목 한글 필터)<br>
        <span style="color:#666;font-size:0.9em">최근 7일 | 수집 영상 {len(df_yt_raw):,}개 | 클러스터 상위 키워드 기반 쿼리 자동 구성</span></td></tr>
    <tr><td>DataLab 검색량</td><td>네이버 DataLab 검색어 트렌드 API · 주간 단위<br>
        <span style="color:#666;font-size:0.9em">조회 기간 {datalab_start} ~ {datalab_end} ({datalab_weeks}주) | {df_raw["theme"].nunique() if not df_raw.empty else 0}개 테마</span></td></tr>

    <tr><th colspan="2" style="background:#16213e;font-size:0.85em;letter-spacing:0.05em">② 전처리 · 품질 필터링</th></tr>
    <tr><td>텍스트 정제</td><td>BeautifulSoup HTML 제거 → 공백 정규화 → kiwipiepy 형태소 분석 (명사 NN* · 외국어 SL, 2자 이상)</td></tr>
    <tr><td>규칙 필터</td><td>본문 길이 ≥ 150자 + ETF 관련 용어 1개 이상 포함</td></tr>
    <tr><td>Proxy Score 필터</td><td>길이 점수(30%) + ETF 밀도(55%) + 비광고(15%) 합산 → 0.55 이상 통과<br>
        <span style="color:#666;font-size:0.9em">광고 감지 어휘: 협찬·체험단·파트너스·원고료 등 15개</span></td></tr>

    <tr><th colspan="2" style="background:#16213e;font-size:0.85em;letter-spacing:0.05em">③ ML 키워드 분석</th></tr>
    <tr><td>벡터화</td><td>TF-IDF (min_df=3, max_df=0.60, max_features=300, token_pattern=\\w+)</td></tr>
    <tr><td>임베딩 (선택)</td><td>SentenceTransformer · paraphrase-multilingual-MiniLM-L12-v2<br>
        <span style="color:#666;font-size:0.9em">미설치 또는 네트워크 차단 시 TF-IDF + SVD(LSA) 자동 fallback</span></td></tr>
    <tr><td>클러스터링</td><td>K-Means · k=3~12 전수 탐색 · 실루엣 계수 최대화 → best k={best_k} (silhouette={silhouette:.3f})<br>
        <span style="color:#666;font-size:0.9em">클러스터 대표 키워드: 클러스터 내 TF-IDF 평균 상위 10개</span></td></tr>
    <tr><td>토픽 모델링</td><td>LDA (n_components=10, random_state=42) · 토픽별 상위 10개 키워드 추출</td></tr>
    <tr><td>버스트 키워드 감지</td><td>novelty_score = (현재 빈도 − 이전 기간 빈도) ÷ (이전 빈도 + 1)<br>
        <span style="color:#666;font-size:0.9em">신규 등장 또는 급증 키워드 자동 감지 · results/burst_keywords.csv 저장</span></td></tr>

    <tr><th colspan="2" style="background:#16213e;font-size:0.85em;letter-spacing:0.05em">④ 트렌드 검증</th></tr>
    <tr><td>DataLab 선형회귀</td><td>OLS (scipy.stats.linregress) · slope·R²·p값 계산<br>
        <span style="color:#666;font-size:0.9em">p &lt; 0.05 = 통계적 유의 (★) · slope &gt; 0 = 상승 추세</span></td></tr>
    <tr><td>3중 교차 검증</td><td>{source_label} 빈도 키워드 ↔ DataLab 검색량 ↔ YouTube 조회 키워드 공통 집합 → 핵심 트렌드 확정</td></tr>

  </table>

  <div class="insight">
    <strong>분석 구조:</strong>
    <span class="tag">ETF</span> 단일 키워드 투입 →
    <strong>ML 자동 클러스터 발굴</strong> ({source_label} 본문 TF-IDF + K-Means) →
    <strong>DataLab 검색량 검증</strong> (선형회귀 추세) →
    <strong>YouTube 트렌드 교차 확인</strong> (조회수 + 키워드 겹침) →
    <strong>기간별 추이 분석</strong> (반복·신규·소멸 자동 분류)<br><br>
    사람이 직접 키워드를 정의하는 기존 방식과 달리, ML이 {source_label} 본문에서 의미 있는 클러스터를 자동 발굴하고
    DataLab·YouTube 2개 소스로 교차 검증하므로 놓치기 쉬운 신흥 트렌드를 조기에 포착할 수 있습니다.
  </div>
</div>

<!-- 2. 수집 및 전처리 결과 -->
<div class="section">
  <h2>2. 수집 · 전처리 결과</h2>
  <div class="desc">원시 수집 → 본문 추출 → 정제 → 필터링 단계별 수치</div>

  <div class="cards">
    <div class="card"><div class="num">{post_count:,}</div><div class="lbl">수집 포스트 수</div></div>
    <div class="card"><div class="num">{len(keywords):,}</div><div class="lbl">추출 키워드 수</div></div>
    <div class="card"><div class="num">{best_k}</div><div class="lbl">최적 클러스터 수</div></div>
    <div class="card"><div class="num">{silhouette:.3f}</div><div class="lbl">실루엣 계수</div></div>
  </div>

  <div class="insight">
    <strong>필터링 기준:</strong> 본문 길이 150자 이상 + 프록시 스코어 0.55 이상.
    수집된 {post_count:,}개 전량 필터 통과 — ETF 단일 키워드 특성상 관련성 높은 포스트 위주로 수집됨.
    <br><strong>실루엣 계수 {silhouette:.3f}:</strong> 0.1 이상이면 의미 있는 분리로 판단 (금융 텍스트의 특성상 클러스터 경계가 모호할 수 있음).
  </div>
</div>

<!-- 3. Top 20 키워드 -->
<div class="section">
  <h2>3. ML 자동 발굴 키워드 Top 20</h2>
  <div class="desc">TF-IDF 벡터화 후 빈도수 기준 상위 20개 — ETF 단일 키워드에서 파생된 주요 연관어</div>
  {chart_keyword_bar}
</div>

<!-- 4. 클러스터 분석 -->
<div class="section">
  <h2>4. K-Means 클러스터 분석</h2>
  <div class="desc">best k={best_k} (실루엣 최대화), 포스트 {post_count:,}개를 {best_k}개 의미 그룹으로 분류</div>

  {chart_cluster_pie}

  <table style="margin-top:20px">
    <thead>
      <tr>
        <th width="80">클러스터</th>
        <th width="80">포스트 수</th>
        <th>대표 키워드 (상위 10개)</th>
      </tr>
    </thead>
    <tbody>
      {cluster_rows_html}
    </tbody>
  </table>

  <div class="insight">
    <strong>주요 발견:</strong><br>
    {key_findings_html}
  </div>
</div>

<!-- 5. LDA 토픽 모델링 -->
<div class="section">
  <h2>5. LDA 토픽 모델링</h2>
  <div class="desc">LDA (n_components=10, random_state=42) · 블로그 본문 TF-IDF 기반 · 토픽별 상위 10개 키워드 추출</div>
  {lda_section_html}
</div>

<!-- 6. 선형회귀 결과 -->
<div class="section">
  <h2>6. 선형회귀 분석 결과</h2>
  <div class="desc">
    각 테마의 주간 검색량에 OLS 선형회귀 적용. slope(기울기) &gt; 0 = 검색량 증가 추세.
    p &lt; 0.05이면 통계적으로 유의미한 추세.
  </div>

  {chart_regression}

  <table style="margin-top:20px">
    <thead>
      <tr>
        <th>테마</th>
        <th>기울기 (slope)</th>
        <th>R²</th>
        <th>p값</th>
        <th>평균 검색량</th>
        <th>방향</th>
        <th>유의성 (p&lt;0.05)</th>
      </tr>
    </thead>
    <tbody>
      {reg_rows_html}
    </tbody>
  </table>

  <div class="insight">
    <strong>핵심 인사이트:</strong><br>
    {regression_insight_html}
  </div>
</div>

<!-- 7. 종합 요약 -->
<div class="section">
  <h2>7. 종합 요약 및 시사점</h2>
  <div class="desc">분석 결과 기반 투자자 관심 흐름 요약</div>

  <table>
    <thead>
      <tr><th>구분</th><th>테마</th><th>검색 트렌드</th><th>해석</th></tr>
    </thead>
    <tbody>
      {summary_rows_html}
    </tbody>
  </table>

  <div class="insight" style="margin-top:16px">
    <strong>다음 액션 아이템:</strong><br>
    {action_html}
  </div>
</div>

<!-- 8. YouTube 트렌드 -->
<div class="section">
  <h2>8. YouTube 트렌드</h2>
  <div class="desc">클러스터 키워드 기반 YouTube 영상 수집 · 조회수 상위 영상 · {source_label}와 겹치는 핵심 키워드 교차 검증</div>
  {youtube_section_html}
</div>

<!-- 9. 기간별 키워드 추이 -->
<div class="section">
  <h2>9. 기간별 키워드 추이</h2>
  <div class="desc">매주 누적되는 키워드 데이터 기반 — 반복 등장(핵심 트렌드) · 신규 부상 · 소멸 키워드 자동 분류</div>
  {period_trend_html}
</div>

<!-- 10. AI 콘텐츠 아이디어 -->
<div class="section">
  <h2>10. AI 콘텐츠 아이디어</h2>
  <div class="desc">ML 발굴 클러스터 키워드 → Claude AI가 자동 생성한 블로그/유튜브/SNS 제목 아이디어</div>
  {content_ideas_html}
</div>

<footer>
  ETF 키워드 자동 발굴 시스템 | 네이버 {source_label} + DataLab + YouTube | 생성: {report_date}
</footer>

</div>
</body>
</html>"""


# ── HTML 보고서 조립 ───────────────────────────────────────────────────────────

def _get_datalab_date_range(df_raw: "pd.DataFrame") -> tuple[str, str]:
    """datalab_raw.csv의 실제 날짜 범위를 반환."""
    try:
        min_d = df_raw["date"].min().strftime("%Y-%m-%d")
        max_d = df_raw["date"].max().strftime("%Y-%m-%d")
        return min_d, max_d
    except Exception:
        return "N/A", "N/A"


def _get_blog_collection_range(df_raw: "pd.DataFrame") -> tuple[str, str]:
    """datalab의 마지막 날짜 기준 직전 1주를 블로그 수집 기간으로 반환."""
    try:
        end = df_raw["date"].max()
        start = end - pd.Timedelta(days=6)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    except Exception:
        today = datetime.now()
        week_ago = today - timedelta(days=6)
        return week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def build_report(source: str = "blog") -> None:
    global DB_PATH, REPORT_PATH, RESULTS_DIR
    cfg = _SOURCE_CONFIG[source]
    DB_PATH = cfg["db"]
    RESULTS_DIR = cfg["results_dir"]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    source_label = cfg["label"]

    clusters, keywords, cluster_run, collection = load_db_data()
    df_raw, df_reg = load_datalab_data()

    best_k       = cluster_run[0] if cluster_run else 0
    silhouette   = cluster_run[1] if cluster_run else 0.0
    post_count   = collection[0]  if collection  else 0
    run_date_str = collection[1]  if (collection and collection[1]) else ""

    date_suffix = f"_{run_date_str.replace('-', '')}" if run_date_str else ""
    REPORT_PATH = RESULTS_DIR / f"{cfg['report'].stem}{date_suffix}.html"

    chart_keyword_bar = make_keyword_bar(keywords)
    chart_cluster_pie = make_cluster_pie(clusters)
    chart_regression  = make_regression_bar(df_reg) if not df_reg.empty else ""

    datalab_start, datalab_end = _get_datalab_date_range(df_raw)
    blog_start, blog_end = _get_blog_collection_range(df_raw)
    datalab_weeks = max(1, (df_raw["date"].max() - df_raw["date"].min()).days // 7 + 1) if not df_raw.empty else 0

    lda_section_html = _build_lda_section_html(source)

    df_yt_raw, df_yt_kw = load_youtube_data()
    youtube_section_html = _build_youtube_section_html(df_yt_raw, df_yt_kw, keywords, source_label)

    df_period = load_period_trend_data()
    period_trend_html = _build_period_trend_section_html(df_period)

    content_ideas: list[dict] = []
    try:
        from app.content_strategy.idea_generator import generate_content_ideas
        latest_clusters = load_latest_clusters()
        if latest_clusters:
            content_ideas = generate_content_ideas(latest_clusters)
    except Exception as exc:
        logger.warning("Content idea generation skipped: %s", exc)
    content_ideas_html = _build_content_ideas_html(content_ideas)

    generic_keywords = {
        "미국", "시장", "상품", "투자자", "종목", "기업", "수익", "자산", "주식",
        "운용", "상장", "비용", "구조", "전략", "포트폴리오", "비중", "분산",
        "정보", "내용", "이해", "추천", "비교", "확인", "기준", "수준",
        "사람", "시간", "시작", "가격", "경우", "생각", "매수", "계좌",
    }
    key_findings_html  = _build_key_findings_html(clusters, NOISE_KEYWORDS, generic_keywords)
    lineage_info       = load_lineage_info(_get_latest_done_period(sqlite3.connect(DB_PATH)))
    cluster_rows_html  = _build_cluster_rows_html(clusters, NOISE_KEYWORDS, lineage_info)
    regression_insight_html, reg_rows_html, summary_rows_html, action_html = _build_regression_components(df_reg)

    report_date = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    html = _assemble_full_html(
        source_label=source_label, run_date_str=run_date_str, report_date=report_date,
        blog_start=blog_start, blog_end=blog_end,
        datalab_start=datalab_start, datalab_end=datalab_end, datalab_weeks=datalab_weeks,
        post_count=post_count, best_k=best_k, silhouette=silhouette,
        df_raw=df_raw, df_yt_raw=df_yt_raw,
        chart_keyword_bar=chart_keyword_bar, chart_cluster_pie=chart_cluster_pie,
        chart_regression=chart_regression, lda_section_html=lda_section_html,
        youtube_section_html=youtube_section_html, period_trend_html=period_trend_html,
        content_ideas_html=content_ideas_html, key_findings_html=key_findings_html,
        cluster_rows_html=cluster_rows_html, reg_rows_html=reg_rows_html,
        regression_insight_html=regression_insight_html,
        summary_rows_html=summary_rows_html, action_html=action_html,
        keywords=keywords,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"보고서 저장: {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", choices=["blog", "news"], default="blog",
        help="보고서 소스 (기본값: blog)",
    )
    args = parser.parse_args()
    cfg = _SOURCE_CONFIG[args.source]
    print(f"[{args.source}] DB={cfg['db']} → {cfg['report'].name}")
    build_report(source=args.source)
