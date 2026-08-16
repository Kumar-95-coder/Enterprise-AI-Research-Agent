from app.config import get_settings
from app.providers.llm.heuristic_provider import HeuristicProvider


def get_llm_provider():
    provider = get_settings().LLM_PROVIDER.lower()
    if provider == "anthropic":
        from app.providers.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if provider == "openai":
        from app.providers.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()
    if provider == "ollama":
        from app.providers.llm.ollama_provider import OllamaProvider
        return OllamaProvider()
    return HeuristicProvider()
