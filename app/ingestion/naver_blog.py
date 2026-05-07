"""Naver blog ingestion utilities."""

from __future__ import annotations

import html
import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

NAVER_BLOG_SEARCH_URL = "https://openapi.naver.com/v1/search/blog.json"
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Remove HTML tags/entities and normalize whitespace."""
    no_tags = TAG_RE.sub("", text or "")
    decoded = html.unescape(no_tags)
    return WHITESPACE_RE.sub(" ", decoded).strip()


def _parse_naver_date(date_text: str) -> date | None:
    """Parse Naver blog date string (YYYYMMDD) into date."""
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, "%Y%m%d").date()
    except ValueError:
        logger.warning("Failed to parse post date: %s", date_text)
        return None


def search_naver_blog(
    query: str,
    start: int,
    display: int,
    retries: int = 2,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """Call Naver blog search API and return JSON response."""
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
                "Request Naver blog API (query=%s, start=%d, display=%d, attempt=%d)",
                query,
                start,
                display,
                attempt + 1,
            )
            response = requests.get(
                NAVER_BLOG_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Naver API request failed (query=%s, start=%d, attempt=%d): %s",
                query,
                start,
                attempt + 1,
                exc,
            )
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))

    logger.error("Naver API failed after retries (query=%s, start=%d)", query, start)
    raise RuntimeError("Failed to call Naver blog API.") from last_error


def collect_blog_posts(
    keywords: list[str],
    days: int,
    max_per_keyword: int,
) -> list[dict[str, Any]]:
    """Collect recent blog posts per keyword with deduplication and HTML cleaning."""
    config = settings.load_settings()
    cutoff_date = (datetime.now() - timedelta(days=days)).date()
    all_posts: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    logger.info(
        "Start blog collection (keywords=%d, days=%d, max_per_keyword=%d)",
        len(keywords),
        days,
        max_per_keyword,
    )

    for keyword in keywords:
        collected_for_keyword = 0
        start = 1
        display = 100

        while collected_for_keyword < max_per_keyword:
            remaining = max_per_keyword - collected_for_keyword
            page_size = min(display, remaining)

            try:
                payload = search_naver_blog(
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
                post_date_raw = item.get("postdate", "")
                post_dt = _parse_naver_date(post_date_raw)
                if post_dt is None:
                    continue
                if post_dt < cutoff_date:
                    old_docs_in_page += 1
                    continue

                link = item.get("link", "").strip()
                if not link or link in seen_links:
                    continue

                blogger_name = _strip_html(item.get("bloggername", ""))
                blogger_link = item.get("bloggerlink", "").strip()
                doc_id = hashlib.sha1(f"{keyword}|{link}".encode("utf-8")).hexdigest()[:16]

                post = {
                    "keyword": keyword,
                    "doc_id": doc_id,
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": link,
                    "post_date": post_dt.isoformat(),
                    "blogger_name": blogger_name,
                    "blogger_link": blogger_link,
                }
                all_posts.append(post)
                seen_links.add(link)
                collected_for_keyword += 1
                added_in_page += 1

                if collected_for_keyword >= max_per_keyword:
                    break

            logger.info(
                "Collected page (keyword=%s, start=%d, page_items=%d, added=%d, total_keyword=%d)",
                keyword,
                start,
                len(items),
                added_in_page,
                collected_for_keyword,
            )

            old_doc_majority_threshold = max(3, len(items) // 2)
            if added_in_page == 0 and old_docs_in_page >= old_doc_majority_threshold:
                logger.info(
                    "Early stop for keyword due to old documents (keyword=%s, old_docs=%d, page_items=%d)",
                    keyword,
                    old_docs_in_page,
                    len(items),
                )
                break

            if len(items) < page_size:
                break
            start += page_size
            if start > 1000:
                logger.info("Reached Naver paging limit (keyword=%s)", keyword)
                break

    logger.info("Collection done (total_posts=%d)", len(all_posts))
    return all_posts
