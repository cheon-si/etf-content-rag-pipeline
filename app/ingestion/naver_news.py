"""Naver News ingestion utilities.

네이버 뉴스 검색 API를 이용해 ETF 관련 뉴스를 수집한다.
블로그 수집과 달리 본문이 없으므로 title + description을 clean_text로 사용한다.
"""

from __future__ import annotations

import html
import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

NAVER_NEWS_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Remove HTML tags/entities and normalize whitespace."""
    no_tags = TAG_RE.sub("", text or "")
    decoded = html.unescape(no_tags)
    return WHITESPACE_RE.sub(" ", decoded).strip()


def _parse_news_date(pub_date: str) -> date | None:
    """Parse Naver news pubDate (RFC 2822) into date.

    Example: 'Mon, 15 Apr 2026 09:00:00 +0900'
    """
    if not pub_date:
        return None
    try:
        return parsedate_to_datetime(pub_date).date()
    except Exception:
        logger.warning("Failed to parse news pubDate: %s", pub_date)
        return None


def search_naver_news(
    query: str,
    start: int,
    display: int,
    retries: int = 2,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """Call Naver news search API and return JSON response."""
    resolved_client_id = client_id or settings.NAVER_CLIENT_ID
    resolved_client_secret = client_secret or settings.NAVER_CLIENT_SECRET
    if not resolved_client_id or not resolved_client_secret:
        raise ValueError("NAVER_CLIENT_ID or NAVER_CLIENT_SECRET is not set.")

    headers = {
        "X-Naver-Client-Id": resolved_client_id,
        "X-Naver-Client-Secret": resolved_client_secret,
    }
    params = {"query": query, "start": start, "display": display, "sort": "date"}

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            logger.info(
                "Request Naver news API (query=%s, start=%d, display=%d, attempt=%d)",
                query, start, display, attempt + 1,
            )
            response = requests.get(
                NAVER_NEWS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            # 인증/권한 오류(401, 403)는 재시도해도 의미 없음 → 즉시 전파
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                logger.error(
                    "Naver news API auth error (status=%s) — aborting all collection.", status
                )
                raise RuntimeError(f"Naver news API auth failed (HTTP {status}).") from exc

            last_error = exc
            logger.warning(
                "Naver news API request failed (query=%s, start=%d, attempt=%d): %s",
                query, start, attempt + 1, exc,
            )
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))

    logger.error("Naver news API failed after retries (query=%s, start=%d)", query, start)
    raise RuntimeError("Failed to call Naver news API.") from last_error


def collect_news_posts(
    keywords: list[str],
    days: int,
    max_per_keyword: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Collect news articles per keyword with deduplication.

    뉴스는 본문이 없으므로 title + description을 합쳐 clean_text로 저장한다.
    source_type='news'로 블로그와 구분한다.

    날짜 범위 적용 규칙:
    - start_date, end_date 둘 다 지정 → 해당 범위 내 뉴스만 수집
    - start_date만 지정           → start_date 이후 수집 (end_date=오늘)
    - end_date만 지정             → days 기준 cutoff ~ end_date 범위 수집
    - 둘 다 None                  → 최근 days일 기준 수집 (기본 동작)
    """
    config = settings.load_settings()

    if start_date or end_date:
        cutoff_date = start_date if start_date else (datetime.now() - timedelta(days=days)).date()
        if end_date is None:
            end_date = datetime.now().date()
        logger.info(
            "Start news collection (keywords=%d, range=%s~%s, max_per_keyword=%d)",
            len(keywords), cutoff_date, end_date, max_per_keyword,
        )
    else:
        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        end_date = None
        logger.info(
            "Start news collection (keywords=%d, days=%d, max_per_keyword=%d)",
            len(keywords), days, max_per_keyword,
        )

    all_posts: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for keyword in keywords:
        collected_for_keyword = 0
        start = 1
        display = 100

        while collected_for_keyword < max_per_keyword:
            remaining = max_per_keyword - collected_for_keyword
            page_size = min(display, remaining)

            try:
                payload = search_naver_news(
                    query=keyword,
                    start=start,
                    display=page_size,
                    client_id=str(config["NAVER_CLIENT_ID"]),
                    client_secret=str(config["NAVER_CLIENT_SECRET"]),
                )
            except Exception as exc:
                logger.error("Stop keyword due to API error (keyword=%s): %s", keyword, exc)
                break

            items = payload.get("items", [])
            if not items:
                logger.info("No more items (keyword=%s, start=%d)", keyword, start)
                break

            added_in_page = 0
            old_docs_in_page = 0
            for item in items:
                pub_date_raw = item.get("pubDate", "")
                post_dt = _parse_news_date(pub_date_raw)
                if post_dt is None:
                    continue

                if post_dt < cutoff_date:
                    old_docs_in_page += 1
                    continue

                if end_date and post_dt > end_date:
                    continue

                # originallink 우선, 없으면 link 사용
                link = item.get("originallink", "").strip() or item.get("link", "").strip()
                if not link or link in seen_links:
                    continue

                title = _strip_html(item.get("title", ""))
                description = _strip_html(item.get("description", ""))
                # 뉴스는 본문이 없으므로 title + description을 clean_text로 활용
                clean_text = f"{title} {description}".strip()

                doc_id = hashlib.sha1(f"{keyword}|{link}".encode("utf-8")).hexdigest()[:16]

                post = {
                    "keyword": keyword,
                    "doc_id": doc_id,
                    "title": title,
                    "description": description,
                    "clean_text": clean_text,
                    "link": link,
                    "post_date": post_dt.isoformat(),
                    "source_type": "news",
                }
                all_posts.append(post)
                seen_links.add(link)
                collected_for_keyword += 1
                added_in_page += 1

                if collected_for_keyword >= max_per_keyword:
                    break

            logger.info(
                "Collected news page (keyword=%s, start=%d, added=%d, too_old=%d)",
                keyword, start, added_in_page, old_docs_in_page,
            )

            threshold = max(3, len(items) // 2)
            if added_in_page == 0 and old_docs_in_page >= threshold:
                logger.info("Early stop: too old (keyword=%s)", keyword)
                break

            if len(items) < page_size:
                break

            start += page_size
            if start > 1000:
                logger.info("Reached Naver paging limit (keyword=%s)", keyword)
                break

    logger.info("News collection done (total_posts=%d)", len(all_posts))
    return all_posts
