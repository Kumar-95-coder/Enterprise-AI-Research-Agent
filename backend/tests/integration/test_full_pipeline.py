"""
Integration test: exercises the full
Question -> Search -> Retrieval -> Processing -> Storage -> Analysis -> Report
flow directly against the pipeline orchestrator and a real (file-based,
throwaway) SQLite database -- not mocked.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import os as _os
_os.environ["DATABASE_URL"] = "sqlite:///./test_integration.db"

from sqlalchemy import select

from app.database import Base, engine, SessionLocal
from app import models
from app.pipeline.orchestrator import run_research_pipeline
from app.models import ResearchJob, Source, Finding, Claim, Contradiction, Conclusion, Citation, ResearchRun


def _reset_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


def test_full_pipeline_end_to_end_with_real_seeded_evidence():
    Session = _reset_schema()
    db = Session()
    job = ResearchJob(question="What AI technologies are changing manufacturing?", status="CREATED")
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    # Runs synchronously here (no BackgroundTasks involved) so assertions
    # below observe the fully-settled end state.
    run_research_pipeline(job_id)

    db = Session()
    job = db.get(ResearchJob, job_id)

    assert job.status == "COMPLETED"
    assert job.error_message is None

    # Search -> Retrieval
    sources = db.execute(select(Source)).scalars().all()
    assert len(sources) > 0
    assert all(s.url.startswith("http") for s in sources)
    assert all(s.content_hash for s in sources)

    # Processing -> extraction
    findings = db.execute(select(Finding).where(Finding.research_job_id == job_id)).scalars().all()
    assert len(findings) > 0
    assert all(f.source_id in {s.id for s in sources} for f in findings)

    # Storage -> claims, with traceable finding linkage
    claims = db.execute(select(Claim).where(Claim.research_job_id == job_id)).scalars().all()
    assert len(claims) > 0

    # Analysis -> at least one contradiction expected given the seeded
    # positive-ROI vs skeptical-ROI evidence in the corpus
    contradictions = db.execute(select(Contradiction).where(Contradiction.research_job_id == job_id)).scalars().all()
    assert len(contradictions) > 0
    for c in contradictions:
        assert c.source_a_id != c.source_b_id
        assert c.contradiction_type in {
            "different_time_period", "different_geography", "forecast_disagreement",
            "empirical_evidence_disagreement",
        }

    # Report -> conclusions + citations, and every conclusion is traceable
    conclusions = db.execute(select(Conclusion).where(Conclusion.research_job_id == job_id)).scalars().all()
    assert len(conclusions) == 9  # one per decomposed sub-question
    non_gap = [c for c in conclusions if c.status != "gap"]
    assert len(non_gap) > 0
    for c in non_gap:
        assert len(c.supporting_claim_ids) > 0

    citations = db.execute(select(Citation).where(Citation.research_job_id == job_id)).scalars().all()
    assert len(citations) > 0
    for cit in citations:
        assert cit.url.startswith("http")

    # Observability -> every pipeline stage logged
    runs = db.execute(select(ResearchRun).where(ResearchRun.research_job_id == job_id)).scalars().all()
    stages = {r.stage for r in runs}
    assert {"PLANNING", "SEARCHING", "COLLECTING", "PROCESSING", "EXTRACTING",
            "COMPARING", "ANALYZING", "STORING", "SYNTHESIZING", "VALIDATING"}.issubset(stages)
    assert all(r.status == "completed" for r in runs)

    db.close()


def test_second_related_job_reuses_knowledge_base():
    Session = _reset_schema()
    db = Session()
    job1 = ResearchJob(question="What AI technologies are changing manufacturing?", status="CREATED")
    db.add(job1)
    db.commit()
    job1_id = job1.id
    db.close()
    run_research_pipeline(job1_id)

    db = Session()
    job2 = ResearchJob(question="How is machine learning reducing equipment downtime?", status="CREATED")
    db.add(job2)
    db.commit()
    job2_id = job2.id
    db.close()
    run_research_pipeline(job2_id)

    db = Session()
    job1 = db.get(ResearchJob, job1_id)
    job2 = db.get(ResearchJob, job2_id)
    assert job2.status == "COMPLETED"
    assert job2.reused_source_count > 0, "job 2 should reuse at least one source discovered by job 1"

    total_sources = db.execute(select(Source)).scalars().all()
    # global source count should be less than the sum of both jobs' source
    # counts, because of deduplication/reuse
    assert len(total_sources) < job1.source_count + job2.source_count

    db.close()
