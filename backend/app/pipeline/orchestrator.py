"""
Pipeline orchestrator.

Runs the full state machine end-to-end:
CREATED -> PLANNING -> SEARCHING -> COLLECTING -> PROCESSING -> EXTRACTING
-> COMPARING -> ANALYZING -> STORING -> SYNTHESIZING -> VALIDATING ->
COMPLETED (or FAILED at any stage; the triggering exception is preserved on
the job, and never allowed to crash the host process).

Invoked as a FastAPI BackgroundTask, so POST /api/research returns
immediately with a job id and the caller polls GET .../status -- this is
the "background processing rather than blocking one HTTP request"
requirement in this codebase's default (single-process) configuration. See
app/workers/celery_tasks.py for the equivalent task wired for horizontal
scaling via Celery + Redis in production (reference implementation, not
started in this sandbox).
"""
import logging
import time
import datetime as dt
from contextlib import contextmanager

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ResearchJob, ResearchRun, Source, Finding, KnowledgeVector
from app.pipeline import decomposition, planning, retrieval, extraction, entities, analysis, synthesis, validation

logger = logging.getLogger("research_agent.orchestrator")


@contextmanager
def _stage(db: Session, job: ResearchJob, stage_name: str, detail: dict = None):
    job.status = stage_name
    db.add(job)
    db.commit()
    run = ResearchRun(research_job_id=job.id, stage=stage_name, status="started")
    db.add(run)
    db.commit()
    t0 = time.time()
    try:
        yield
        run.status = "completed"
        run.detail = detail or {}
    except Exception as e:
        run.status = "failed"
        run.detail = {"error": str(e)}
        raise
    finally:
        run.duration_ms = int((time.time() - t0) * 1000)
        db.add(run)
        db.commit()


def run_research_pipeline(job_id: str):
    db = SessionLocal()
    try:
        job = db.get(ResearchJob, job_id)
        if job is None:
            logger.error(f"Job {job_id} not found")
            return
        job.started_at = dt.datetime.utcnow()
        db.commit()

        try:
            with _stage(db, job, "PLANNING"):
                sub_questions = decomposition.decompose(db, job.id, job.question)
                db.commit()
                plan = planning.build_plan(db, job.id, job.question, sub_questions)
                db.commit()

            with _stage(db, job, "SEARCHING"):
                queries = list(plan.search_strategies)

            with _stage(db, job, "COLLECTING"):
                collect_result = retrieval.discover_and_collect(db, job.id, queries)
                db.commit()
                job.new_source_count = collect_result["new"]
                job.reused_source_count = collect_result["reused"]
                job.source_count = collect_result["new"] + collect_result["reused"]
                db.commit()

            with _stage(db, job, "PROCESSING"):
                source_ids = collect_result["source_ids"]
                sources = (db.execute(select(Source).where(Source.id.in_(source_ids))).scalars().all()
                            if source_ids else [])

            with _stage(db, job, "EXTRACTING") as _:
                all_findings: list[Finding] = []
                for src in sources:
                    all_findings.extend(extraction.extract_findings_for_source(db, job.id, src, sub_questions))
                db.commit()
                job.finding_count = len(all_findings)

                claims = extraction.cluster_claims(db, job.id, all_findings)
                db.commit()
                job.claim_count = len(claims)

                ent_result = entities.extract_entities_and_relationships(db, job.id, all_findings)
                db.commit()

            with _stage(db, job, "COMPARING", detail=ent_result):
                pass  # aggregate comparison stats are computed inside cluster_claims (extraction.py)

            with _stage(db, job, "ANALYZING"):
                contradictions = analysis.detect_contradictions(db, job.id, claims)
                db.commit()
                job.contradiction_count = len(contradictions)

            with _stage(db, job, "STORING"):
                _index_knowledge_vectors(db, job.id, all_findings, claims, sources)
                db.commit()

            with _stage(db, job, "SYNTHESIZING"):
                synthesis.synthesize(db, job.id, sub_questions)
                db.commit()

            validation_result = None
            with _stage(db, job, "VALIDATING"):
                validation_result = validation.validate_and_finalize(db, job.id)
                db.commit()

            job.status = "COMPLETED"
            job.completed_at = dt.datetime.utcnow()
            db.commit()
            logger.info(f"Job {job_id} COMPLETED: {validation_result}")

        except Exception:
            logger.exception(f"Research job {job_id} failed")
            db.rollback()
            job = db.get(ResearchJob, job_id)
            job.status = "FAILED"
            job.error_message = _safe_error_message()
            db.commit()
    finally:
        db.close()


def _safe_error_message() -> str:
    import traceback
    return traceback.format_exc(limit=3)


def _index_knowledge_vectors(db: Session, job_id: str, findings, claims, sources):
    def _upsert(object_type, object_id, text):
        exists = db.execute(select(KnowledgeVector).where(
            KnowledgeVector.object_type == object_type, KnowledgeVector.object_id == object_id
        )).scalar_one_or_none()
        if not exists:
            db.add(KnowledgeVector(object_type=object_type, object_id=object_id, text=text, research_job_id=job_id))

    for f in findings:
        _upsert("finding", f.id, f.evidence_text)
    for c in claims:
        _upsert("claim", c.id, c.statement)
    for s in sources:
        _upsert("source", s.id, f"{s.title} {s.content}")
