from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ResearchJobCreate(BaseModel):
    question: str
    config: Optional[Dict[str, Any]] = None


class ResearchJobOut(ORMModel):
    id: str
    question: str
    status: str
    error_message: Optional[str] = None
    overall_confidence: Optional[float] = None
    source_count: int
    new_source_count: int
    reused_source_count: int
    finding_count: int
    claim_count: int
    contradiction_count: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class SubQuestionOut(ORMModel):
    id: str
    text: str
    focus_area: str
    order_index: int


class ResearchPlanOut(ORMModel):
    search_strategies: List[str]
    source_categories: List[str]
    evidence_requirements: str
    objectives: str


class SourceOut(ORMModel):
    id: str
    url: str
    title: str
    publisher: Optional[str] = None
    author: Optional[str] = None
    publication_date: Optional[str] = None
    retrieval_date: datetime
    source_type: str
    quality_score: float
    content_hash: str
    citation_metadata: Dict[str, Any]


class FindingOut(ORMModel):
    id: str
    source_id: str
    sub_question_id: Optional[str] = None
    claim_id: Optional[str] = None
    evidence_text: str
    category: str
    confidence: float
    evidence_strength: str
    date_hint: Optional[str] = None


class ClaimOut(ORMModel):
    id: str
    sub_question_id: Optional[str] = None
    statement: str
    category: str
    supporting_count: int
    contradicting_count: int
    distinct_source_count: int
    distinct_publisher_count: int
    agreement_level: str
    confidence: float
    evidence_strength: str


class ContradictionOut(ORMModel):
    id: str
    claim_a_id: str
    claim_b_id: Optional[str] = None
    source_a_id: str
    source_b_id: str
    contradiction_type: str
    explanation: str
    confidence: float
    possible_reason: str


class EntityOut(ORMModel):
    id: str
    name: str
    entity_type: str


class RelationshipOut(ORMModel):
    id: str
    source_entity_id: str
    relation_type: str
    target_entity_id: str
    confidence: float


class ConclusionOut(ORMModel):
    id: str
    sub_question_id: Optional[str] = None
    statement: str
    status: str
    confidence: float
    supporting_claim_ids: List[str]


class ResearchRunOut(ORMModel):
    stage: str
    status: str
    duration_ms: Optional[int] = None
    detail: Dict[str, Any]
