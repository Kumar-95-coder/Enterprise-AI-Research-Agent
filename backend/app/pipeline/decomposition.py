from sqlalchemy.orm import Session

from app.models import SubQuestion
from app.providers.llm import get_llm_provider


def decompose(db: Session, job_id: str, question: str) -> list[SubQuestion]:
    provider = get_llm_provider()
    raw = provider.decompose_question(question)
    subs = []
    for i, item in enumerate(raw):
        sq = SubQuestion(
            research_job_id=job_id,
            text=item["text"],
            focus_area=item.get("focus_area", "general"),
            order_index=i,
        )
        db.add(sq)
        subs.append(sq)
    db.flush()
    return subs
