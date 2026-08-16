"""
HeuristicProvider: the default, zero-dependency 'intelligence' backend.

This is NOT a claim to be as capable as a real LLM. It is a genuinely
dynamic, topic-agnostic implementation that runs anywhere with no API key
and no internet: it extracts the topic phrase out of *whatever question it
is given* and parameterizes a fixed set of enterprise research angles with
it, rather than being hard-coded to any single topic/industry.

This is what actually executes in this sandbox demo. AnthropicProvider /
OpenAIProvider (same directory) are complete, correct implementations that
produce materially better decomposition and synthesis (real natural-language
reasoning instead of templates) -- swap LLM_PROVIDER + supply an API key to
use them; the rest of the pipeline does not change.
"""
import re
from typing import List, Dict

from app.providers.llm.base import LLMProvider

# A fixed taxonomy of research angles. This mirrors the example decomposition
# given in the assignment brief itself, generalized to any topic phrase.
_ANGLE_TEMPLATES = [
    ("adoption", "Which {topic} solutions or approaches are currently being adopted, and by whom?"),
    ("process_impact", "Which specific processes or operations are affected by {topic}?"),
    ("benefits", "What measurable benefits or outcomes have been reported for {topic}?"),
    ("adopters", "Which companies or industries are adopting {topic}?"),
    ("barriers", "What implementation barriers or challenges exist for {topic}?"),
    ("risks", "What risks or downsides are associated with {topic}?"),
    ("contradicting_evidence", "What evidence contradicts the claimed benefits of {topic}?"),
    ("maturity", "What is the current maturity level of {topic}?"),
    ("future_outlook", "What future developments are expected for {topic}?"),
]

_STOPWORD_PREFIXES = [
    r"^what\s+ai\s+technologies\s+are\s+", r"^what\s+are\s+the\s+", r"^what\s+",
    r"^which\s+", r"^how\s+is\s+", r"^how\s+are\s+", r"^how\s+", r"^why\s+is\s+",
]
_TRAILING_TRIM = [r"\?+$", r"\.$"]


def extract_topic(question: str) -> str:
    """Turn an arbitrary question into a short topic noun-phrase.
    Deliberately simple/regex-based (no model download required) -- see
    docs/architecture.md for the tradeoff and the LLM-backed upgrade path."""
    q = question.strip()
    for pat in _TRAILING_TRIM:
        q = re.sub(pat, "", q).strip()
    lowered = q.lower()
    for pat in _STOPWORD_PREFIXES:
        m = re.match(pat, lowered)
        if m:
            q = q[m.end():]
            break
    # Strip a small set of generic leading/trailing filler verbs.
    q = re.sub(r"^(changing|transforming|impacting|affecting|reshaping)\s+", "", q, flags=re.I)
    q = re.sub(r"\s+(changing|transforming|impacting|affecting|reshaping)$", "", q, flags=re.I)
    q = q.strip(" ?.")
    return q if q else question.strip(" ?.")


class HeuristicProvider(LLMProvider):
    name = "heuristic"

    def decompose_question(self, question: str) -> List[Dict]:
        topic = extract_topic(question)
        out = []
        for focus_area, template in _ANGLE_TEMPLATES:
            out.append({"text": template.format(topic=topic), "focus_area": focus_area})
        return out

    def summarize_for_synthesis(self, sub_question: str, claim_statements: List[str]) -> str:
        if not claim_statements:
            return (f"No sufficiently corroborated evidence was collected for '{sub_question}' "
                     f"in the current knowledge base. This is reported as an evidence gap rather "
                     f"than a conclusion.")
        lead = claim_statements[0]
        rest = claim_statements[1:3]
        para = f"Regarding '{sub_question}', the collected evidence indicates: {lead}"
        if rest:
            para += " Additional evidence in this area: " + " ".join(rest)
        return para
