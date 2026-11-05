"""External grounding for occasions the curated file does not know.

Uses the public Wikipedia API (opensearch + page summary): free, no key, short
factual extracts. Every failure mode degrades to "not found" so the agent falls
back to a clearly generic design instead of inventing facts.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

SEARCH_API = "https://en.wikipedia.org/w/api.php"
SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
USER_AGENT = "SeasonalWebsiteDemo/1.0 (placeholder demo)"
MAX_SUMMARY_CHARS = 800
MIN_SUMMARY_CHARS = 80


def _get_json(url: str, timeout_s: float) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read(256 * 1024).decode("utf-8"))


def search_festival(name: str, timeout_s: float = 8) -> dict:
    """Search for an occasion; returns found/title/summary/url. Never raises."""
    try:
        query = urllib.parse.urlencode({
            "action": "opensearch",
            "search": name,
            "limit": 5,
            "format": "json",
        })
        data = _get_json(f"{SEARCH_API}?{query}", timeout_s)
        titles = data[1] if isinstance(data, list) and len(data) > 1 else []
        if not isinstance(titles, list):
            return {"found": False}
        for title in titles[:5]:
            if not isinstance(title, str) or not title:
                continue
            try:
                page = _get_json(SUMMARY_API + urllib.parse.quote(title), timeout_s)
            except Exception:
                continue
            if not isinstance(page, dict) or page.get("type") == "disambiguation":
                continue
            summary = (page.get("extract") or "").strip()
            if len(summary) < MIN_SUMMARY_CHARS:
                continue
            desktop = (page.get("content_urls") or {}).get("desktop") or {}
            return {
                "found": True,
                "title": title,
                "summary": summary[:MAX_SUMMARY_CHARS],
                "url": desktop.get("page", ""),
            }
        return {"found": False}
    except Exception:
        return {"found": False}
