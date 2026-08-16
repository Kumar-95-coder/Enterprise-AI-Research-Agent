"""
Real Ollama-backed provider -- local, free, no API key required.

Requires Ollama (https://ollama.com) installed and running locally, with a
model pulled, e.g.:
    ollama pull llama3.2        # ~2GB, good default balance of speed/quality
    ollama pull qwen2.5:3b      # smaller/faster, weaker reasoning
    ollama pull llama3.1        # ~4.7GB, stronger reasoning, needs ~8GB RAM

Ollama runs an HTTP server on localhost:11434 by default. Nothing external
is called, no key is needed, no data leaves the machine this runs on. This
is the real keyless path to non-heuristic reasoning: same LLMProvider
interface as AnthropicProvider/OpenAIProvider, so nothing else in the
pipeline changes when you switch to it.

Verified against Ollama's current documented /api/chat contract (checked
2026-08-14, https://docs.ollama.com/capabilities/structured-outputs):
POST /api/chat with {"model", "messages", "stream": false, "format": "json"}
returns {"message": {"content": "<json string>"}}. format:"json" constrains
the model to emit syntactically valid JSON; it does not guarantee the exact
schema asked for in the prompt, so the response is still validated below
rather than trusted blindly.

NOT exercised live in the sandboxed demo bundled with this repo -- that
sandbox's network is restricted to package registries, so it can neither
install Ollama nor download model weights. Run this locally: the code below
is written and verified against Ollama's real, current API documentation
and is ready to use once `ollama serve` is running.
"""
import json
import requests
from typing import List, Dict

from app.providers.llm.base import LLMProvider
from app.config import get_settings

DECOMPOSE_SYSTEM = (
    "You are a research planning assistant for an enterprise research agent. "
    "Given a research question, output 6-9 sub-questions that would need to be "
    "answered to thoroughly research it, covering adoption, process impact, "
    "measurable benefits, adopters, barriers, risks, contradicting evidence, "
    "maturity, and future outlook where applicable. "
    'Respond ONLY with a JSON object of the exact shape '
    '{"sub_questions": [{"text": "...", "focus_area": "..."}, ...]}. '
    "No markdown, no prose, no code fences -- valid JSON only."
)

SYNTHESIS_SYSTEM = "You are a precise research analyst. Respond in plain prose, no markdown, no preamble."


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL

    def is_live(self) -> bool:
        return True

    def _chat(self, system: str, user: str, want_json: bool) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if want_json:
            payload["format"] = "json"
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is it installed and running? "
                f"Install from https://ollama.com, then `ollama pull {self.model}` and "
                f"`ollama serve` (or just `ollama run {self.model}` once, which starts the "
                f"server too). Original error: {e}"
            )
        if resp.status_code == 404:
            raise RuntimeError(
                f"Ollama is running but model '{self.model}' isn't pulled yet. "
                f"Run `ollama pull {self.model}` (or set OLLAMA_MODEL to a model you already have)."
            )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def decompose_question(self, question: str) -> List[Dict]:
        raw = self._chat(DECOMPOSE_SYSTEM, question, want_json=True)
        try:
            data = json.loads(raw)
            items = data.get("sub_questions", data) if isinstance(data, dict) else data
            return [{"text": d["text"], "focus_area": d.get("focus_area", "general")} for d in items]
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
            raise ValueError(
                f"Ollama's format:json mode guarantees syntactically valid JSON but not this "
                f"exact schema -- got: {raw[:300]}"
            ) from e

    def summarize_for_synthesis(self, sub_question: str, claim_statements: List[str]) -> str:
        if not claim_statements:
            prompt = f"Sub-question: {sub_question}\n\nNo evidence was found. State plainly that this is an evidence gap."
        else:
            prompt = (
                f"Sub-question: {sub_question}\n\n"
                f"Claims derived from retrieved evidence (do not invent claims beyond this list):\n"
                + "\n".join(f"- {c}" for c in claim_statements)
                + "\n\nWrite a 2-3 sentence evidence-grounded synthesis."
            )
        return self._chat(SYNTHESIS_SYSTEM, prompt, want_json=False).strip()
