"""
Celery + Redis reference implementation for horizontal scaling.

This is the production scale-out path referenced in docs/scaling.md: the
exact same pipeline stages as app/pipeline/orchestrator.py, wrapped as a
Celery task so N worker processes (potentially on N machines) can pull jobs
from a shared Redis queue instead of one process handling everything via
FastAPI BackgroundTasks.

NOT started in this sandbox demo -- there's no Redis daemon running here,
and the default docker-compose profile doesn't start the `redis`/`worker`
services either, to keep the default `docker-compose up` path simple. To
actually run this:

    docker compose --profile scale up      # starts redis + worker replicas
    # then in .env: BACKGROUND_MODE=celery

and change the POST /api/research handler to call
`run_research_pipeline_task.delay(job_id)` instead of
`background_tasks.add_task(run_research_pipeline, job_id)`.

The task body is intentionally a thin wrapper around the *same* orchestrator
function used by the default path, so there is exactly one implementation
of the pipeline logic to keep correct, not two that can drift apart.
"""
import os

try:
    from celery import Celery
except ImportError:  # pragma: no cover -- celery is an optional prod dependency
    Celery = None

from app.pipeline.orchestrator import run_research_pipeline

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

if Celery is not None:
    celery_app = Celery("research_agent", broker=REDIS_URL, backend=REDIS_URL)
    celery_app.conf.update(
        task_routes={
            # Separate queues per stage-weight so a slow LLM-bound job
            # doesn't starve fast dedup/storage work -- see docs/scaling.md
            "app.workers.celery_tasks.run_research_pipeline_task": {"queue": "research"},
        },
        task_acks_late=True,          # re-deliver to another worker if one dies mid-job
        worker_prefetch_multiplier=1,  # don't hoard jobs on one worker while others idle
        task_reject_on_worker_lost=True,
    )

    @celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
    def run_research_pipeline_task(self, job_id: str):
        try:
            run_research_pipeline(job_id)
        except Exception as exc:  # pragma: no cover
            raise self.retry(exc=exc)
else:
    celery_app = None
    run_research_pipeline_task = None
