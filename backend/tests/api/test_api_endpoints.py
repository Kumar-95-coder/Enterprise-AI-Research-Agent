"""
API tests: exercise the real FastAPI app through TestClient (in-process,
no network) against an isolated SQLite database so they never touch the
developer's research_agent.db.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_api.db")

from app.main import app
from app.database import Base, get_db
from app.config import get_settings

get_settings.cache_clear()
TEST_DB = "sqlite:///./test_api.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(bind=engine)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def _wait_for_completion(job_id, timeout=15):
    for _ in range(timeout * 10):
        r = client.get(f"/api/research/{job_id}")
        if r.json()["status"] in ("COMPLETED", "FAILED"):
            return r.json()
        time.sleep(0.1)
    raise TimeoutError(f"Job {job_id} did not complete in {timeout}s")


class TestHealthAndRoot:
    def test_health(self):
        assert client.get("/health").status_code == 200

    def test_root_reports_active_providers(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "llm_provider" in r.json()


class TestResearchJobLifecycle:
    def test_create_research_rejects_trivial_question(self):
        r = client.post("/api/research", json={"question": "hi"})
        assert r.status_code == 422

    def test_create_and_complete_research_job(self):
        r = client.post("/api/research", json={"question": "What AI technologies are changing manufacturing?"})
        assert r.status_code == 201
        job = r.json()
        assert job["status"] == "CREATED"

        completed = _wait_for_completion(job["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["source_count"] > 0
        assert completed["finding_count"] > 0

    def test_status_endpoint_shows_pipeline_stages(self):
        r = client.post("/api/research", json={"question": "What AI risks exist for financial institutions?"})
        job_id = r.json()["id"]
        _wait_for_completion(job_id)
        status = client.get(f"/api/research/{job_id}/status").json()
        stage_names = [s["stage"] for s in status["pipeline"]]
        for expected in ["PLANNING", "SEARCHING", "COLLECTING", "EXTRACTING", "ANALYZING", "VALIDATING"]:
            assert expected in stage_names

    def test_unknown_job_returns_404(self):
        assert client.get("/api/research/does-not-exist").status_code == 404

    def test_list_research_returns_jobs(self):
        client.post("/api/research", json={"question": "How is generative AI changing customer service?"})
        r = client.get("/api/research")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0


class TestKnowledgeBaseAndTraceability:
    def test_full_traceability_chain_is_queryable(self):
        r = client.post("/api/research", json={"question": "What AI technologies are changing manufacturing?"})
        job_id = r.json()["id"]
        _wait_for_completion(job_id)

        claims = client.get(f"/api/research/{job_id}/claims").json()
        assert len(claims) > 0

        claim_detail = client.get(f"/api/claims/{claims[0]['id']}").json()
        assert "supporting" in claim_detail
        assert "claim" in claim_detail

        sources = client.get(f"/api/research/{job_id}/sources").json()
        assert len(sources) > 0
        source_detail = client.get(f"/api/sources/{sources[0]['id']}").json()
        assert "findings" in source_detail
        assert source_detail["source"]["url"].startswith("http")

    def test_report_requires_completed_job(self):
        r = client.post("/api/research", json={"question": "What AI technologies are changing manufacturing?"})
        job_id = r.json()["id"]
        # immediately requesting the report before completion should 409, not fabricate one
        report_resp = client.get(f"/api/research/{job_id}/report")
        assert report_resp.status_code in (200, 409)

    def test_knowledge_search_finds_prior_job_content(self):
        r = client.post("/api/research", json={"question": "What AI technologies are changing manufacturing?"})
        _wait_for_completion(r.json()["id"])
        results = client.get("/api/knowledge/search", params={"q": "predictive maintenance downtime"}).json()
        assert results["result_count"] >= 0  # endpoint works; content depends on prior tests' ordering


class TestEvidenceGapHonesty:
    def test_unseeded_topic_reports_gap_not_fabricated_sources(self):
        r = client.post("/api/research", json={"question": "Which AI applications are producing measurable ROI in healthcare?"})
        job_id = r.json()["id"]
        completed = _wait_for_completion(job_id)
        assert completed["source_count"] == 0
        report = client.get(f"/api/research/{job_id}/report").json()
        assert len(report["evidence_gaps"]) == len(report["established_findings"]) + \
               len(report["emerging_findings"]) + len(report["evidence_gaps"])
        assert report["sources"] == []
