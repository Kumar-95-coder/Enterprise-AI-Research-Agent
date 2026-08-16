"""
GET /api/knowledge/search: semantic search across the entire persisted
knowledge base (not scoped to one research job), backed by the same TF-IDF
vector store used during the pipeline. This is what "the application should
progressively become more useful as more research is performed" means
concretely: every finding/claim/source ever stored is searchable here,
independent of which research job originally produced it.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import KnowledgeVector, Finding, Claim, Source
from app.vectorstore.tfidf_store import TfidfVectorStore

router = APIRouter(prefix="/api/knowledge", tags=["knowledge-base"])


@router.get("/search")
def search_knowledge(q: str = Query(..., min_length=2), k: int = 10, db: Session = Depends(get_db)):
    vectors = db.execute(select(KnowledgeVector)).scalars().all()
    store = TfidfVectorStore()
    store.fit([(v.id, v.text) for v in vectors])
    hits = store.search(q, k=k, min_similarity=0.05)

    by_id = {v.id: v for v in vectors}
    results = []
    for vec_id, score in hits:
        v = by_id[vec_id]
        item = {"object_type": v.object_type, "object_id": v.object_id, "text": v.text,
                "similarity": round(score, 3), "research_job_id": v.research_job_id}
        if v.object_type == "source":
            src = db.get(Source, v.object_id)
            if src:
                item["url"] = src.url
                item["title"] = src.title
        results.append(item)
    return {"query": q, "result_count": len(results), "results": results}
