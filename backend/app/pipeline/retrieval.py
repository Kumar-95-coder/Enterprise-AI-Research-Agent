"""
Pipeline stage: source discovery + retrieval + deduplication + storage.

Every candidate result from the configured SearchProvider is deduplicated
against the *global* sources table (normalized URL first) before being
persisted -- a source already known from a previous research job is reused
(job_sources.is_new_for_job=False) rather than re-inserted. This is the
concrete mechanism behind "knowledge reuse" (see docs/data-model.md) and
"never repeatedly retrieve the same source."
"""
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Source, JobSource
from app.providers.search import get_search_provider
from app.utils.hashing import normalize_url, content_hash

_SOURCE_TYPE_WEIGHT = {
    "government": 0.95, "academic": 0.90, "standards": 0.90,
    "industry_report": 0.75, "technical_documentation": 0.70,
    "news_business": 0.60, "web": 0.50,
}


def _quality_score(r: dict) -> float:
    base = _SOURCE_TYPE_WEIGHT.get(r.get("source_type", "web"), 0.5)
    if r.get("publication_date"):
        base += 0.05
    if r.get("author"):
        base += 0.03
    return round(min(base, 1.0), 2)


def discover_and_collect(db: Session, job_id: str, queries: list[str], max_per_query: int = 4) -> dict:
    provider = get_search_provider()
    new_count, reused_count = 0, 0
    collected_source_ids = []
    seen_norm_urls = set()

    for query in queries:
        results = provider.search(query, max_results=max_per_query)
        for r in results:
            url = r.get("url")
            if not url:
                continue
            norm = normalize_url(url)
            if norm in seen_norm_urls:
                continue
            seen_norm_urls.add(norm)

            existing = db.execute(select(Source).where(Source.normalized_url == norm)).scalar_one_or_none()
            if existing:
                source, is_new = existing, False
                reused_count += 1
            else:
                content = r.get("content", "") or ""
                source = Source(
                    url=url,
                    normalized_url=norm,
                    title=(r.get("title") or "Untitled")[:500],
                    publisher=r.get("publisher"),
                    author=r.get("author"),
                    publication_date=r.get("publication_date"),
                    source_type=r.get("source_type", "web"),
                    content=content,
                    content_hash=content_hash(content or url),
                    quality_score=_quality_score(r),
                    relevant_passages=[],
                    citation_metadata={"retrieved_via": r.get("retrieved_via", provider.name),
                                        "search_provider": provider.name},
                    first_discovered_by_job_id=job_id,
                )
                db.add(source)
                db.flush()
                is_new = True
                new_count += 1

            link = db.execute(select(JobSource).where(
                JobSource.job_id == job_id, JobSource.source_id == source.id
            )).scalar_one_or_none()
            if not link:
                db.add(JobSource(job_id=job_id, source_id=source.id, search_query=query, is_new_for_job=is_new))
            collected_source_ids.append(source.id)

    db.flush()
    return {"new": new_count, "reused": reused_count,
            "source_ids": list(dict.fromkeys(collected_source_ids))}
