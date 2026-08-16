from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.database import get_db
from app.models import Source, Finding, Claim, ClaimFinding, Contradiction, Entity
from app import schemas

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/{source_id}")
def get_source_detail(source_id: str, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    findings = db.execute(select(Finding).where(Finding.source_id == source_id)).scalars().all()
    finding_ids = [f.id for f in findings]

    claim_ids = {f.claim_id for f in findings if f.claim_id}
    claims = db.execute(select(Claim).where(Claim.id.in_(claim_ids))).scalars().all() if claim_ids else []

    contradictions = db.execute(
        select(Contradiction).where(or_(Contradiction.source_a_id == source_id, Contradiction.source_b_id == source_id))
    ).scalars().all() if finding_ids else []

    entity_ids = set()
    for f in findings:
        entity_ids.update(f.entities or [])
    entities = db.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all() if entity_ids else []

    return {
        "source": schemas.SourceOut.model_validate(source).model_dump(),
        "extracted_passages": [f.evidence_text for f in findings],
        "findings": [schemas.FindingOut.model_validate(f).model_dump() for f in findings],
        "claims_derived": [schemas.ClaimOut.model_validate(c).model_dump() for c in claims],
        "contradictions_involving_source": [schemas.ContradictionOut.model_validate(c).model_dump() for c in contradictions],
        "entities_extracted": [schemas.EntityOut.model_validate(e).model_dump() for e in entities],
    }
