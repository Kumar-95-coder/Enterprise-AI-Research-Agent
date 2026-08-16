"""
LLM provider interface.

Every 'intelligence' operation the pipeline needs is expressed here as a
method. Swapping LLM_PROVIDER in the environment swaps the implementation
underneath the pipeline without changing any pipeline code -- this is the
seam that satisfies the assignment's "what if this external service becomes
unavailable" resilience requirement.
"""
from abc import ABC, abstractmethod
from typing import List, Dict


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def decompose_question(self, question: str) -> List[Dict]:
        """Return a list of {'text': str, 'focus_area': str} sub-questions."""
        raise NotImplementedError

    @abstractmethod
    def summarize_for_synthesis(self, sub_question: str, claim_statements: List[str]) -> str:
        """Produce a short synthesis paragraph for one sub-question given its claims."""
        raise NotImplementedError

    def is_live(self) -> bool:
        """Whether this provider makes real network calls to a hosted model."""
        return False
