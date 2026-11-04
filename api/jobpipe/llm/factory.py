"""Build the extractor named by LLM_PROVIDER."""

from jobpipe.llm.base import Extractor
from jobpipe.settings import Settings


def make_extractor(settings: Settings) -> Extractor:
    if settings.llm_provider == "fake":
        from jobpipe.llm.fake import FakeExtractor

        return FakeExtractor()
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER is gemini but GEMINI_API_KEY is not set")
        from jobpipe.llm.gemini import GeminiExtractor

        return GeminiExtractor.from_api_key(settings.gemini_api_key, settings.gemini_model,
                                            settings.gemini_thinking_level or None)
    if settings.llm_provider == "claude":
        from jobpipe.llm.claude import ClaudeExtractor

        return ClaudeExtractor.from_api_key(settings.anthropic_api_key or None, settings.claude_model,
                                            settings.claude_effort)
    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")
