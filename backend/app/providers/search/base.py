from abc import ABC, abstractmethod
from typing import List, Dict


class SearchProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """Return a list of candidate sources:
        {title, url, publisher, author, publication_date, source_type, content, snippet_score}
        An empty list is a valid, honest answer -- providers must never invent
        results to avoid returning nothing."""
        raise NotImplementedError

    def is_live(self) -> bool:
        return False
