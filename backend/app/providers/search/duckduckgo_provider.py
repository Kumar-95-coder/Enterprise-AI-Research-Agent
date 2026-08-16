"""
Real DuckDuckGo-backed provider -- free, no API key, and (unlike
SearXNGProvider) no self-hosted service to run either. Uses the `ddgs`
package (https://pypi.org/project/ddgs/, `pip install ddgs`), which queries
real search engines' public web interfaces directly and scrapes structured
results out of the HTML response.

This is the lowest-setup keyless option: install one package and it works.
The tradeoff, stated plainly: this is not an official, documented API --
DuckDuckGo doesn't offer a free public search API -- so it is inherently
more fragile than SearXNGProvider. It can break when a target site changes
its page structure, and sustained/heavy use risks temporary rate-limiting.
Good for light or occasional use and quick local testing; SearXNGProvider
(self-hosted) is the more robust choice for sustained use.

Verified against the installed `ddgs` package's actual source (checked
2026-08-14, not just documentation): `DDGS().text(query, max_results=...,
backend="duckduckgo")` returns `list[dict]` with keys `title`, `href`,
`body` (confirmed via `ddgs/engines/duckduckgo.py` and `ddgs/results.py` in
the installed package). Note `ddgs` has grown into a small multi-engine
client since its DuckDuckGo-only origins -- `backend="duckduckgo"` below
pins it to DuckDuckGo specifically, matching what this provider promises;
`backend="auto"` would let the library pick across several engines instead.

NOT exercised live in this sandboxed repo -- this sandbox has no route to
duckduckgo.com (its network is restricted to package registries).
"""
from typing import List, Dict

from app.providers.search.base import SearchProvider


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def __init__(self):
        try:
            from ddgs import DDGS
            self._DDGS = DDGS
            self._import_error = None
        except ImportError as e:
            self._DDGS = None
            self._import_error = str(e)

    def is_live(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        if self._DDGS is None:
            raise RuntimeError(
                f"The `ddgs` package isn't installed ({self._import_error}). "
                f"Run `pip install ddgs`, or use SEARCH_PROVIDER=searxng / local_corpus instead."
            )
        try:
            with self._DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=max_results, backend="duckduckgo"))
        except Exception as e:
            raise RuntimeError(
                f"DuckDuckGo search failed ({e}). This is often transient rate-limiting from "
                f"scraping-based search -- SEARCH_PROVIDER=searxng (self-hosted) is more "
                f"reliable for sustained use; retrying in a few seconds may also work."
            )

        out = []
        for r in raw_results:
            url = r.get("href") or r.get("url")
            if not url:
                continue
            out.append({
                "title": r.get("title", "Untitled"),
                "url": url,
                "publisher": _domain(url),
                "author": None,
                "publication_date": None,  # not exposed by this backend
                "source_type": "web",
                "content": (r.get("body") or "")[:2000],
                "snippet_score": 0.5,
                "retrieved_via": "duckduckgo",
            })
        return out


def _domain(url: str) -> str:
    try:
        return url.split("/")[2].replace("www.", "")
    except Exception:
        return "unknown"
