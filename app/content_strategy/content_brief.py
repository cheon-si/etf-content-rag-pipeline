"""
content_brief.py — 블로그 + 뉴스 클러스터 교차 분석 기반 콘텐츠 브리프 생성기.

블로그 클러스터 (독자 관심) × 뉴스 클러스터 (시장 이슈)를 키워드 겹침으로 매칭하고,
Claude API로 Search Intent / JTBD / AIDA / PAS 프레임워크 적용 브리프를 생성한다.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.config.constants import GENERIC_KEYWORDS as _GENERIC_KWS
from app.config.constants import NOISE_KEYWORDS as _NOISE_KWS

logger = logging.getLogger(__name__)


def _is_noise(kw_list: list[str]) -> bool:
    return any(n in kw_list for n in _NOISE_KWS)


def _distinctive(kw_list: list[str], n: int = 5) -> list[str]:
    return [k for k in kw_list if k.lower() not in _GENERIC_KWS][:n]


def _theme_name(blog_kws: list[str], news_kws: list[str]) -> str:
    """블로그/뉴스 키워드에서 대표 주제명 생성 (distinctive 2~3개)."""
    combined = blog_kws + [k for k in news_kws if k not in blog_kws]
    dist = _distinctive(combined, 3)
    return "/".join(dist) if dist else "/".join((blog_kws + news_kws)[:3])


def match_clusters(
    blog_clusters: list[dict[str, Any]],
    news_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    블로그/뉴스 클러스터를 키워드 겹침 기준으로 매칭.

    Returns:
        list of theme dicts:
        {
            "theme":         str,       # 대표 주제명
            "source":        str,       # "공통" | "블로그" | "뉴스"
            "blog_keywords": list[str],
            "news_keywords": list[str],
            "blog_size":     int,
            "news_size":     int,
        }
    """
    # 노이즈 클러스터 제거
    clean_blog = [c for c in blog_clusters if not _is_noise(c.get("keywords", []))]
    clean_news = [c for c in news_clusters if not _is_noise(c.get("keywords", []))]

    # distinctive 키워드가 2개 미만인 클러스터 제거
    clean_blog = [c for c in clean_blog if len(_distinctive(c.get("keywords", []))) >= 2]
    clean_news = [c for c in clean_news if len(_distinctive(c.get("keywords", []))) >= 2]

    matched_blog_ids: set[int] = set()
    matched_news_ids: set[int] = set()
    themes: list[dict[str, Any]] = []

    # 모든 쌍의 겹침 수 계산 후 내림차순 정렬
    pairs: list[tuple[int, int, int]] = []
    for bi, bc in enumerate(clean_blog):
        bset = set(bc.get("keywords", []))
        for ni, nc in enumerate(clean_news):
            nset = set(nc.get("keywords", []))
            overlap = len(bset & nset)
            if overlap >= 2:
                pairs.append((overlap, bi, ni))
    pairs.sort(reverse=True)

    # 겹침 많은 순으로 매칭 (각 클러스터는 1번만 매칭)
    for _, bi, ni in pairs:
        if bi in matched_blog_ids or ni in matched_news_ids:
            continue
        bc = clean_blog[bi]
        nc = clean_news[ni]
        bkws = bc.get("keywords", [])
        nkws = nc.get("keywords", [])
        themes.append({
            "theme":         _theme_name(bkws, nkws),
            "source":        "공통",
            "blog_keywords": bkws,
            "news_keywords": nkws,
            "blog_size":     bc.get("size", 0),
            "news_size":     nc.get("size", 0),
        })
        matched_blog_ids.add(bi)
        matched_news_ids.add(ni)

    # 매칭 안 된 블로그 클러스터
    for bi, bc in enumerate(clean_blog):
        if bi in matched_blog_ids:
            continue
        bkws = bc.get("keywords", [])
        themes.append({
            "theme":         _theme_name(bkws, []),
            "source":        "블로그",
            "blog_keywords": bkws,
            "news_keywords": [],
            "blog_size":     bc.get("size", 0),
            "news_size":     0,
        })

    # 매칭 안 된 뉴스 클러스터
    for ni, nc in enumerate(clean_news):
        if ni in matched_news_ids:
            continue
        nkws = nc.get("keywords", [])
        themes.append({
            "theme":         _theme_name([], nkws),
            "source":        "뉴스",
            "blog_keywords": [],
            "news_keywords": nkws,
            "blog_size":     0,
            "news_size":     nc.get("size", 0),
        })

    logger.info(
        "Cluster matching done: 공통=%d, 블로그전용=%d, 뉴스전용=%d",
        sum(1 for t in themes if t["source"] == "공통"),
        sum(1 for t in themes if t["source"] == "블로그"),
        sum(1 for t in themes if t["source"] == "뉴스"),
    )
    return themes


def _parse_brief(text: str) -> dict[str, Any]:
    """Claude 응답 텍스트를 구조화된 dict로 파싱."""
    result: dict[str, Any] = {
        "search_intent": "",
        "jtbd": "",
        "aida": {"attention": "", "interest": "", "desire": "", "action": ""},
        "pas":  {"problem": "", "agitate": "", "solution": ""},
        "blog_titles":    [],
        "youtube_titles": [],
        "sns_messages":   [],
    }

    lines = text.splitlines()
    section = None
    blog_count = youtube_count = sns_count = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        lower = line.lower()

        # 섹션 감지
        if lower.startswith("search intent"):
            val = line.split(":", 1)[-1].strip()
            result["search_intent"] = val
        elif lower.startswith("jtbd"):
            val = line.split(":", 1)[-1].strip()
            result["jtbd"] = val
        elif "aida" in lower and ":" not in lower[:8]:
            section = "aida"
        elif "pas" in lower and ":" not in lower[:6]:
            section = "pas"
        elif "블로그 제목" in line:
            section = "blog"
            blog_count = 0
        elif "유튜브 제목" in line:
            section = "youtube"
            youtube_count = 0
        elif "sns" in lower or "한줄" in line:
            section = "sns"
            sns_count = 0

        # AIDA 항목
        elif section == "aida":
            if line.startswith("- Attention") or line.startswith("- attention"):
                result["aida"]["attention"] = line.split(":", 1)[-1].strip()
            elif line.startswith("- Interest") or line.startswith("- interest"):
                result["aida"]["interest"] = line.split(":", 1)[-1].strip()
            elif line.startswith("- Desire") or line.startswith("- desire"):
                result["aida"]["desire"] = line.split(":", 1)[-1].strip()
            elif line.startswith("- Action") or line.startswith("- action"):
                result["aida"]["action"] = line.split(":", 1)[-1].strip()

        # PAS 항목
        elif section == "pas":
            if line.startswith("- Problem") or line.startswith("- problem"):
                result["pas"]["problem"] = line.split(":", 1)[-1].strip()
            elif line.startswith("- Agitate") or line.startswith("- agitate"):
                result["pas"]["agitate"] = line.split(":", 1)[-1].strip()
            elif line.startswith("- Solution") or line.startswith("- solution"):
                result["pas"]["solution"] = line.split(":", 1)[-1].strip()

        # 번호 리스트 항목
        elif section in ("blog", "youtube", "sns") and line and line[0].isdigit() and "." in line:
            item = line.split(".", 1)[-1].strip()
            if not item:
                continue
            if section == "blog" and blog_count < 3:
                result["blog_titles"].append(item)
                blog_count += 1
            elif section == "youtube" and youtube_count < 3:
                result["youtube_titles"].append(item)
                youtube_count += 1
            elif section == "sns" and sns_count < 2:
                result["sns_messages"].append(item)
                sns_count += 1

    return result


def generate_content_briefs(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    매칭된 theme 리스트를 받아 Claude API로 콘텐츠 브리프 생성.

    Args:
        themes: match_clusters() 반환값

    Returns:
        각 theme dict에 search_intent / jtbd / aida / pas / 제목 아이디어 추가된 리스트.
        API 미설정 또는 실패 시 빈 리스트 반환.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY 미설정 — 콘텐츠 브리프 생성 스킵.")
        return []

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic 패키지 미설치 — 콘텐츠 브리프 생성 스킵.")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    results: list[dict[str, Any]] = []

    for theme in themes:
        bkws = theme.get("blog_keywords", [])
        nkws = theme.get("news_keywords", [])

        blog_str = ", ".join(bkws[:8]) if bkws else "없음"
        news_str = ", ".join(nkws[:8]) if nkws else "없음"

        prompt = f"""당신은 ETF 투자 콘텐츠 전략 전문가입니다.
아래 두 가지 데이터를 바탕으로 콘텐츠 브리프를 작성해주세요.

[블로그 독자 관심 키워드]: {blog_str}
[뉴스/시장 이슈 키워드]: {news_str}

다음 형식으로 정확히 응답해주세요 (항목 순서와 표기를 지켜주세요):

Search Intent: 정보성 또는 비교성 또는 거래성

JTBD: 나는 [구체적 상황]에서 [동기]를 가지고 [목표]를 달성하고 싶다

AIDA:
- Attention: (독자의 주목을 끄는 훅 한 문장)
- Interest: (관심을 유지시키는 핵심 정보 한 문장)
- Desire: (원하게 만드는 욕구 자극 한 문장)
- Action: (실행을 유도하는 CTA 한 문장)

PAS:
- Problem: (독자의 핵심 페인포인트 한 문장)
- Agitate: (문제를 심화시키는 한 문장)
- Solution: (ETF로 해결되는 방법 한 문장)

블로그 제목 3개:
1.
2.
3.

유튜브 제목 3개:
1.
2.
3.

SNS 메시지 2개:
1.
2.
"""

        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            parsed = _parse_brief(raw)
            results.append({**theme, **parsed})
            logger.info(
                "브리프 생성 완료: %s (%s)", theme["theme"], theme["source"]
            )
        except Exception as exc:
            logger.warning("Claude API 실패 (theme=%s): %s", theme["theme"], exc)

    return results
