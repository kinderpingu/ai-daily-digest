"""
tools/web_search.py

Upgraded search — uses Google News RSS as primary source (no API key, great results),
falls back to DuckDuckGo if RSS fails.
"""

import logging
import re
import urllib.parse
import html
from typing import Any, Dict, List

import httpx

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
}


async def web_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    results = await _google_news_rss(query, num_results)
    if not results:
        log.warning("Google News RSS returned nothing, trying DDG...")
        results = await _ddg_lite_scrape(query, num_results)
    log.info("  web_search(%r) -> %d results", query, len(results))

    return {"query": query, "results": results}


async def _google_news_rss(query: str, num: int) -> List[Dict]:
    """Google News RSS — no API key, real news articles, always fresh."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            xml = resp.text

        # Parse RSS items
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
        results = []
        seen = set()
        for item in items[:num * 2]:
            title = re.search(r"<title>(.*?)</title>", item, re.S)
            link  = re.search(r"<link/>(.*?)\n|<link>(.*?)</link>", item, re.S)
            desc  = re.search(r"<description>(.*?)</description>", item, re.S)

            title_text = _clean(title.group(1)) if title else ""
            # Google News RSS puts URL after <link/>
            raw_link = ""
            if link:
                raw_link = (link.group(1) or link.group(2) or "").strip()
            desc_text = _clean(desc.group(1)) if desc else ""

            key = (title_text.lower(), raw_link.split("#", 1)[0])
            if title_text and raw_link and key not in seen:
                seen.add(key)
                results.append({
                    "title": title_text,
                    "url": raw_link,
                    "snippet": desc_text[:300],
                })
                if len(results) >= num:
                    break
        return results
    except Exception as exc:
        log.warning("Google News RSS failed: %s", exc)
        return []


async def _ddg_lite_scrape(query: str, num: int) -> List[Dict]:
    """Fallback: DuckDuckGo lite."""
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
            resp.raise_for_status()
            html = resp.text
        results = []
        links    = re.findall(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
        snippets = re.findall(r'<td[^>]+class="result-snippet"[^>]*>(.*?)</td>', html, re.S)
        for i, (url, title) in enumerate(links[:num]):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]) if i < len(snippets) else ""
            results.append({"title": title.strip(), "url": url.strip(), "snippet": snippet.strip()})
        return results
    except Exception as exc:
        log.error("DDG fallback also failed: %s", exc)
        return []


def _clean(text: str) -> str:
    """Strip HTML tags and decode basic entities."""
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
