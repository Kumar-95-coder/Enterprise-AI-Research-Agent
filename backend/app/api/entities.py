from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import Entity, Relationship
from app import schemas

router = APIRouter(tags=["knowledge-graph"])


@router.get("/api/entities", response_model=list[schemas.EntityOut])
def list_entities(entity_type: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    q = select(Entity)
    if entity_type:
        q = q.where(Entity.entity_type == entity_type)
    return db.execute(q.limit(limit)).scalars().all()


@router.get("/api/relationships", response_model=list[schemas.RelationshipOut])
def list_relationships(research_job_id: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    q = select(Relationship)
    if research_job_id:
        q = q.where(Relationship.research_job_id == research_job_id)
    return db.execute(q.limit(limit)).scalars().all()
