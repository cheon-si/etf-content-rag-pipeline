"""Blog content extraction utilities."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup, FeatureNotFound

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_WHITESPACE_RE = re.compile(r"\s+")
_MIN_SELECTOR_TEXT_LENGTH = 80
_MIN_FALLBACK_TEXT_LENGTH = 120


def _parse_html(html_text: str) -> BeautifulSoup:
    """Parse HTML using lxml when available, then fallback to html.parser."""
    try:
        return BeautifulSoup(html_text, "lxml")
    except FeatureNotFound:
        logger.warning("lxml parser is unavailable. Falling back to html.parser.")
        return BeautifulSoup(html_text, "html.parser")


def _normalize_whitespace(text: str) -> str:
    """Normalize consecutive whitespace characters to a single space."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _fetch_html(url: str) -> str:
    """Fetch HTML from URL and return response text."""
    try:
        response = requests.get(url, headers=_HEADERS, timeout=10)
        response.raise_for_status()
    except requests.exceptions.SSLError:
        logger.warning("SSL verification failed for %s. Retrying once without certificate verification.", url)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(url, headers=_HEADERS, timeout=10, verify=False)
        response.raise_for_status()

    if response.apparent_encoding:
        response.encoding = response.apparent_encoding
    return response.text


def _resolve_naver_iframe_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Resolve Naver blog iframe URL when main content is embedded in an iframe."""
    iframe = soup.select_one("iframe#mainFrame")
    if iframe is None:
        return None

    src = iframe.get("src")
    if not src:
        return None

    return urljoin(base_url, src)


def _extract_text_from_soup(soup: BeautifulSoup) -> str:
    """Extract readable text from known Naver blog content containers."""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    selectors = [
        ".se-main-container",
        "#postViewArea",
        ".post-view",
        ".post-view .view",
        ".contents_style",
        ".blog2_series",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node is not None:
            text = _normalize_whitespace(" ".join(node.stripped_strings))
            if len(text) >= _MIN_SELECTOR_TEXT_LENGTH:
                return text

    body = soup.body
    if body is None:
        return ""
    fallback_text = _normalize_whitespace(" ".join(body.stripped_strings))
    if len(fallback_text) < _MIN_FALLBACK_TEXT_LENGTH:
        return ""
    return fallback_text


def extract_blog_content(url: str) -> str:
    """Extract blog body text from a URL. Returns empty string on failure."""
    try:
        logger.info("Extracting blog content from %s", url)
        html_text = _fetch_html(url)
        soup = _parse_html(html_text)

        iframe_url = _resolve_naver_iframe_url(soup, url)
        if iframe_url:
            logger.info("Detected Naver iframe. Loading frame URL: %s", iframe_url)
            frame_html = _fetch_html(iframe_url)
            soup = _parse_html(frame_html)

        text = _extract_text_from_soup(soup)
        if not text:
            logger.warning("No extractable text found for URL: %s", url)
            return ""
        return text
    except Exception as exc:
        logger.exception("Failed to extract blog content from %s: %s", url, exc)
        return ""
