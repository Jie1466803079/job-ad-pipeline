"""Gemini extractor using the official google-genai SDK."""

import time
from collections.abc import Callable

from google import genai
from google.genai import errors, types

from jobpipe.llm.base import ExtractionError, ExtractionResult, LLMUsage, parse_payload
from jobpipe.llm.prompt import SYSTEM_PROMPT, build_user_message
from jobpipe.llm.schema import EXTRACTION_JSON_SCHEMA, strip_keys
from jobpipe.models import Posting

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GeminiExtractor:
    provider = "gemini"

    def __init__(self, client, model: str, thinking_level: str | None = None, max_attempts: int = 4,
                 sleep: Callable[[float], None] = time.sleep,
                 api_error_type: type[Exception] = errors.APIError):
        self.client = client
        self.model = model
        self.thinking_level = thinking_level
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._api_error_type = api_error_type
        self._schema = strip_keys(EXTRACTION_JSON_SCHEMA, {"additionalProperties"})

    @classmethod
    def from_api_key(cls, api_key: str, model: str, thinking_level: str | None = None) -> "GeminiExtractor":
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))
        return cls(client, model, thinking_level)

    def _config(self) -> types.GenerateContentConfig:
        options: dict = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_json_schema": self._schema,
        }
        if self.thinking_level:
            options["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        return types.GenerateContentConfig(**options)

    def extract(self, posting: Posting) -> ExtractionResult:
        started = time.monotonic()
        response = self._generate(build_user_message(posting))
        meta = getattr(response, "usage_metadata", None)
        usage = LLMUsage(
            provider=self.provider,
            model=getattr(response, "model_version", None) or self.model,
            input_tokens=getattr(meta, "prompt_token_count", None) or 0,
            output_tokens=(getattr(meta, "candidates_token_count", None) or 0)
            + (getattr(meta, "thoughts_token_count", None) or 0),
            latency_ms=int((time.monotonic() - started) * 1000),
            request_id=getattr(response, "response_id", None),
        )
        text = getattr(response, "text", None)
        if not text:
            feedback = getattr(response, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                raise ExtractionError("refused", f"Gemini blocked the request: {feedback.block_reason}", usage)
            raise ExtractionError("invalid", "Gemini returned no text", usage)
        return ExtractionResult(payload=parse_payload(text, usage), usage=usage)

    def _generate(self, user_message: str):
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=user_message,
                                                           config=self._config())
            except self._api_error_type as exc:
                status = getattr(exc, "code", None)
                if status in RETRYABLE_STATUS and attempt < self.max_attempts:
                    self._sleep(min(2 ** attempt, 30))
                    continue
                raise ExtractionError("api_error", f"Gemini API error {status}: {exc}") from exc
        raise ExtractionError("api_error", "Gemini API retries exhausted")
