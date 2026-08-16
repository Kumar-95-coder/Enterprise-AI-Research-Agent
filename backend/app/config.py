"""
Centralized configuration.

Every external dependency is configured through environment variables so the
application is reproducible without hard-coded credentials, and so any
provider (LLM, search, database) can be swapped without touching code.
See ../../.env.example for the full list of supported variables.
"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to backend/.env via __file__ rather than a bare relative ".env" --
# a relative path is resolved against the process's CURRENT WORKING
# DIRECTORY at the moment Settings() is instantiated, which silently
# breaks the moment uvicorn/alembic/pytest are launched from anywhere other
# than exactly this directory (verified: this was actually broken --
# `cd backend` then a .env placed one level up, per what an earlier version
# of this README told people to do, was silently ignored with no error).
# Anchoring to __file__ makes local .env loading work the same regardless
# of the caller's CWD. Docker Compose is unaffected by this either way --
# it injects real process env vars directly via its own `env_file:`
# mechanism, which pydantic-settings picks up automatically.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # --- Database ---
    # SQLite by default (zero-config, fully real relational DB with FKs/indexes).
    # Point this at postgresql+psycopg2://user:pass@host:5432/db for production;
    # every model/migration in this codebase is dialect-agnostic.
    DATABASE_URL: str = "sqlite:///./research_agent.db"

    # --- LLM provider ---
    # heuristic  -> local, deterministic, no external calls, no API key required
    # anthropic  -> calls the real Anthropic API (requires ANTHROPIC_API_KEY + internet)
    # openai     -> calls the real OpenAI API (requires OPENAI_API_KEY + internet)
    # ollama     -> calls a local Ollama server (requires Ollama installed + a model
    #               pulled, but NO API key and NO internet at inference time)
    LLM_PROVIDER: str = "heuristic"
    LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # --- Search / retrieval provider ---
    # local_corpus -> searches the locally indexed seed corpus (no internet)
    # live_http    -> calls a real web-search API (requires SEARCH_API_KEY + internet)
    # searxng      -> self-hosted metasearch engine (no API key; needs a running instance,
    #                 see docker-compose.yml's `searxng` service)
    # duckduckgo   -> scrapes DuckDuckGo directly via the `ddgs` package (no API key,
    #                 no service to run, but more fragile than searxng -- see its docstring)
    SEARCH_PROVIDER: str = "local_corpus"
    SEARCH_API_KEY: str = ""
    SEARCH_API_URL: str = "https://api.tavily.com/search"
    SEARXNG_URL: str = "http://localhost:8888"

    # --- Embeddings / vector search ---
    # tfidf -> scikit-learn TF-IDF + cosine similarity, fully local
    # sentence-transformers -> swap-in target for higher-quality semantic search
    EMBEDDING_MODEL: str = "tfidf"

    # --- Background processing (see docs/scaling.md) ---
    # asyncio (default, runs in-process via FastAPI BackgroundTasks) | celery
    BACKGROUND_MODE: str = "asyncio"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Misc ---
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"
    # Calibrated empirically against this codebase's real seed corpus (see
    # docs/architecture.md "Threshold calibration"): TF-IDF cosine similarity
    # between short single-sentence claims runs much lower than intuition
    # suggests -- genuinely same-topic sentence pairs measured ~0.15-0.21,
    # unrelated pairs ~0.0. 0.30/0.35 (the original guesses) excluded almost
    # everything.
    MIN_CONTRADICTION_SIMILARITY: float = 0.06
    MIN_CLAIM_CLUSTER_SIMILARITY: float = 0.12


@lru_cache
def get_settings() -> Settings:
    return Settings()
