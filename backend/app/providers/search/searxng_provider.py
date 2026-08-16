"""
Real SearXNG-backed provider -- free, open-source, no API key required.

SearXNG (https://docs.searxng.org) is a self-hostable metasearch engine: it
aggregates results from real search engines (Google, Bing, Brave,
DuckDuckGo, Wikipedia, and more, all configurable) behind one JSON API,
with no tracking and no API key. Self-hosting is one Docker service --
`docker compose --profile search up searxng` (see docker-compose.yml, and
docker/searxng-settings.yml for the minimal config that enables the JSON
API, which is OFF by default on a stock SearXNG install).

Public SearXNG instances also exist (https://searx.space lists them) and
SEARXNG_URL can point at one instead of a local container, but many public
instances disable the JSON format for anti-abuse reasons or rate-limit it
heavily -- self-hosting is the reliable path, which is why it's wired into
docker-compose.yml as a first-class service.

Verified against SearXNG's current documented Search API (checked
2026-08-14, https://docs.searxng.org/dev/search_api.html): GET /search with
?q=<query>&format=json; requesting a format not enabled in settings.yml
returns 403, not empty results -- handled explicitly below with a clear
error rather than a silent empty response.

NOT exercised live in the sandboxed demo bundled with this repo -- that
sandbox's network cannot pull the searxng Docker image or reach any
instance's HTTP API.
"""
import requests
from typing import List, Dict

from app.providers.search.base import SearchProvider
from app.config import get_settings


class SearXNGProvider(SearchProvider):
    name = "searxng"

    def __init__(self):
        self.base_url = get_settings().SEARXNG_URL.rstrip("/")

    def is_live(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        try:
            resp = requests.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json", "language": "en"},
                timeout=20,
            )
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach SearXNG at {self.base_url}. Run "
                f"`docker compose --profile search up searxng` (see docker-compose.yml), "
                f"or point SEARXNG_URL at a public instance from https://searx.space. "
                f"Original error: {e}"
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"SearXNG at {self.base_url} returned 403 for format=json -- the JSON API is "
                f"disabled on this instance by default. If self-hosting, add to settings.yml: "
                f"`search:\\n  formats:\\n    - html\\n    - json` and restart "
                f"(docker/searxng-settings.yml in this repo already does this)."
            )
        resp.raise_for_status()
        data = resp.json()

        out = []
        for r in data.get("results", [])[:max_results]:
            out.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url"),
                "publisher": r.get("engine") or _domain(r.get("url", "")),
                "author": None,
                "publication_date": r.get("publishedDate"),
                "source_type": "web",
                "content": (r.get("content") or "")[:2000],
                "snippet_score": r.get("score", 0.5),
                "retrieved_via": "searxng",
            })
        return out


def _domain(url: str) -> str:
    try:
        return url.split("/")[2].replace("www.", "")
    except Exception:
        return "unknown"
