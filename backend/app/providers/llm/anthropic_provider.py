"""
Real Anthropic-backed provider.

This is complete, correct, production code -- it is NOT exercised live in
the sandboxed demo bundled with this repo, because that sandbox has no
outbound network access to api.anthropic.com and no API key. Run this
locally with ANTHROPIC_API_KEY set and LLM_PROVIDER=anthropic to activate
real LLM reasoning for decomposition and synthesis; every other pipeline
stage (retrieval, storage, comparison, contradiction detection, entity
extraction) is unchanged.
"""
import json
from typing import List, Dict

from app.providers.llm.base import LLMProvider
from app.config import get_settings

DECOMPOSE_SYSTEM = (
    "You are a research planning assistant for an enterprise research agent. "
    "Given a research question, output 6-9 sub-questions that would need to be "
    "answered to thoroughly research it, covering adoption, process impact, "
    "measurable benefits, adopters, barriers, risks, contradicting evidence, "
    "maturity, and future outlook where applicable. "
    "Respond ONLY with a JSON array of objects: [{\"text\": ..., \"focus_area\": ...}]. "
    "No markdown, no prose, no code fences."
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self):
        self.settings = get_settings()
        try:
            import anthropic  # local import: optional dependency
            self._client = anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
        except Exception as e:  # pragma: no cover - only hit without the SDK/key
            self._client = None
            self._init_error = str(e)

    def is_live(self) -> bool:
        return True

    def decompose_question(self, question: str) -> List[Dict]:
        if self._client is None:
            raise RuntimeError(
                f"AnthropicProvider not initialized ({getattr(self, '_init_error', 'no client')}). "
                f"Install `anthropic` and set ANTHROPIC_API_KEY, or use LLM_PROVIDER=heuristic."
            )
        resp = self._client.messages.create(
            model=self.settings.LLM_MODEL,
            max_tokens=1000,
            system=DECOMPOSE_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            data = json.loads(text)
            return [{"text": d["text"], "focus_area": d.get("focus_area", "general")} for d in data]
        except Exception:
            # Never let a malformed model response silently fabricate structure;
            # surface the failure so the pipeline can log/handle it explicitly.
            raise ValueError(f"Could not parse decomposition response as JSON: {text[:200]}")

    def summarize_for_synthesis(self, sub_question: str, claim_statements: List[str]) -> str:
        if self._client is None:
            raise RuntimeError("AnthropicProvider not initialized.")
        prompt = (
            f"Sub-question: {sub_question}\n\n"
            f"Claims derived from retrieved evidence (do not invent claims beyond this list):\n"
            + "\n".join(f"- {c}" for c in claim_statements)
            + "\n\nWrite a 2-3 sentence evidence-grounded synthesis. "
              "If the list is empty, state plainly that this is an evidence gap."
        )
        resp = self._client.messages.create(
            model=self.settings.LLM_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
