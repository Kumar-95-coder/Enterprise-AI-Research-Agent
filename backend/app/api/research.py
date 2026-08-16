from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.database import get_db
from app.models import (
    ResearchJob, SubQuestion, ResearchPlan, Source, JobSource, Finding, Claim,
    Contradiction, Conclusion, ResearchRun, Citation,
)
from app import schemas
from app.pipeline.orchestrator import run_research_pipeline
from app.config import get_settings

router = APIRouter(prefix="/api/research", tags=["research"])


def _dispatch_pipeline(job_id: str, background_tasks: BackgroundTasks):
    """BACKGROUND_MODE=celery routes through the Celery reference
    implementation (app/workers/celery_tasks.py) for horizontal scaling;
    the default 'asyncio' mode runs in-process via FastAPI BackgroundTasks.
    Falls back to BackgroundTasks if Celery/Redis isn't actually available,
    rather than failing the request -- see docs/scaling.md."""
    settings = get_settings()
    if settings.BACKGROUND_MODE == "celery":
        try:
            from app.workers.celery_tasks import run_research_pipeline_task
            if run_research_pipeline_task is not None:
                run_research_pipeline_task.delay(job_id)
                return
        except Exception:
            pass  # Redis/Celery not reachable -- degrade to in-process background task
    background_tasks.add_task(run_research_pipeline, job_id)


def _job_or_404(db: Session, job_id: str) -> ResearchJob:
    job = db.get(ResearchJob, job_id)
    if not job:
        raise HTTPException(404, f"Research job {job_id} not found")
    return job


@router.post("", response_model=schemas.ResearchJobOut, status_code=201)
def create_research(payload: schemas.ResearchJobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not payload.question or len(payload.question.strip()) < 5:
        raise HTTPException(422, "question must be a non-trivial research question")
    job = ResearchJob(question=payload.question.strip(), status="CREATED", config=payload.config or {})
    db.add(job)
    db.commit()
    db.refresh(job)
    _dispatch_pipeline(job.id, background_tasks)
    return job


@router.get("", response_model=list[schemas.ResearchJobOut])
def list_research(limit: int = 50, db: Session = Depends(get_db)):
    jobs = db.execute(select(ResearchJob).order_by(desc(ResearchJob.created_at)).limit(limit)).scalars().all()
    return jobs


@router.get("/{job_id}", response_model=schemas.ResearchJobOut)
def get_research(job_id: str, db: Session = Depends(get_db)):
    return _job_or_404(db, job_id)


@router.get("/{job_id}/status")
def get_status(job_id: str, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    runs = db.execute(select(ResearchRun).where(ResearchRun.research_job_id == job_id)
                       .order_by(ResearchRun.started_at)).scalars().all()
    return {
        "id": job.id, "status": job.status, "error_message": job.error_message,
        "pipeline": [schemas.ResearchRunOut.model_validate(r).model_dump() for r in runs],
        "source_count": job.source_count, "finding_count": job.finding_count,
        "claim_count": job.claim_count, "contradiction_count": job.contradiction_count,
    }


@router.get("/{job_id}/questions")
def get_questions(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    subs = db.execute(select(SubQuestion).where(SubQuestion.research_job_id == job_id)
                       .order_by(SubQuestion.order_index)).scalars().all()
    plan = db.execute(select(ResearchPlan).where(ResearchPlan.research_job_id == job_id)).scalar_one_or_none()
    return {
        "sub_questions": [schemas.SubQuestionOut.model_validate(s).model_dump() for s in subs],
        "plan": schemas.ResearchPlanOut.model_validate(plan).model_dump() if plan else None,
    }


@router.get("/{job_id}/sources")
def get_sources(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    rows = db.execute(
        select(Source, JobSource.is_new_for_job)
        .join(JobSource, JobSource.source_id == Source.id)
        .where(JobSource.job_id == job_id)
    ).all()
    out = []
    for source, is_new in rows:
        d = schemas.SourceOut.model_validate(source).model_dump()
        d["is_new_for_this_job"] = is_new
        out.append(d)
    return out


@router.get("/{job_id}/findings", response_model=list[schemas.FindingOut])
def get_findings(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    return db.execute(select(Finding).where(Finding.research_job_id == job_id)).scalars().all()


@router.get("/{job_id}/claims", response_model=list[schemas.ClaimOut])
def get_claims(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    return db.execute(select(Claim).where(Claim.research_job_id == job_id)).scalars().all()


@router.get("/{job_id}/contradictions", response_model=list[schemas.ContradictionOut])
def get_contradictions(job_id: str, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    return db.execute(select(Contradiction).where(Contradiction.research_job_id == job_id)).scalars().all()


@router.get("/{job_id}/report")
def get_report(job_id: str, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status not in ("COMPLETED", "FAILED"):
        raise HTTPException(409, f"Research job is still {job.status}; report not ready yet")

    subs = db.execute(select(SubQuestion).where(SubQuestion.research_job_id == job_id)
                       .order_by(SubQuestion.order_index)).scalars().all()
    conclusions = {c.sub_question_id: c for c in
                   db.execute(select(Conclusion).where(Conclusion.research_job_id == job_id)).scalars()}
    contradictions = db.execute(select(Contradiction).where(Contradiction.research_job_id == job_id)).scalars().all()
    sources = db.execute(
        select(Source).join(JobSource, JobSource.source_id == Source.id).where(JobSource.job_id == job_id)
    ).scalars().all()
    citations = db.execute(select(Citation).where(Citation.research_job_id == job_id)).scalars().all()

    established, emerging, conflicting, gaps = [], [], [], []
    for sq in subs:
        c = conclusions.get(sq.id)
        if not c:
            continue
        bucket = {"established": established, "emerging": emerging,
                  "conflicting": conflicting, "gap": gaps}[c.status]
        bucket.append({"sub_question": sq.text, "statement": c.statement, "confidence": c.confidence,
                        "conclusion_id": c.id, "supporting_claim_ids": c.supporting_claim_ids})

    exec_summary = (
        f"Research on \"{job.question}\" examined {len(subs)} sub-questions using "
        f"{job.source_count} sources ({job.new_source_count} newly retrieved, "
        f"{job.reused_source_count} reused from the existing knowledge base), producing "
        f"{job.finding_count} extracted findings, {job.claim_count} claims, and "
        f"{job.contradiction_count} detected contradictions. "
        f"{len(established)} conclusions are well-established, {len(emerging)} are emerging, "
        f"{len(conflicting)} involve conflicting evidence, and {len(gaps)} sub-questions "
        f"remain evidence gaps. Overall evidence-based confidence: "
        f"{job.overall_confidence if job.overall_confidence is not None else 'n/a'}."
    )

    return {
        "job_id": job.id,
        "research_question": job.question,
        "status": job.status,
        "executive_summary": exec_summary,
        "methodology": (
            "Question decomposed into sub-questions across a fixed set of enterprise research "
            "angles (adoption, process impact, benefits, adopters, barriers, risks, contradicting "
            "evidence, maturity, future outlook). Each angle drove expanded search queries against "
            "the configured search provider. Retrieved sources were deduplicated against the global "
            "knowledge base, evidence passages were extracted and classified, clustered into claims, "
            "compared across sources, and checked for contradictions before conclusions were "
            "synthesized and validated for traceability."
        ),
        "established_findings": established,
        "emerging_findings": emerging,
        "conflicting_evidence": conflicting,
        "evidence_gaps": gaps,
        "contradictions": [schemas.ContradictionOut.model_validate(c).model_dump() for c in contradictions],
        "sources": [schemas.SourceOut.model_validate(s).model_dump() for s in sources],
        "citation_count": len(citations),
        "overall_confidence": job.overall_confidence,
    }
