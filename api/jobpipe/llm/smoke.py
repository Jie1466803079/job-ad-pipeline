"""Send one sample ad to a real provider and print what comes back.

    make smoke PROVIDER=gemini      needs GEMINI_API_KEY in .env
    make smoke PROVIDER=claude      needs ANTHROPIC_API_KEY in .env
"""

import argparse
from datetime import UTC, date, datetime

from jobpipe.checks import run_checks
from jobpipe.configfiles import load_prices
from jobpipe.llm.factory import make_extractor
from jobpipe.llm.pricing import cost_usd
from jobpipe.models import BoardFields
from jobpipe.routing import decide_route
from jobpipe.settings import Settings
from jobpipe.sources.common import make_posting

SAMPLE_TEXT = """\
Join our data team in Sydney. This is a hybrid role with three days a week in our Sydney office.

- Strong Python and SQL skills
- Experience with AWS
- Exposure to Airflow is a bonus

You must have full working rights in Australia.

Salary: $95,000 - $110,000 plus super.

Applications close 31 October 2026."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one sample ad to a real LLM provider.")
    parser.add_argument("--provider", choices=["gemini", "claude"], required=True)
    parser.add_argument("--model", help="override GEMINI_MODEL or CLAUDE_MODEL")
    args = parser.parse_args()
    overrides: dict = {"llm_provider": args.provider}
    if args.model:
        overrides["gemini_model" if args.provider == "gemini" else "claude_model"] = args.model
    settings = Settings(**overrides)
    extractor = make_extractor(settings)
    posting = make_posting(source="greenhouse", source_id="smoke-1", company="Example", title="Data Engineer",
                           url="https://example.test/smoke", posted_at=datetime(2026, 10, 1, tzinfo=UTC),
                           text=SAMPLE_TEXT, board=BoardFields(locations=["Sydney"]))
    result = extractor.extract(posting)
    print(result.payload.model_dump_json(indent=2))
    checks = run_checks(posting, result.payload, today=date.today())
    for check in checks:
        if check.status != "na":
            print(f"{check.field:20} {check.name:18} {check.status:5} {check.item or ''} {check.reason}")
    decision = decide_route(result.payload, checks)
    prices = load_prices(settings.config_path / "prices.yaml")
    usage = result.usage
    cost = cost_usd(usage.model, usage.input_tokens, usage.output_tokens, prices, fallback_model=extractor.model)
    print(f"route: {decision.route} {decision.reasons}")
    print(f"model: {usage.model}  tokens in/out: {usage.input_tokens}/{usage.output_tokens}  "
          f"latency: {usage.latency_ms} ms  cost: {cost if cost is not None else 'no price'} USD")


if __name__ == "__main__":
    main()
