"""
run_generate_content_brief.py — ETF 콘텐츠 전략 브리프 통합 보고서 생성기

블로그 클러스터(독자 관심) + 뉴스 클러스터(시장 이슈) 교차 분석 →
Search Intent / JTBD / AIDA / PAS 프레임워크 적용 →
results/etf_content_brief.html 생성
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

from app.config.constants import GENERIC_KEYWORDS, NOISE_KEYWORDS
from app.content_strategy.content_brief import generate_content_briefs, match_clusters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from app.utils import week_folder as _week_folder

_PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = _PROJECT_ROOT / "results" / _week_folder()
REPORT_PATH = RESULTS_DIR / "etf_content_brief.html"

BLOG_DB = str(_PROJECT_ROOT / "etf_trend.db")
NEWS_DB = str(_PROJECT_ROOT / "etf_trend_news.db")

# ── 데이터 로드 ────────────────────────────────────────────────────────────────

def load_clusters_from_db(db_path: str) -> list[dict]:
    """지정 DB에서 최신 period 클러스터 로드."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT period FROM collections WHERE status='done' ORDER BY period DESC LIMIT 1"
        ).fetchone()
        if not row:
            con.close()
            logger.warning("DB에 완료된 period 없음: %s", db_path)
            return []
        period = row[0]
        clusters = con.execute(
            "SELECT cluster_id, size, keywords FROM clusters WHERE period=? ORDER BY size DESC",
            (period,),
        ).fetchall()
        con.close()
        return [
            {"cluster_id": cid, "size": size, "keywords": kws.split(",")}
            for cid, size, kws in clusters
        ]
    except Exception as exc:
        logger.warning("클러스터 로드 실패 (%s): %s", db_path, exc)
        return []


def _compute_all_streaks(db_path: str) -> dict[str, int]:
    """DB의 최신 period 키워드별 연속 등장 주수 반환 (최신 period 기준 연속 역산)."""
    try:
        con = sqlite3.connect(db_path)
        periods = [
            row[0]
            for row in con.execute(
                "SELECT period FROM collections WHERE status='done' ORDER BY period DESC"
            ).fetchall()
        ]
        period_kws: list[set[str]] = []
        for period in periods:
            rows = con.execute(
                "SELECT keywords FROM clusters WHERE period=?", (period,)
            ).fetchall()
            kws: set[str] = set()
            for (kws_str,) in rows:
                for k in kws_str.split(","):
                    kws.add(k.strip())
            period_kws.append(kws)
        con.close()

        streaks: dict[str, int] = {}
        if period_kws:
            for kw in period_kws[0]:
                streak = 0
                for kws in period_kws:
                    if kw in kws:
                        streak += 1
                    else:
                        break
                streaks[kw] = streak
        return streaks
    except Exception as exc:
        logger.warning("streak 계산 실패 (%s): %s", db_path, exc)
        return {}


def _select_llm_clusters(
    blog_clusters: list[dict],
    news_clusters: list[dict],
    blog_streaks: dict[str, int],
    news_streaks: dict[str, int],
    top_common: int = 2,
    top_blog: int = 1,
    top_news: int = 1,
) -> list[dict]:
    """cluster_selector.py와 동일 기준으로 LLM 파이프라인 대상 클러스터 선정."""
    themes = match_clusters(blog_clusters, news_clusters)

    def _is_noise_theme(t: dict) -> bool:
        if "[노이즈]" in t.get("theme", ""):
            return True
        combined = t.get("blog_keywords", []) + t.get("news_keywords", [])
        return any(n in combined for n in NOISE_KEYWORDS)

    themes = [t for t in themes if not _is_noise_theme(t)]

    common = sorted(
        [t for t in themes if t["source"] == "공통"],
        key=lambda t: t["blog_size"] + t["news_size"],
        reverse=True,
    )
    blog_only = sorted(
        [t for t in themes if t["source"] == "블로그"],
        key=lambda t: t["blog_size"],
        reverse=True,
    )
    news_only = sorted(
        [t for t in themes if t["source"] == "뉴스"],
        key=lambda t: t["news_size"],
        reverse=True,
    )

    selected = common[:top_common] + blog_only[:top_blog] + news_only[:top_news]

    for theme in selected:
        kws = list(dict.fromkeys(
            theme.get("blog_keywords", []) + theme.get("news_keywords", [])
        ))
        kw_streaks = {
            k: max(blog_streaks.get(k, 0), news_streaks.get(k, 0))
            for k in kws
        }
        theme["keyword_streaks"] = kw_streaks
        theme["streak"] = max(kw_streaks.values(), default=1)
    return selected


# ── HTML 렌더링 ────────────────────────────────────────────────────────────────

_SOURCE_COLOR = {
    "공통":  {"bg": "#e8f5e9", "border": "#27ae60", "text": "#1a6b35", "emoji": "🟩"},
    "블로그": {"bg": "#e8f4fd", "border": "#4A90D9", "text": "#1a4f8a", "emoji": "🟦"},
    "뉴스":  {"bg": "#fdecea", "border": "#e74c3c", "text": "#8a1a1a", "emoji": "🟥"},
}

_INTENT_COLOR = {
    "정보성": {"bg": "#e3f2fd", "border": "#1565c0", "text": "#1565c0"},
    "비교성": {"bg": "#f3e5f5", "border": "#7b1fa2", "text": "#7b1fa2"},
    "거래성": {"bg": "#fff3e0", "border": "#e65100", "text": "#e65100"},
}


def _streak_badge(streak: int) -> str:
    if streak == 0:
        label, color = "신규", "#7f8c8d"
    elif streak == 1:
        label, color = "1주", "#7f8c8d"
    elif streak == 2:
        label, color = "2주 연속", "#e67e22"
    else:
        label, color = f"{streak}주 연속", "#27ae60"
    return (
        f'<span style="background:{color}20;color:{color};border:1px solid {color}40;'
        f'border-radius:6px;padding:1px 7px;font-size:0.75em;font-weight:700">🔁 {label}</span>'
    )


def _llm_selection_section_html(selected: list[dict]) -> str:
    if not selected:
        return ""

    sc_map = _SOURCE_COLOR

    cards = []
    for rank, theme in enumerate(selected, start=1):
        source = theme.get("source", "공통")
        sc = sc_map.get(source, sc_map["공통"])
        streak = theme.get("streak", 1)
        kw_streaks: dict[str, int] = theme.get("keyword_streaks", {})

        kw_html = ""
        for kw in list(dict.fromkeys(
            theme.get("blog_keywords", []) + theme.get("news_keywords", [])
        ))[:10]:
            s = kw_streaks.get(kw, 1)
            if s >= 3:
                s_color, s_bg = "#27ae60", "#e8f5e9"
            elif s == 2:
                s_color, s_bg = "#e67e22", "#fff3e0"
            else:
                s_color, s_bg = "#95a5a6", "#f5f5f5"
            kw_html += (
                f'<span style="background:{s_bg};border:1px solid {s_color}40;'
                f'border-radius:10px;padding:2px 8px;margin:2px;'
                f'display:inline-block;font-size:0.8em">'
                f'{kw}'
                f'<span style="color:{s_color};font-weight:700;margin-left:3px;'
                f'font-size:0.72em">{s}W</span>'
                f'</span>'
            )

        cards.append(f"""
<div style="border:1px solid {sc["border"]};border-radius:10px;padding:16px 18px;
            background:white;flex:1;min-width:210px">
  <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:#0f3460;color:white;border-radius:50%;
                 width:22px;height:22px;display:inline-flex;align-items:center;
                 justify-content:center;font-size:0.82em;font-weight:700;
                 flex-shrink:0">{rank}</span>
    <span style="background:{sc["bg"]};border:1px solid {sc["border"]};
                 color:{sc["text"]};border-radius:6px;padding:1px 8px;
                 font-size:0.78em;font-weight:700">{sc["emoji"]} {source}</span>
    {_streak_badge(streak)}
  </div>
  <div style="font-weight:700;color:#0f3460;font-size:0.92em;margin-bottom:8px;
              line-height:1.4">{theme.get("theme", "")}</div>
  <div style="margin-bottom:8px">{kw_html}</div>
  <div style="color:#aaa;font-size:0.74em">
    블로그 {theme.get("blog_size", 0)}개 · 뉴스 {theme.get("news_size", 0)}개
  </div>
</div>""")

    return f"""
<div style="background:linear-gradient(135deg,#1a1a2e 0%,#0f3460 100%);
            border-radius:12px;padding:24px;margin-bottom:28px;color:white">
  <div style="font-size:0.78em;opacity:0.65;margin-bottom:3px;letter-spacing:0.05em">
    LLM 파이프라인 자동 선정
  </div>
  <div style="font-size:1.1em;font-weight:700;margin-bottom:3px">
    🤖 콘텐츠 아이디어 생성 대상 {len(selected)}개 클러스터
  </div>
  <div style="font-size:0.8em;opacity:0.6;margin-bottom:18px">
    공통 최대 2개 + 블로그 단독 1개 + 뉴스 단독 1개 &nbsp;|&nbsp;
    W = 해당 키워드의 연속 등장 주수 (1W = 이번 주 첫 등장)
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap">
    {"".join(cards)}
  </div>
</div>"""


def _kw_badge(kw: str, color: str, border: str) -> str:
    return (
        f'<span style="background:{color};border:1px solid {border};border-radius:12px;'
        f'padding:2px 8px;margin:2px;display:inline-block;font-size:0.82em">{kw}</span>'
    )


def _intent_badge(intent: str) -> str:
    c = _INTENT_COLOR.get(intent, {"bg": "#f5f5f5", "border": "#999", "text": "#555"})
    return (
        f'<span style="background:{c["bg"]};border:1px solid {c["border"]};'
        f'color:{c["text"]};border-radius:6px;padding:2px 10px;font-size:0.8em;'
        f'font-weight:700">{intent}</span>'
    )


def _aida_pas_html(brief: dict) -> str:
    aida = brief.get("aida", {})
    pas  = brief.get("pas", {})

    def row(label: str, val: str, color: str) -> str:
        return (
            f'<tr><td style="width:90px;font-weight:700;color:{color};'
            f'padding:7px 10px;vertical-align:top">{label}</td>'
            f'<td style="padding:7px 10px;line-height:1.6">{val or "—"}</td></tr>'
        )

    aida_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:0.88em">'
        + row("Attention", aida.get("attention", ""), "#c0392b")
        + row("Interest",  aida.get("interest",  ""), "#2980b9")
        + row("Desire",    aida.get("desire",    ""), "#8e44ad")
        + row("Action",    aida.get("action",    ""), "#27ae60")
        + '</table>'
    )
    pas_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:0.88em">'
        + row("Problem",  pas.get("problem",  ""), "#c0392b")
        + row("Agitate",  pas.get("agitate",  ""), "#e67e22")
        + row("Solution", pas.get("solution", ""), "#27ae60")
        + '</table>'
    )

    return f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
      <div>
        <div style="font-size:0.8em;font-weight:700;color:#555;margin-bottom:6px;
                    letter-spacing:0.05em">AIDA</div>
        <div style="border:1px solid #e9ecef;border-radius:8px;overflow:hidden">
          {aida_html}
        </div>
      </div>
      <div>
        <div style="font-size:0.8em;font-weight:700;color:#555;margin-bottom:6px;
                    letter-spacing:0.05em">PAS</div>
        <div style="border:1px solid #e9ecef;border-radius:8px;overflow:hidden">
          {pas_html}
        </div>
      </div>
    </div>"""


def _titles_html(brief: dict) -> str:
    def col(label: str, color: str, items: list[str]) -> str:
        lis = "".join(f"<li style='margin-bottom:4px'>{t}</li>" for t in items) or "<li style='color:#aaa'>—</li>"
        return (
            f'<div><div style="font-size:0.8em;font-weight:700;color:{color};'
            f'margin-bottom:6px">{label}</div>'
            f'<ol style="padding-left:18px;font-size:0.86em;line-height:1.7;margin:0">{lis}</ol></div>'
        )

    return f"""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:16px">
      {col("📝 블로그 제목", "#4A90D9", brief.get("blog_titles", []))}
      {col("▶️ 유튜브 제목", "#e74c3c", brief.get("youtube_titles", []))}
      {col("💬 SNS 메시지", "#27ae60", brief.get("sns_messages", []))}
    </div>"""


def _theme_card_html(brief: dict) -> str:
    source = brief.get("source", "공통")
    sc = _SOURCE_COLOR.get(source, _SOURCE_COLOR["공통"])
    intent = brief.get("search_intent", "")
    jtbd   = brief.get("jtbd", "")

    # 키워드 배지
    blog_badges = "".join(_kw_badge(k, "#e8f4fd", "#4A90D9") for k in brief.get("blog_keywords", [])[:8])
    news_badges = "".join(_kw_badge(k, "#fdecea", "#e74c3c") for k in brief.get("news_keywords", [])[:8])

    kw_section = ""
    if blog_badges:
        kw_section += f'<div style="margin-bottom:4px"><span style="font-size:0.75em;color:#4A90D9;margin-right:6px">블로그</span>{blog_badges}</div>'
    if news_badges:
        kw_section += f'<div><span style="font-size:0.75em;color:#e74c3c;margin-right:6px">뉴스</span>{news_badges}</div>'

    blog_size = brief.get("blog_size", 0)
    news_size = brief.get("news_size", 0)
    size_txt = f"블로그 {blog_size}개" if blog_size else ""
    if news_size:
        size_txt += (" / " if size_txt else "") + f"뉴스 {news_size}개"

    source_badge = (
        f'<span style="background:{sc["bg"]};border:1px solid {sc["border"]};'
        f'color:{sc["text"]};border-radius:6px;padding:2px 10px;font-size:0.8em;'
        f'font-weight:700;margin-right:8px">{sc["emoji"]} {source}</span>'
    )

    intent_html = _intent_badge(intent) if intent else ""
    jtbd_html = (
        f'<div style="background:#fffbea;border-left:4px solid #f39c12;'
        f'border-radius:0 8px 8px 0;padding:10px 14px;margin:12px 0;'
        f'font-size:0.9em;line-height:1.6">'
        f'<strong style="color:#e67e22">JTBD</strong>&nbsp;&nbsp;{jtbd}</div>'
    ) if jtbd else ""

    has_brief = bool(intent or jtbd or any(brief.get("aida", {}).values()))
    aida_pas = _aida_pas_html(brief) if has_brief else ""
    titles   = _titles_html(brief) if has_brief else ""

    no_api_msg = ""

    return f"""
<div style="border:1px solid {sc["border"]};border-radius:12px;padding:24px;
            margin-bottom:24px;background:#fff;
            box-shadow:0 2px 8px rgba(0,0,0,0.05)">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
    {source_badge}
    {intent_html}
    <span style="font-weight:700;color:#0f3460;font-size:1.05em">{brief.get("theme","")}</span>
    <span style="color:#aaa;font-size:0.82em;margin-left:auto">{size_txt}</span>
  </div>
  <div style="margin-bottom:10px">{kw_section}</div>
  {jtbd_html}
  {aida_pas}
  {titles}
  {no_api_msg}
</div>"""


def _build_html(
    briefs: list[dict],
    blog_count: int,
    news_count: int,
    llm_section: str = "",
) -> str:
    common_count = sum(1 for b in briefs if b.get("source") == "공통")
    report_date  = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")

    # 소스별 정렬: 공통 → 블로그 → 뉴스
    order = {"공통": 0, "블로그": 1, "뉴스": 2}
    sorted_briefs = sorted(briefs, key=lambda b: order.get(b.get("source", "뉴스"), 3))

    cards_html = "\n".join(_theme_card_html(b) for b in sorted_briefs)
    if not cards_html:
        cards_html = '<div style="color:#aaa;text-align:center;padding:40px">분석할 클러스터 데이터가 없습니다.</div>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>ETF 콘텐츠 전략 브리프</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
         background:#f0f2f5; color:#1a1a2e; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:40px 24px; }}

  .cover {{ background:linear-gradient(135deg,#1a1a2e 0%,#16213e 60%,#0f3460 100%);
            color:white; border-radius:16px; padding:48px 40px; margin-bottom:32px; }}
  .cover h1 {{ font-size:1.9em; font-weight:700; margin-bottom:8px; }}
  .cover .sub {{ font-size:1em; opacity:0.75; margin-bottom:24px; }}
  .cover .meta {{ display:flex; gap:24px; flex-wrap:wrap; }}
  .cover .meta-item {{ background:rgba(255,255,255,0.1); border-radius:10px; padding:12px 20px; }}
  .cover .meta-item .label {{ font-size:0.75em; opacity:0.7; margin-bottom:4px; }}
  .cover .meta-item .value {{ font-size:1.1em; font-weight:600; }}

  .cards {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:32px; }}
  .card {{ flex:1; min-width:150px; background:white; border-radius:10px;
           padding:16px 20px; text-align:center; border:1px solid #e9ecef; }}
  .card .num {{ font-size:2em; font-weight:800; color:#0f3460; }}
  .card .lbl {{ font-size:0.8em; color:#888; margin-top:4px; }}

  .legend {{ background:white; border-radius:10px; padding:16px 20px;
             margin-bottom:28px; display:flex; gap:24px; flex-wrap:wrap;
             border:1px solid #e9ecef; font-size:0.88em; }}
  .legend-item {{ display:flex; align-items:center; gap:6px; }}

  footer {{ text-align:center; color:#aaa; font-size:0.8em; margin-top:32px; padding:16px; }}
</style>
</head>
<body>
<div class="wrap">

<div class="cover">
  <div class="sub">블로그 독자 관심 × 뉴스 시장 이슈 교차 분석</div>
  <h1>ETF 콘텐츠 전략 브리프</h1>
  <div class="meta">
    <div class="meta-item">
      <div class="label">생성일</div>
      <div class="value">{report_date}</div>
    </div>
    <div class="meta-item">
      <div class="label">블로그 클러스터</div>
      <div class="value">{blog_count}개</div>
    </div>
    <div class="meta-item">
      <div class="label">뉴스 클러스터</div>
      <div class="value">{news_count}개</div>
    </div>
    <div class="meta-item">
      <div class="label">분석 주제</div>
      <div class="value">{len(briefs)}개</div>
    </div>
    <div class="meta-item">
      <div class="label">공통 주제</div>
      <div class="value">{common_count}개</div>
    </div>
  </div>
</div>

<div class="cards">
  <div class="card">
    <div class="num" style="color:#27ae60">{common_count}</div>
    <div class="lbl">🟩 공통 주제<br>(블로그+뉴스 동시 관심)</div>
  </div>
  <div class="card">
    <div class="num" style="color:#4A90D9">{sum(1 for b in briefs if b.get("source")=="블로그")}</div>
    <div class="lbl">🟦 블로그 전용<br>(독자 기존 관심)</div>
  </div>
  <div class="card">
    <div class="num" style="color:#e74c3c">{sum(1 for b in briefs if b.get("source")=="뉴스")}</div>
    <div class="lbl">🟥 뉴스 전용<br>(신흥 시장 이슈)</div>
  </div>
</div>

<div class="legend">
  <strong>범례</strong>
  <span class="legend-item"><span style="color:#27ae60">🟩 공통</span> — 두 소스 모두에서 포착된 핵심 주제. 콘텐츠 우선 제작 권장</span>
  <span class="legend-item"><span style="color:#4A90D9">🟦 블로그</span> — 독자가 이미 찾는 주제. 검색 유입 최적화 가능</span>
  <span class="legend-item"><span style="color:#e74c3c">🟥 뉴스</span> — 시장에서 부상 중인 주제. 선점 콘텐츠 기회</span>
</div>

{llm_section}

{cards_html}

<footer>ETF 콘텐츠 전략 브리프 | 블로그 + 뉴스 통합 분석 | {report_date}</footer>
</div>
</body>
</html>"""


# ── 메인 ──────────────────────────────────────────────────────────────────────

def build_content_brief_report() -> None:
    logger.info("콘텐츠 브리프 보고서 생성 시작")

    blog_clusters = load_clusters_from_db(BLOG_DB)
    news_clusters = load_clusters_from_db(NEWS_DB)
    logger.info("클러스터 로드: 블로그=%d, 뉴스=%d", len(blog_clusters), len(news_clusters))

    if not blog_clusters and not news_clusters:
        logger.error("양쪽 DB 모두 클러스터 없음. 파이프라인을 먼저 실행하세요.")
        return

    # ── LLM 선정 클러스터 + streak ────────────────────────────────────────────
    blog_streaks = _compute_all_streaks(BLOG_DB)
    news_streaks = _compute_all_streaks(NEWS_DB)
    logger.info("streak 계산 완료: 블로그=%d개, 뉴스=%d개 키워드", len(blog_streaks), len(news_streaks))

    llm_selected = _select_llm_clusters(blog_clusters, news_clusters, blog_streaks, news_streaks)
    logger.info("LLM 선정 클러스터: %d개", len(llm_selected))
    llm_section = _llm_selection_section_html(llm_selected)

    # ── 전체 브리프 매칭 ──────────────────────────────────────────────────────
    themes = match_clusters(blog_clusters, news_clusters)
    logger.info("매칭 결과: %d개 주제", len(themes))

    briefs = generate_content_briefs(themes)

    # API 미설정이면 매칭 결과만으로 보고서 생성
    if not briefs:
        logger.info("API 브리프 없음 — 클러스터 매칭 결과만으로 보고서 생성.")
        briefs = themes  # theme dict만 있어도 카드 렌더링 가능

    html = _build_html(briefs, len(blog_clusters), len(news_clusters), llm_section=llm_section)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    print(f"콘텐츠 브리프 저장: {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    build_content_brief_report()
