"""
Real live web-search provider. Complete, correct code -- NOT exercised in
this sandboxed demo, because this container's network is restricted to
package registries (see docker/README notes) and has no SEARCH_API_KEY.

Written against Tavily's API shape (https://docs.tavily.com) since it has a
free tier and a simple JSON contract; swapping to Bing/Serper/SerpAPI/etc.
means changing the request/response mapping below, not the pipeline.
"""
import requests
from typing import List, Dict

from app.providers.search.base import SearchProvider
from app.config import get_settings


class LiveHttpSearchProvider(SearchProvider):
    name = "live_http"

    def __init__(self):
        self.settings = get_settings()

    def is_live(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        if not self.settings.SEARCH_API_KEY:
            raise RuntimeError(
                "SEARCH_PROVIDER=live_http requires SEARCH_API_KEY to be set. "
                "Use SEARCH_PROVIDER=local_corpus for offline/demo mode."
            )
        resp = requests.post(
            self.settings.SEARCH_API_URL,
            json={
                "api_key": self.settings.SEARCH_API_KEY,
                "query": query,
                "max_results": max_results,
                "include_raw_content": False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        out = []
        for r in data.get("results", [])[:max_results]:
            out.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url"),
                "publisher": _domain(r.get("url", "")),
                "author": None,
                "publication_date": r.get("published_date"),
                "source_type": "web",
                "content": r.get("content", "")[:2000],
                "snippet_score": r.get("score", 0.5),
            })
        return out


def _domain(url: str) -> str:
    try:
        return url.split("/")[2].replace("www.", "")
    except Exception:
        return "unknown"
