from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import Finding, Claim, ClaimFinding, Source, Contradiction
from app import schemas

findings_router = APIRouter(prefix="/api/findings", tags=["findings"])
claims_router = APIRouter(prefix="/api/claims", tags=["claims"])


@findings_router.get("/{finding_id}")
def get_finding_detail(finding_id: str, db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    source = db.get(Source, finding.source_id)
    return {
        "finding": schemas.FindingOut.model_validate(finding).model_dump(),
        "source": schemas.SourceOut.model_validate(source).model_dump() if source else None,
    }


@claims_router.get("/{claim_id}")
def get_claim_detail(claim_id: str, db: Session = Depends(get_db)):
    """The claim detail view required by the spec:
    Claim -> Supporting Evidence -> Supporting Sources
          -> Contradicting Evidence -> Contradicting Sources
          -> Confidence / Evidence Strength / Research Context
    """
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")

    links = db.execute(select(ClaimFinding).where(ClaimFinding.claim_id == claim_id)).scalars().all()

    def _bundle(stance: str):
        f_ids = [l.finding_id for l in links if l.stance == stance]
        findings = db.execute(select(Finding).where(Finding.id.in_(f_ids))).scalars().all() if f_ids else []
        source_ids = {f.source_id for f in findings}
        sources = db.execute(select(Source).where(Source.id.in_(source_ids))).scalars().all() if source_ids else []
        return {
            "evidence": [schemas.FindingOut.model_validate(f).model_dump() for f in findings],
            "sources": [schemas.SourceOut.model_validate(s).model_dump() for s in sources],
        }

    contradictions = db.execute(
        select(Contradiction).where((Contradiction.claim_a_id == claim_id) | (Contradiction.claim_b_id == claim_id))
    ).scalars().all()

    return {
        "claim": schemas.ClaimOut.model_validate(claim).model_dump(),
        "supporting": _bundle("supporting"),
        "contradicting": _bundle("contradicting"),
        "contradiction_records": [schemas.ContradictionOut.model_validate(c).model_dump() for c in contradictions],
    }
