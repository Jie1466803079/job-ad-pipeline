"""A stand-in extractor for tests and for running the stack without API keys."""

from collections.abc import Callable

from jobpipe.llm.base import ExtractionResult, LLMUsage
from jobpipe.llm.schema import ExtractionPayload, not_stated_payload
from jobpipe.models import Posting


class FakeExtractor:
    provider = "fake"

    def __init__(self, payload_for: Callable[[Posting], ExtractionPayload | Exception] | None = None,
                 model: str = "fake-1"):
        self.model = model
        self.calls: list[str] = []
        self._payload_for = payload_for or (lambda posting: not_stated_payload())

    def extract(self, posting: Posting) -> ExtractionResult:
        self.calls.append(posting.source_id)
        outcome = self._payload_for(posting)
        if isinstance(outcome, Exception):
            raise outcome
        usage = LLMUsage(provider=self.provider, model=self.model, input_tokens=1000, output_tokens=200)
        return ExtractionResult(payload=outcome, usage=usage)
