# Scaling: 10 → 100 → 1,000 → 10,000+ documents

## A real measured baseline, not a guess

Rather than only speculating, this sandbox ran an actual throughput benchmark: 200 synthetic
documents (clearly synthetic — template-generated, not real sources, so as not to misrepresent
them as retrieved evidence) through the real extraction + classification + spaCy NER pipeline,
single-process, single-threaded:

```
200 documents -> 5,000 candidate findings extracted -> 30.55s -> 6.5 docs/sec
```

spaCy NER is the dominant cost (one model call per candidate evidence sentence, ~25 sentences/doc
here). This is the number everything below extrapolates from.

## What breaks first, in order, as volume grows

| Stage | Bottleneck at scale | Fix |
|---|---|---|
| SEARCHING | Sequential API calls to `SearchProvider`, one per expanded query (~15-20 per job) | Parallelize with `asyncio.gather` / a connection pool; respect the provider's rate limit with a token-bucket limiter |
| COLLECTING | Fetching + hashing full page content synchronously | Move to a queue-backed worker pool (see below); cap concurrent fetches |
| EXTRACTING | spaCy NER is ~6.5 docs/sec single-process (measured above) | Embarrassingly parallel across documents — this is the first and highest-value target for horizontal scaling |
| Claim clustering / contradiction detection | O(n²) pairwise TF-IDF comparisons within a sub-question bucket | Bounded already by bucket size (9 sub-questions × typically tens of findings each); at 10,000+ documents, pre-cluster with approximate nearest-neighbor (e.g. FAISS) before the O(n²) pass, or cap per-bucket comparison to top-k by TF-IDF-index proximity |
| Database | Single SQLite file; write contention under concurrent workers | Switch `DATABASE_URL` to Postgres (already fully supported, see `docker-compose.yml`) — SQLite is intentionally a dev-mode choice, not a scale choice |
| Vector search | TF-IDF store is rebuilt in memory per knowledge-search request | Fine into the thousands of rows; beyond that, persist a proper ANN index (FAISS/pgvector/Qdrant) incrementally rather than rebuilding on every query |

## Concrete architecture at each order of magnitude

**10–100 documents (current default path):** exactly what's running in this repo's demo —
FastAPI `BackgroundTasks`, SQLite, in-memory TF-IDF rebuilt per request. No changes needed.

**100–1,000 documents:** switch `DATABASE_URL` to Postgres (one env var). Move background
execution from `BackgroundTasks` to the Celery + Redis reference implementation in
`backend/app/workers/celery_tasks.py` (same task logic, now runnable as N worker processes).
Batch NER calls with `nlp.pipe(sentences, batch_size=64)` instead of one call per sentence — this
alone is typically a 3-5x speedup over the naive per-call pattern measured above.

**1,000–10,000 documents:** horizontal scale-out — multiple Celery workers per pipeline stage
(a `search` queue, an `extract` queue, an `analyze` queue, so a slow LLM-bound stage doesn't
starve fast stages), each processing documents in parallel. Chunk long documents before extraction
rather than extracting from the whole page at once. Add exponential-backoff retry (e.g. `tenacity`)
around every external call (search API, LLM API) since failure *rate*, not just latency, starts to
matter once you're making thousands of calls. Introduce a real ANN vector index for semantic
retrieval instead of TF-IDF-in-memory.

**10,000+ documents:** the knowledge base itself becomes the bottleneck, not any single job's
ingestion. Partition/shard the vector index; move to a managed vector DB (Qdrant/Weaviate/pgvector
at scale) with incremental upsert (already the pattern in `KnowledgeVector` — this schema doesn't
need to change, only its backing index does); consider read replicas for the Postgres instance
serving the knowledge-base-explorer UI, since research and reporting reads shouldn't contend with
ingestion writes; add a cost/rate-limit budget tracker per research job so one runaway job can't
exhaust the LLM/search API quota for everyone else using the platform.

## Cost and latency, extrapolated from the measured baseline

At 6.5 docs/sec single-process (NER-bound): 1,000 documents ≈ 2.6 minutes single-threaded, or
under 20 seconds with 8 parallel workers. Search and LLM-provider latency (not measured here,
since this sandbox has no live network to either) will typically dominate over local NER/TF-IDF
cost once a real `SEARCH_PROVIDER=live_http` and `LLM_PROVIDER=anthropic`/`openai` are active —
budget for API rate limits as the real ceiling at high volume, not local compute.

## Failure recovery

Every pipeline stage is already wrapped in the orchestrator's per-stage error boundary
(`app/pipeline/orchestrator.py::_stage`): a failure in one stage marks the job `FAILED` with the
triggering error preserved on `job.error_message`, rather than crashing the process or silently
producing a corrupted job. A single bad source cannot currently take down a whole job's SEARCHING
stage (each search-provider call is independent per query); the same pattern should be extended
per-document at the EXTRACTING stage before scaling to thousands of documents per job, so a single
malformed document doesn't fail the entire batch — this is flagged here as a genuine next step,
not already fully implemented at the per-document level.
