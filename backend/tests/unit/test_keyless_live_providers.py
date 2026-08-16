"""
Tests for OllamaProvider / SearXNGProvider / DuckDuckGoProvider.

This sandbox cannot reach any of these live (no Ollama install, no SearXNG
instance, no route to duckduckgo.com). What CAN be verified without live
network access -- and is verified here -- is that the request payloads
these providers build match each service's real documented contract, and
that their response-parsing logic correctly handles both well-formed and
malformed responses. HTTP calls are mocked; nothing about the parsing or
error-handling logic is faked.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import pytest
from unittest.mock import MagicMock

from app.providers.llm.ollama_provider import OllamaProvider
from app.providers.search.searxng_provider import SearXNGProvider


class TestOllamaProvider:
    def test_decompose_sends_correct_request_shape(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"message": {"content":
                '{"sub_questions": [{"text": "Which AI tools are adopted?", "focus_area": "adoption"}, '
                '{"text": "What risks exist?", "focus_area": "risks"}]}'
            }}
            return resp

        monkeypatch.setattr("app.providers.llm.ollama_provider.requests.post", fake_post)
        provider = OllamaProvider()
        result = provider.decompose_question("What AI technologies are changing manufacturing?")

        assert captured["url"] == "http://localhost:11434/api/chat"
        assert captured["json"]["format"] == "json"
        assert captured["json"]["stream"] is False
        assert captured["json"]["messages"][-1]["content"] == "What AI technologies are changing manufacturing?"
        assert result == [
            {"text": "Which AI tools are adopted?", "focus_area": "adoption"},
            {"text": "What risks exist?", "focus_area": "risks"},
        ]

    def test_raises_actionable_error_when_ollama_not_running(self, monkeypatch):
        def fake_post(*a, **k):
            raise requests.exceptions.ConnectionError("Connection refused")
        monkeypatch.setattr("app.providers.llm.ollama_provider.requests.post", fake_post)

        provider = OllamaProvider()
        with pytest.raises(RuntimeError, match="Could not reach Ollama"):
            provider.decompose_question("test question")

    def test_raises_actionable_error_when_model_not_pulled(self, monkeypatch):
        def fake_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 404
            return resp
        monkeypatch.setattr("app.providers.llm.ollama_provider.requests.post", fake_post)

        provider = OllamaProvider()
        with pytest.raises(RuntimeError, match="isn't pulled yet"):
            provider.decompose_question("test question")

    def test_raises_clear_error_on_malformed_json_response(self, monkeypatch):
        def fake_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"message": {"content": "this is not json"}}
            return resp
        monkeypatch.setattr("app.providers.llm.ollama_provider.requests.post", fake_post)

        provider = OllamaProvider()
        with pytest.raises(ValueError):
            provider.decompose_question("test question")

    def test_synthesis_reports_gap_prompt_when_no_claims(self, monkeypatch):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["prompt"] = json["messages"][-1]["content"]
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"message": {"content": "This is an evidence gap."}}
            return resp
        monkeypatch.setattr("app.providers.llm.ollama_provider.requests.post", fake_post)

        provider = OllamaProvider()
        result = provider.summarize_for_synthesis("What risks exist?", [])
        assert "No evidence" in captured["prompt"]
        assert result == "This is an evidence gap."


class TestSearXNGProvider:
    def test_search_sends_correct_request_shape_and_parses_response(self, monkeypatch):
        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"results": [
                {"title": "Real result", "url": "https://example.com/a",
                 "content": "some content", "engine": "google", "score": 0.8},
                {"title": "Second result", "url": "https://example.org/b",
                 "content": "other content", "engine": "bing"},
            ]}
            return resp
        monkeypatch.setattr("app.providers.search.searxng_provider.requests.get", fake_get)

        provider = SearXNGProvider()
        results = provider.search("AI manufacturing", max_results=5)

        assert captured["url"] == "http://localhost:8888/search"
        assert captured["params"]["format"] == "json"
        assert captured["params"]["q"] == "AI manufacturing"
        assert len(results) == 2
        assert results[0]["url"] == "https://example.com/a"
        assert results[0]["publisher"] == "google"
        assert results[0]["retrieved_via"] == "searxng"

    def test_raises_actionable_error_when_searxng_not_running(self, monkeypatch):
        def fake_get(*a, **k):
            raise requests.exceptions.ConnectionError("Connection refused")
        monkeypatch.setattr("app.providers.search.searxng_provider.requests.get", fake_get)

        provider = SearXNGProvider()
        with pytest.raises(RuntimeError, match="Could not reach SearXNG"):
            provider.search("test query")

    def test_raises_actionable_error_when_json_format_disabled(self, monkeypatch):
        def fake_get(url, params=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 403
            return resp
        monkeypatch.setattr("app.providers.search.searxng_provider.requests.get", fake_get)

        provider = SearXNGProvider()
        with pytest.raises(RuntimeError, match="JSON API is disabled"):
            provider.search("test query")

    def test_respects_max_results(self, monkeypatch):
        def fake_get(url, params=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": "x", "engine": "google"}
                for i in range(10)
            ]}
            return resp
        monkeypatch.setattr("app.providers.search.searxng_provider.requests.get", fake_get)

        provider = SearXNGProvider()
        results = provider.search("test", max_results=3)
        assert len(results) == 3


class TestDuckDuckGoProviderFieldMapping:
    """DuckDuckGoProvider wraps the `ddgs` package rather than raw HTTP, so
    what's tested here is the title/href/body -> our schema mapping using
    the package's real, confirmed result shape -- not a live search."""

    def test_maps_ddgs_result_fields_correctly(self, monkeypatch):
        from app.providers.search.duckduckgo_provider import DuckDuckGoProvider

        class FakeDDGS:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def text(self, query, max_results=5, backend="duckduckgo"):
                assert backend == "duckduckgo"
                return [
                    {"title": "Manufacturing AI report", "href": "https://example.com/report", "body": "Some content here"},
                ]

        provider = DuckDuckGoProvider()
        provider._DDGS = FakeDDGS
        results = provider.search("AI manufacturing", max_results=5)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/report"
        assert results[0]["title"] == "Manufacturing AI report"
        assert results[0]["content"] == "Some content here"
        assert results[0]["publisher"] == "example.com"
        assert results[0]["retrieved_via"] == "duckduckgo"

    def test_raises_clear_error_when_package_not_installed(self):
        from app.providers.search.duckduckgo_provider import DuckDuckGoProvider
        provider = DuckDuckGoProvider()
        provider._DDGS = None
        provider._import_error = "simulated: not installed"
        with pytest.raises(RuntimeError, match="ddgs.*isn't installed"):
            provider.search("test")
