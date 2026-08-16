"""
Pipeline stage: traceability validation + citation materialization.

Walks Conclusion -> Claim -> Finding -> Source -> URL for every
non-evidence-gap conclusion and records any broken link as an issue rather
than silently completing. Also computes overall_confidence from the actual
evidence graph (not self-reported by any LLM) and writes materialized
Citation rows, so "citations are preserved" is a queryable, persisted fact
rather than something assembled ad hoc only in a report view.
"""
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Conclusion, Claim, ClaimFinding, Finding, Source, Citation, ResearchJob


def validate_and_finalize(db: Session, job_id: str) -> dict:
    conclusions = db.execute(select(Conclusion).where(Conclusion.research_job_id == job_id)).scalars().all()
    issues = []
    citation_count = 0
    confidences = []

    for conclusion in conclusions:
        if conclusion.status == "gap":
            continue
        claim_ids = conclusion.supporting_claim_ids or []
        if not claim_ids:
            issues.append(f"Conclusion {conclusion.id} has no linked claims despite non-gap status.")
            continue
        for claim_id in claim_ids:
            claim = db.get(Claim, claim_id)
            if claim is None:
                issues.append(f"Claim {claim_id} referenced by conclusion {conclusion.id} not found.")
                continue
            confidences.append(claim.confidence)
            findings = db.execute(
                select(Finding).join(ClaimFinding, ClaimFinding.finding_id == Finding.id)
                .where(ClaimFinding.claim_id == claim.id)
            ).scalars().all()
            if not findings:
                issues.append(f"Claim {claim.id} has no linked findings.")
                continue
            for finding in findings:
                source = db.get(Source, finding.source_id)
                if source is None or not source.url:
                    issues.append(f"Finding {finding.id} has no traceable source URL.")
                    continue
                exists = db.execute(
                    select(Citation).where(Citation.conclusion_id == conclusion.id, Citation.source_id == source.id)
                ).scalar_one_or_none()
                if not exists:
                    db.add(Citation(research_job_id=job_id, conclusion_id=conclusion.id,
                                     source_id=source.id, url=source.url))
                    citation_count += 1

    overall_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None

    job = db.get(ResearchJob, job_id)
    job.overall_confidence = overall_confidence
    db.flush()

    return {"issues": issues, "citations_created": citation_count, "overall_confidence": overall_confidence}
