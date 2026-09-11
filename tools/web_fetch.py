"""
tools/web_fetch.py

Fetches a URL and returns cleaned plain text, capped at max_chars.
Uses trafilatura for article extraction (strips ads, nav, footers).
Falls back to raw HTML stripping if trafilatura can't parse the page.
"""

import logging
import re
from typing import Dict

import httpx

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def web_fetch(url: str, max_chars: int = 4000) -> Dict:
    """
    Returns:
        {"url": str, "title": str, "text": str, "chars": int}
        or
        {"url": str, "error": str}
    """
    try:
        async with httpx.AsyncClient(
            timeout=20,
            headers=HEADERS,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        log.warning("web_fetch(%s) failed: %s", url, exc)
        return {"url": url, "error": str(exc)}

    title, text = _extract(html)
    text = text[:max_chars]
    log.debug("web_fetch(%s) → %d chars", url, len(text))
    return {
        "url": url,
        "source_url": str(resp.url),
        "title": title,
        "text": text,
        "chars": len(text),
    }


def _extract(html: str):
    """Try trafilatura first, fall back to naive strip."""
    title = _extract_title(html)
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        if text.strip():
            return title, text.strip()
    except ImportError:
        pass

    # Naive fallback: strip all tags
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return title, text.strip()


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return ""
