"""
Real OpenAI-backed provider -- same contract as AnthropicProvider, offered
as a second option so the application is not dependent on one proprietary
vendor. Not exercised live in this sandbox (no key / no network).
"""
import json
from typing import List, Dict

from app.providers.llm.base import LLMProvider
from app.config import get_settings


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        self.settings = get_settings()
        try:
            import openai  # local import: optional dependency
            self._client = openai.OpenAI(api_key=self.settings.OPENAI_API_KEY)
        except Exception as e:  # pragma: no cover
            self._client = None
            self._init_error = str(e)

    def is_live(self) -> bool:
        return True

    def decompose_question(self, question: str) -> List[Dict]:
        if self._client is None:
            raise RuntimeError(
                f"OpenAIProvider not initialized ({getattr(self, '_init_error', 'no client')}). "
                f"Install `openai` and set OPENAI_API_KEY, or use LLM_PROVIDER=heuristic."
            )
        resp = self._client.chat.completions.create(
            model=self.settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Output ONLY a JSON array of {\"text\":..., \"focus_area\":...} sub-questions "
                    "for the enterprise research question, covering adoption, process impact, "
                    "benefits, adopters, barriers, risks, contradicting evidence, maturity, outlook."
                )},
                {"role": "user", "content": question},
            ],
        )
        text = resp.choices[0].message.content
        data = json.loads(text)
        return [{"text": d["text"], "focus_area": d.get("focus_area", "general")} for d in data]

    def summarize_for_synthesis(self, sub_question: str, claim_statements: List[str]) -> str:
        if self._client is None:
            raise RuntimeError("OpenAIProvider not initialized.")
        prompt = (f"Sub-question: {sub_question}\nClaims:\n" +
                   "\n".join(f"- {c}" for c in claim_statements) +
                   "\n\nWrite a 2-3 sentence evidence-grounded synthesis, or note an evidence gap.")
        resp = self._client.chat.completions.create(
            model=self.settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
