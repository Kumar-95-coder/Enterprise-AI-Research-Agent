"""
Research planning: builds an explicit plan (search strategies, source
categories, evidence requirements) BEFORE any search executes, so the
system never degrades to "one generic web search."

Query expansion is dynamic: it derives targeted queries from each
sub-question's own words plus its focus_area, rather than a fixed per-topic
query list.
"""
from sqlalchemy.orm import Session

from app.models import ResearchPlan, SubQuestion
from app.providers.llm.heuristic_provider import extract_topic

_PREFERRED_SOURCE_CATEGORIES = [
    "industry_report", "academic", "government", "news_business", "technical_documentation",
]

_FOCUS_AREA_QUALIFIERS = {
    "adoption": ["adoption", "deployment"],
    "process_impact": ["operations impact", "process automation"],
    "benefits": ["ROI", "measurable results", "case study"],
    "adopters": ["companies", "enterprise adoption"],
    "barriers": ["implementation challenges", "barriers"],
    "risks": ["risks", "limitations"],
    "contradicting_evidence": ["criticism", "failure", "skepticism"],
    "maturity": ["maturity", "market readiness"],
    "future_outlook": ["future trends", "forecast"],
}


def expand_queries(topic: str, sub_questions: list[SubQuestion]) -> list[str]:
    queries = [topic]
    for sq in sub_questions:
        qualifiers = _FOCUS_AREA_QUALIFIERS.get(sq.focus_area, [sq.focus_area])
        for q in qualifiers:
            queries.append(f"{topic} {q}")
    # de-dupe while preserving order
    seen, out = set(), []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


def build_plan(db: Session, job_id: str, question: str, sub_questions: list[SubQuestion]) -> ResearchPlan:
    topic = extract_topic(question)
    strategies = expand_queries(topic, sub_questions)
    plan = ResearchPlan(
        research_job_id=job_id,
        search_strategies=strategies,
        source_categories=_PREFERRED_SOURCE_CATEGORIES,
        evidence_requirements=(
            "Each sub-question requires at least one corroborated, attributable passage; "
            "prefer sources with an explicit publisher/date; flag single-source claims as "
            "'emerging' rather than 'established'."
        ),
        objectives=f"Systematically investigate: {topic} across {len(sub_questions)} research angles.",
    )
    db.add(plan)
    db.flush()
    return plan
