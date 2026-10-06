"""Claude extractor using the official anthropic SDK."""

import time

import anthropic

from jobpipe.llm.base import ExtractionError, ExtractionResult, LLMUsage, parse_payload
from jobpipe.llm.prompt import SYSTEM_PROMPT, build_user_message
from jobpipe.llm.schema import EXTRACTION_JSON_SCHEMA
from jobpipe.models import Posting

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeExtractor:
    provider = "claude"

    def __init__(self, client, model: str, effort: str = "low", max_tokens: int = 16000):
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    @classmethod
    def from_api_key(cls, api_key: str | None, model: str, effort: str = "low") -> "ClaudeExtractor":
        # With api_key None the SDK uses ANTHROPIC_API_KEY or an `ant auth login` profile.
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=3)
        return cls(client, model, effort)

    def extract(self, posting: Posting) -> ExtractionResult:
        started = time.monotonic()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(posting)}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": EXTRACTION_JSON_SCHEMA},
                },
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionError("api_error", f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError("api_error", f"Claude connection error: {exc}") from exc
        usage = LLMUsage(
            provider=self.provider,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            request_id=getattr(response, "_request_id", None),
        )
        if response.stop_reason == "refusal":
            raise ExtractionError("refused", "Claude declined the request", usage)
        if response.stop_reason == "max_tokens":
            raise ExtractionError("truncated", "the response hit max_tokens", usage)
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise ExtractionError("invalid", "Claude returned no text block", usage)
        return ExtractionResult(payload=parse_payload(text, usage), usage=usage)
