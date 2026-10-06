"""What every extractor returns, and the error it raises."""

from typing import Protocol

from pydantic import BaseModel, ValidationError

from jobpipe.llm.schema import ExtractionPayload
from jobpipe.models import Posting


class LLMUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None


class ExtractionResult(BaseModel):
    payload: ExtractionPayload
    usage: LLMUsage


class ExtractionError(Exception):
    """kind is one of: refused, truncated, invalid, api_error."""

    def __init__(self, kind: str, message: str, usage: LLMUsage | None = None):
        super().__init__(message)
        self.kind = kind
        self.usage = usage


class Extractor(Protocol):
    provider: str
    model: str

    def extract(self, posting: Posting) -> ExtractionResult: ...


def parse_payload(raw_text: str, usage: LLMUsage) -> ExtractionPayload:
    try:
        return ExtractionPayload.model_validate_json(raw_text)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "top level"
        message = f"response did not match the schema ({exc.error_count()} errors, first at {where}: {first['msg']})"
        raise ExtractionError("invalid", message, usage) from exc
