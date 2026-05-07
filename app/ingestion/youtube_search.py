"""YouTube Data API v3 ingestion utilities."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_MAX_RESULTS_PER_PAGE = 50
_KO_RE = __import__("re").compile(r"[가-힣]")


def _is_korean(text: str) -> bool:
    """제목에 한글이 1자 이상 포함되어 있으면 한국 영상으로 판단."""
    return bool(_KO_RE.search(text or ""))


def _iso_days_ago(days: int) -> str:
    """Return ISO 8601 datetime string for N days ago (UTC)."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _search_videos(
    query: str,
    published_after: str,
    max_results: int,
    api_key: str,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Call YouTube search.list and return raw JSON."""
    params: dict[str, Any] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": min(max_results, _MAX_RESULTS_PER_PAGE),
        "regionCode": "KR",
        "relevanceLanguage": "ko",
        "key": api_key,
    }
    if page_token:
        params["pageToken"] = page_token

    resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_video_stats(video_ids: list[str], api_key: str) -> dict[str, dict[str, int]]:
    """Call YouTube videos.list for statistics. Returns {video_id: {view, like, comment}}."""
    if not video_ids:
        return {}

    stats: dict[str, dict[str, int]] = {}
    # API allows max 50 ids per request
    for chunk_start in range(0, len(video_ids), 50):
        chunk = video_ids[chunk_start : chunk_start + 50]
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": api_key,
        }
        try:
            resp = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=15)
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                vid_id = item["id"]
                s = item.get("statistics", {})
                stats[vid_id] = {
                    "view_count": int(s.get("viewCount", 0)),
                    "like_count": int(s.get("likeCount", 0)),
                    "comment_count": int(s.get("commentCount", 0)),
                }
        except Exception as exc:
            logger.warning("Failed to fetch stats for chunk starting at %d: %s", chunk_start, exc)

    return stats


def collect_youtube_videos(
    keywords: list[str],
    days: int = 7,
    max_per_keyword: int = 50,
    api_key: str = "",
) -> list[dict[str, Any]]:
    """
    Collect YouTube videos for given keywords published within `days` days.

    Returns:
        List of dicts: {keyword, video_id, title, description, channel_title,
                        published_at, view_count, like_count, comment_count}
    """
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is required.")

    published_after = _iso_days_ago(days)
    all_videos: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for keyword in keywords:
        collected = 0
        page_token: str | None = None

        while collected < max_per_keyword:
            remaining = max_per_keyword - collected
            try:
                data = _search_videos(
                    query=keyword,
                    published_after=published_after,
                    max_results=min(remaining, _MAX_RESULTS_PER_PAGE),
                    api_key=api_key,
                    page_token=page_token,
                )
            except Exception as exc:
                logger.error("YouTube search failed (keyword=%s): %s", keyword, exc)
                break

            items = data.get("items", [])
            if not items:
                break

            video_ids = [
                item["id"]["videoId"]
                for item in items
                if item.get("id", {}).get("videoId")
            ]
            stats_map = _fetch_video_stats(video_ids, api_key)

            for item in items:
                vid_id = item.get("id", {}).get("videoId")
                if not vid_id or vid_id in seen_ids:
                    continue
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                # 한국어 영상만 수집 (제목에 한글 없으면 스킵)
                if not _is_korean(title):
                    continue
                s = stats_map.get(vid_id, {})
                all_videos.append({
                    "keyword": keyword,
                    "video_id": vid_id,
                    "title": title,
                    "description": snippet.get("description", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "view_count": s.get("view_count", 0),
                    "like_count": s.get("like_count", 0),
                    "comment_count": s.get("comment_count", 0),
                })
                seen_ids.add(vid_id)
                collected += 1

            logger.info(
                "YouTube collected (keyword=%s, page_items=%d, total=%d)",
                keyword, len(items), len(all_videos),
            )

            page_token = data.get("nextPageToken")
            if not page_token or collected >= max_per_keyword:
                break

            time.sleep(0.3)  # API quota 보호

    logger.info("YouTube collection done (total_videos=%d)", len(all_videos))
    return all_videos
