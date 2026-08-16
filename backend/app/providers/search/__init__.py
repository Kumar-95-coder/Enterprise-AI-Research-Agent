from app.config import get_settings
from app.providers.search.local_corpus_provider import LocalCorpusSearchProvider


def get_search_provider():
    provider = get_settings().SEARCH_PROVIDER.lower()
    if provider == "live_http":
        from app.providers.search.live_http_provider import LiveHttpSearchProvider
        return LiveHttpSearchProvider()
    if provider == "searxng":
        from app.providers.search.searxng_provider import SearXNGProvider
        return SearXNGProvider()
    if provider == "duckduckgo":
        from app.providers.search.duckduckgo_provider import DuckDuckGoProvider
        return DuckDuckGoProvider()
    return LocalCorpusSearchProvider()
