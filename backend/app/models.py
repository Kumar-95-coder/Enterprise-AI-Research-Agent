"""
Data model.

Tables map directly onto the assignment's required entities:
research_jobs, research_questions(=job.question)+research_subquestions,
research_plans, sources, findings(=evidence), claims, entities,
relationships, contradictions, conclusions, citations, research_runs.

`documents` is intentionally merged into `sources` in this implementation:
each source maps 1:1 to one retrieved document/page. A production system
ingesting multi-page PDFs or multi-section reports would split a `documents`
table back out (one source -> many document chunks); see docs/data-model.md.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean, ForeignKey, DateTime,
    JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> datetime:
    return datetime.utcnow()


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id = Column(String, primary_key=True, default=gen_id)
    question = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="CREATED", index=True)
    config = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    overall_confidence = Column(Float, nullable=True)
    source_count = Column(Integer, default=0)
    new_source_count = Column(Integer, default=0)
    reused_source_count = Column(Integer, default=0)
    finding_count = Column(Integer, default=0)
    claim_count = Column(Integer, default=0)
    contradiction_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    sub_questions = relationship("SubQuestion", back_populates="job", cascade="all, delete-orphan")
    plan = relationship("ResearchPlan", back_populates="job", uselist=False, cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="job", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="job", cascade="all, delete-orphan")
    contradictions = relationship("Contradiction", back_populates="job", cascade="all, delete-orphan")
    conclusions = relationship("Conclusion", back_populates="job", cascade="all, delete-orphan")
    runs = relationship("ResearchRun", back_populates="job", cascade="all, delete-orphan")
    job_sources = relationship("JobSource", back_populates="job", cascade="all, delete-orphan")

    @property
    def duration_seconds(self):
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class SubQuestion(Base):
    __tablename__ = "research_subquestions"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    focus_area = Column(String, nullable=False)  # e.g. adoption, benefits, risks, maturity...
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="sub_questions")


class ResearchPlan(Base):
    __tablename__ = "research_plans"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), unique=True, nullable=False)
    search_strategies = Column(JSON, default=list)   # list of expanded search queries
    source_categories = Column(JSON, default=list)   # preferred source types
    evidence_requirements = Column(Text, default="")
    objectives = Column(Text, default="")
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="plan")


class Source(Base):
    """Global, deduplicated source table -- reused across research jobs."""
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=gen_id)
    url = Column(String, nullable=False, unique=True, index=True)
    normalized_url = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False)
    publisher = Column(String, nullable=True)
    author = Column(String, nullable=True)
    publication_date = Column(String, nullable=True)
    retrieval_date = Column(DateTime, default=now)
    source_type = Column(String, nullable=False, default="web")
    content = Column(Text, nullable=False, default="")       # paraphrased extracted content
    content_hash = Column(String, nullable=False, index=True)
    quality_score = Column(Float, default=0.5)
    relevant_passages = Column(JSON, default=list)
    citation_metadata = Column(JSON, default=dict)
    first_discovered_by_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=True)
    created_at = Column(DateTime, default=now)

    findings = relationship("Finding", back_populates="source")
    job_links = relationship("JobSource", back_populates="source")

    __table_args__ = (Index("ix_sources_hash", "content_hash"),)


class JobSource(Base):
    """Join table: which jobs used which sources, and whether the source was
    newly retrieved for that job or reused from the existing knowledge base."""
    __tablename__ = "job_sources"

    id = Column(String, primary_key=True, default=gen_id)
    job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False, index=True)
    search_query = Column(String, nullable=True)
    is_new_for_job = Column(Boolean, default=True)  # False => reused prior knowledge
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="job_sources")
    source = relationship("Source", back_populates="job_links")

    __table_args__ = (UniqueConstraint("job_id", "source_id", name="uq_job_source"),)


class Finding(Base):
    """A single extracted evidence passage (a 'finding'/'evidence' record)."""
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    sub_question_id = Column(String, ForeignKey("research_subquestions.id"), nullable=True, index=True)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("claims.id"), nullable=True, index=True)
    evidence_text = Column(Text, nullable=False)
    context = Column(Text, default="")
    category = Column(String, nullable=False, default="General")
    confidence = Column(Float, default=0.5)
    evidence_strength = Column(String, default="moderate")  # strong | moderate | weak
    polarity = Column(Float, default=0.0)  # heuristic signed polarity, used for contradiction detection
    date_hint = Column(String, nullable=True)
    entities = Column(JSON, default=list)  # list of entity ids surfaced in this passage
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="findings")
    source = relationship("Source", back_populates="findings")
    sub_question = relationship("SubQuestion")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    sub_question_id = Column(String, ForeignKey("research_subquestions.id"), nullable=True, index=True)
    statement = Column(Text, nullable=False)
    category = Column(String, default="General")
    supporting_count = Column(Integer, default=0)
    contradicting_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    distinct_source_count = Column(Integer, default=0)
    distinct_publisher_count = Column(Integer, default=0)
    agreement_level = Column(String, default="unclear")  # strong_agreement | mixed | disputed | single_source
    confidence = Column(Float, default=0.5)
    evidence_strength = Column(String, default="moderate")
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="claims")
    findings = relationship("Finding", backref="claim", foreign_keys=[Finding.claim_id])


class ClaimFinding(Base):
    """Explicit stance of a finding relative to a claim (supporting/contradicting/neutral).
    Kept separate from Finding.claim_id so a finding's *primary* claim and its
    stance record can be queried/audited independently."""
    __tablename__ = "claim_findings"

    id = Column(String, primary_key=True, default=gen_id)
    claim_id = Column(String, ForeignKey("claims.id"), nullable=False, index=True)
    finding_id = Column(String, ForeignKey("findings.id"), nullable=False, index=True)
    stance = Column(String, nullable=False, default="supporting")  # supporting | contradicting | neutral

    __table_args__ = (UniqueConstraint("claim_id", "finding_id", name="uq_claim_finding"),)


class Contradiction(Base):
    __tablename__ = "contradictions"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    claim_a_id = Column(String, ForeignKey("claims.id"), nullable=False)
    claim_b_id = Column(String, ForeignKey("claims.id"), nullable=True)
    finding_a_id = Column(String, ForeignKey("findings.id"), nullable=False)
    finding_b_id = Column(String, ForeignKey("findings.id"), nullable=False)
    source_a_id = Column(String, ForeignKey("sources.id"), nullable=False)
    source_b_id = Column(String, ForeignKey("sources.id"), nullable=False)
    contradiction_type = Column(String, nullable=False, default="empirical_evidence_disagreement")
    explanation = Column(Text, nullable=False)
    confidence = Column(Float, default=0.5)
    possible_reason = Column(Text, default="")
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="contradictions")


class Entity(Base):
    """Global, deduplicated by (name, entity_type)."""
    __tablename__ = "entities"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=now)

    __table_args__ = (UniqueConstraint("name", "entity_type", name="uq_entity_name_type"),)


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    source_entity_id = Column(String, ForeignKey("entities.id"), nullable=False, index=True)
    relation_type = Column(String, nullable=False)  # uses | affects | improves | reports | adopts ...
    target_entity_id = Column(String, ForeignKey("entities.id"), nullable=False, index=True)
    finding_id = Column(String, ForeignKey("findings.id"), nullable=True)  # provenance
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=now)


class Conclusion(Base):
    __tablename__ = "conclusions"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    sub_question_id = Column(String, ForeignKey("research_subquestions.id"), nullable=True, index=True)
    statement = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="emerging")  # established | emerging | conflicting | gap
    confidence = Column(Float, default=0.5)
    supporting_claim_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=now)

    job = relationship("ResearchJob", back_populates="conclusions")


class Citation(Base):
    """Materialized citation records generated at report-validation time --
    one row per (conclusion, source) pair actually used in the final report."""
    __tablename__ = "citations"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    conclusion_id = Column(String, ForeignKey("conclusions.id"), nullable=False)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url = Column(String, nullable=False)
    accessed_date = Column(DateTime, default=now)


class ResearchRun(Base):
    """Observability / audit log of each pipeline stage transition."""
    __tablename__ = "research_runs"

    id = Column(String, primary_key=True, default=gen_id)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=False, index=True)
    stage = Column(String, nullable=False)
    status = Column(String, nullable=False, default="started")  # started | completed | failed
    detail = Column(JSON, default=dict)
    started_at = Column(DateTime, default=now)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    job = relationship("ResearchJob", back_populates="runs")


class KnowledgeVector(Base):
    """Backing store for semantic search: one row per indexed text object
    (finding / claim / source) so the knowledge base can be searched
    independently of any single research job."""
    __tablename__ = "knowledge_vectors"

    id = Column(String, primary_key=True, default=gen_id)
    object_type = Column(String, nullable=False)  # finding | claim | source
    object_id = Column(String, nullable=False, index=True)
    text = Column(Text, nullable=False)
    research_job_id = Column(String, ForeignKey("research_jobs.id"), nullable=True)
    created_at = Column(DateTime, default=now)

    __table_args__ = (UniqueConstraint("object_type", "object_id", name="uq_vector_object"),)
