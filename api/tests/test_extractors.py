import json
from types import SimpleNamespace

import pytest

from helpers import posting_with
from jobpipe.configfiles import Price
from jobpipe.llm.base import ExtractionError
from jobpipe.llm.claude import FALLBACK_BETA, ClaudeExtractor
from jobpipe.llm.factory import make_extractor
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.gemini import GeminiExtractor
from jobpipe.llm.pricing import cost_usd
from jobpipe.llm.schema import EXTRACTION_JSON_SCHEMA, not_stated_payload
from jobpipe.settings import Settings

PAYLOAD_JSON = not_stated_payload().model_dump_json()


class FakeAPIError(Exception):
    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.code = code


class StubModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def gemini_response(text, block_reason=None):
    return SimpleNamespace(
        text=text,
        model_version="gemini-3.8-flash",
        response_id="resp-1",
        usage_metadata=SimpleNamespace(prompt_token_count=3000, candidates_token_count=700, thoughts_token_count=300),
        prompt_feedback=SimpleNamespace(block_reason=block_reason) if block_reason else None,
    )


def gemini_with(outcomes):
    models = StubModels(outcomes)
    extractor = GeminiExtractor(SimpleNamespace(models=models), "gemini-3.8-flash", sleep=lambda seconds: None,
                                api_error_type=FakeAPIError)
    return extractor, models


def test_gemini_sends_the_schema_and_parses_the_payload():
    extractor, models = gemini_with([gemini_response(PAYLOAD_JSON)])
    result = extractor.extract(posting_with("Some ad text"))
    assert result.payload == not_stated_payload()
    assert (result.usage.input_tokens, result.usage.output_tokens) == (3000, 1000)
    assert result.usage.request_id == "resp-1"
    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert "<job_ad>" in call["contents"]
    assert call["config"].response_mime_type == "application/json"
    assert "additionalProperties" not in json.dumps(call["config"].response_json_schema)
    assert call["config"].thinking_config is None


def test_gemini_retries_rate_limits_and_server_errors():
    extractor, models = gemini_with([FakeAPIError(429), FakeAPIError(503), gemini_response(PAYLOAD_JSON)])
    assert extractor.extract(posting_with("Some ad text")).payload == not_stated_payload()
    assert len(models.calls) == 3


def test_gemini_gives_up_on_client_errors():
    extractor, models = gemini_with([FakeAPIError(400)])
    with pytest.raises(ExtractionError) as info:
        extractor.extract(posting_with("Some ad text"))
    assert info.value.kind == "api_error"
    assert len(models.calls) == 1


def test_gemini_blocked_and_malformed_responses():
    extractor, _ = gemini_with([gemini_response(None, block_reason="SAFETY")])
    with pytest.raises(ExtractionError) as info:
        extractor.extract(posting_with("Some ad text"))
    assert info.value.kind == "refused"
    extractor, _ = gemini_with([gemini_response('{"work_rights": "oops"}')])
    with pytest.raises(ExtractionError) as info:
        extractor.extract(posting_with("Some ad text"))
    assert info.value.kind == "invalid"
    assert info.value.usage.input_tokens == 3000


class StubMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def claude_response(text, stop_reason="end_turn"):
    blocks = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(model="claude-opus-5-5", stop_reason=stop_reason, content=blocks,
                           usage=SimpleNamespace(input_tokens=3100, output_tokens=900), _request_id="req_1")


def claude_with(response):
    messages = StubMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeExtractor(client, "claude-opus-5-5"), messages


def test_claude_sends_the_schema_with_refusal_fallback_and_parses_the_payload():
    extractor, messages = claude_with(claude_response(PAYLOAD_JSON))
    result = extractor.extract(posting_with("Some ad text"))
    assert result.payload == not_stated_payload()
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.request_id) == (3100, 900, "req_1")
    sent = messages.kwargs
    assert sent["model"] == "claude-opus-5-5"
    assert sent["betas"] == [FALLBACK_BETA] and sent["fallbacks"] == "default"
    assert sent["output_config"] == {"effort": "low",
                                     "format": {"type": "json_schema", "schema": EXTRACTION_JSON_SCHEMA}}
    assert "<job_ad>" in sent["messages"][0]["content"]


@pytest.mark.parametrize("stop_reason, kind", [("refusal", "refused"), ("max_tokens", "truncated")])
def test_claude_refusal_and_truncation(stop_reason, kind):
    extractor, _ = claude_with(claude_response(None, stop_reason=stop_reason))
    with pytest.raises(ExtractionError) as info:
        extractor.extract(posting_with("Some ad text"))
    assert info.value.kind == kind


def test_fake_extractor_records_calls_and_can_fail():
    fake = FakeExtractor()
    assert fake.extract(posting_with("x", source_id="a")).payload == not_stated_payload()
    assert fake.calls == ["a"]
    failing = FakeExtractor(lambda posting: ExtractionError("api_error", "boom"))
    with pytest.raises(ExtractionError):
        failing.extract(posting_with("x"))


def test_cost_usd():
    prices = {"gemini-3.8-flash": Price(input=0.75, output=3.75)}
    assert cost_usd("gemini-3.8-flash", 3000, 1000, prices) == 0.006
    assert cost_usd("gemini-3.8-flash-001", 3000, 1000, prices) is None
    assert cost_usd("gemini-3.8-flash-001", 3000, 1000, prices, fallback_model="gemini-3.8-flash") == 0.006


def test_factory_picks_the_configured_provider():
    assert isinstance(make_extractor(Settings(llm_provider="fake")), FakeExtractor)
    with pytest.raises(RuntimeError):
        make_extractor(Settings(llm_provider="gemini", gemini_api_key=""))
    gemini = make_extractor(Settings(llm_provider="gemini", gemini_api_key="test-key",
                                     gemini_model="gemini-3.5-flash-lite"))
    assert isinstance(gemini, GeminiExtractor) and gemini.model == "gemini-3.5-flash-lite"
    claude = make_extractor(Settings(llm_provider="claude", anthropic_api_key="test-key"))
    assert isinstance(claude, ClaudeExtractor) and claude.model == "claude-opus-5-5"


def test_settings_default_config_dir_is_the_repo_config():
    assert Settings().config_path.name == "config"
