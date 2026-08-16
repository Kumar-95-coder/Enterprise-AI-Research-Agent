import logging
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import Base, engine
from app import models  # noqa: F401 registers models on Base.metadata
from app.api import research, sources, findings, entities, knowledge

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("research_agent")

app = FastAPI(
    title="Enterprise AI Research Agent",
    description=(
        "Research Planning + External Retrieval + Persistent Knowledge + Evidence Modeling "
        "+ Comparison + Contradiction Detection + Reasoning + Traceability. "
        f"Active providers: LLM={settings.LLM_PROVIDER}, SEARCH={settings.SEARCH_PROVIDER}, "
        f"EMBEDDINGS={settings.EMBEDDING_MODEL}."
    ),
    version="1.0.0",
)

origins = ["*"] if settings.CORS_ORIGINS == "*" else [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # A single failure must not take down the whole service or leak a raw
    # traceback to the client; log full detail server-side only.
    logger.exception(f"Unhandled error on {request.method} {request.url}")
    return JSONResponse(status_code=500, content={"detail": "Internal error. See server logs for details."})


app.include_router(research.router)
app.include_router(sources.router)
app.include_router(findings.findings_router)
app.include_router(findings.claims_router)
app.include_router(entities.router)
app.include_router(knowledge.router)


@app.get("/")
def root():
    return {
        "service": "Enterprise AI Research Agent",
        "status": "ok",
        "llm_provider": settings.LLM_PROVIDER,
        "search_provider": settings.SEARCH_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
        "database": settings.DATABASE_URL.split("://")[0],
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
