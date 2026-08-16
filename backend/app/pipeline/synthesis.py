"""
Pipeline stage: conclusion synthesis.

For each sub-question, aggregates its claims into one conclusion. The
natural-language synthesis paragraph comes from the configured
LLMProvider.summarize_for_synthesis() -- plugging in a real LLM materially
improves this stage's prose without touching anything else.

The *status* classification (established / emerging / conflicting / gap) is
evidence-driven, independent of which provider wrote the sentence -- this is
the "confidence should reflect the evidence rather than simply the LLM's
confidence" requirement made concrete.
"""
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import SubQuestion, Claim, Conclusion, Contradiction
from app.providers.llm import get_llm_provider


def synthesize(db: Session, job_id: str, sub_questions: list[SubQuestion]) -> list[Conclusion]:
    provider = get_llm_provider()

    contradicted_claim_ids = set()
    for c in db.execute(select(Contradiction).where(Contradiction.research_job_id == job_id)).scalars():
        contradicted_claim_ids.add(c.claim_a_id)
        contradicted_claim_ids.add(c.claim_b_id)

    conclusions = []
    for sq in sub_questions:
        claims = db.execute(select(Claim).where(Claim.sub_question_id == sq.id)).scalars().all()

        if not claims:
            status, confidence = "gap", 0.0
            statement = provider.summarize_for_synthesis(sq.text, [])
        else:
            has_contradiction = any(c.id in contradicted_claim_ids for c in claims)
            strong = [c for c in claims if c.distinct_source_count >= 2 and c.evidence_strength == "strong"]
            statement = provider.summarize_for_synthesis(sq.text, [c.statement for c in claims[:4]])
            confidence = round(sum(c.confidence for c in claims) / len(claims), 2)
            status = "conflicting" if has_contradiction else ("established" if strong else "emerging")

        conclusion = Conclusion(
            research_job_id=job_id, sub_question_id=sq.id,
            statement=statement, status=status, confidence=confidence,
            supporting_claim_ids=[c.id for c in claims],
        )
        db.add(conclusion)
        conclusions.append(conclusion)

    db.flush()
    return conclusions
