import csv
import json
from datetime import UTC, date, datetime

import pytest

from helpers import payload_with, posting_with
from jobpipe.configfiles import Price
from jobpipe.eval.baseline import RulesExtractor
from jobpipe.eval.files import Snapshot, Split
from jobpipe.eval.labels import COLUMNS
from jobpipe.eval.report import render_summary
from jobpipe.eval.run import evaluate, main, rescore, run_name
from jobpipe.eval.sample import inject, write_sample
from jobpipe.llm.base import ExtractionError
from jobpipe.llm.claude import ClaudeExtractor
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.gemini import GeminiExtractor
from jobpipe.llm.schema import ROUTING_FIELDS, LocationsField

PRICES = {"fake-1": Price(input=1.0, output=2.0), "rules-1": Price(input=0.0, output=0.0)}
TEXT = "Join our data team in Sydney."


def label_all(eval_dir, changes=None):
    """Fill in every row of labels.csv: Sydney, and not_stated for the rest, with changes for some ids."""
    path = eval_dir / "labels.csv"
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row.update(dict.fromkeys(ROUTING_FIELDS, "not_stated") | {"locations": "Sydney"}
                   | (changes or {}).get(row["id"], {}))
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def eval_dir(tmp_path):
    directory = tmp_path / "eval"
    postings = {f"ad00{n}": posting_with(f"Ad {n}. {TEXT}", source_id=str(n)) for n in range(1, 5)}
    snapshots = [Snapshot(id=ad_id, group="general", fetched_on=date(2026, 10, 15), posting=posting)
                 for ad_id, posting in postings.items()]
    snapshots.append(Snapshot(id="ad003-inj", group="general", fetched_on=date(2026, 10, 15),
                              posting=inject(postings["ad003"]), altered_from="ad003"))
    write_sample(directory, snapshots, Split(seed=1, dev=["ad001", "ad002"], test=["ad003", "ad004"],
                                             injected={"ad003-inj": "ad003"}))
    label_all(directory, {"ad002": {"locations": "Melbourne"}})
    return directory


def answers(posting):
    if posting.source_id == "4":
        return ExtractionError("api_error", "Gemini API error 503: overloaded")
    return payload_with(locations=LocationsField(value=["Sydney"], quote=TEXT))


def results(eval_dir, name):
    return json.loads((eval_dir / "results" / f"{name}.json").read_text(encoding="utf-8"))


def test_a_dev_run_routes_and_scores_each_ad_and_writes_the_reports(eval_dir):
    lines = []
    code = evaluate(eval_dir, "dev", FakeExtractor(answers), PRICES, report=lines.append,
                    now=lambda: datetime(2026, 10, 16, tzinfo=UTC))
    assert code == 0
    doc = results(eval_dir, "dev_fake")
    assert [ad["id"] for ad in doc["ads"]] == ["ad001", "ad002"]
    assert [ad["route"] for ad in doc["ads"]] == ["tracked", "tracked"]
    assert doc["ads"][1]["correct"]["locations"] is False
    metrics = doc["metrics"]
    assert (metrics["auto_routed"], metrics["auto_routed_wrong"]) == (2, 1)
    assert metrics["cost_per_1000_usd"] == 1.4  # 1,000 tokens in at $1 and 200 out at $2 per million
    assert doc["date"].startswith("2026-10-16")
    assert (eval_dir / "results" / "dev_fake.md").exists()
    assert "Fake extractor" in (eval_dir / "results" / "summary.md").read_text(encoding="utf-8")
    assert "dev_fake: 2 of 2 ads routed automatically, 1 of them with a wrong field." in lines[-1]


def test_results_never_hold_ad_text(eval_dir):
    evaluate(eval_dir, "dev", FakeExtractor(answers), PRICES, report=lambda line: None)
    saved = (eval_dir / "results" / "dev_fake.json").read_text(encoding="utf-8")
    assert "quote" not in saved
    assert TEXT not in saved


def test_a_failed_extraction_is_counted_and_the_run_goes_on(eval_dir):
    assert evaluate(eval_dir, "test", FakeExtractor(answers), PRICES, report=lambda line: None) == 0
    doc = results(eval_dir, "test_fake")
    by_id = {ad["id"]: ad for ad in doc["ads"]}
    assert sorted(by_id) == ["ad003", "ad003-inj", "ad004"]
    failed = by_id["ad004"]
    assert (failed["failed"], failed["route"], failed["values"]) == (True, "review", None)
    assert failed["reasons"] == ["extraction_failed: api_error: Gemini API error 503: overloaded"]
    metrics = doc["metrics"]
    assert (metrics["ads"], metrics["failed"], metrics["injected"], metrics["injected_auto_wrong"]) == (2, 1, 1, 0)


def test_the_test_split_is_scored_once_per_method(eval_dir):
    extractor = FakeExtractor(answers)
    assert evaluate(eval_dir, "test", extractor, PRICES, report=lambda line: None) == 0
    calls = len(extractor.calls)
    lines = []
    assert evaluate(eval_dir, "test", extractor, PRICES, report=lines.append) == 1
    assert len(extractor.calls) == calls
    assert "already been scored on the test split" in lines[0]


def test_unlabelled_ads_stop_the_run_before_any_call(eval_dir):
    label_all(eval_dir, {"ad001": dict.fromkeys(ROUTING_FIELDS, "")})
    extractor, lines = FakeExtractor(answers), []
    assert evaluate(eval_dir, "dev", extractor, PRICES, report=lines.append) == 1
    assert extractor.calls == []
    assert lines == ["Label these ads first: ad001"]


def test_a_run_in_which_every_extraction_fails_writes_nothing(eval_dir):
    def no_key(posting):
        return ExtractionError("api_error", "Claude API error 401: invalid x-api-key")

    lines = []
    assert evaluate(eval_dir, "dev", FakeExtractor(no_key), PRICES, report=lines.append) == 1
    assert not (eval_dir / "results").exists()
    assert "Every extraction failed" in lines[-1]


def test_a_model_without_a_price_is_refused(eval_dir):
    lines = []
    assert evaluate(eval_dir, "dev", FakeExtractor(answers, model="fake-2"), PRICES, report=lines.append) == 1
    assert lines == ["config/prices.yaml has no price for fake-2. Add one before running."]


def test_a_run_before_the_sample_is_drawn_says_what_to_do(tmp_path):
    lines = []
    assert evaluate(tmp_path / "eval", "dev", FakeExtractor(answers), PRICES, report=lines.append) == 1
    assert lines == ["eval/split.json does not exist yet. Run make eval-sample first."]


def test_rescore_uses_the_current_labels_without_calling_the_model(eval_dir):
    extractor = FakeExtractor(answers)
    evaluate(eval_dir, "dev", extractor, PRICES, report=lambda line: None)
    calls = len(extractor.calls)
    label_all(eval_dir)  # ad002 is Sydney after all
    assert rescore(eval_dir, report=lambda line: None) == 0
    assert results(eval_dir, "dev_fake")["metrics"]["auto_routed_wrong"] == 0
    assert len(extractor.calls) == calls


def test_run_names_carry_the_model_and_its_setting():
    assert run_name("dev", GeminiExtractor(None, "gemini-3.8-flash", "low")) == "dev_gemini_gemini-3.8-flash_low"
    assert run_name("dev", GeminiExtractor(None, "gemini-3.8-flash")) == "dev_gemini_gemini-3.8-flash_default"
    assert run_name("test", ClaudeExtractor(None, "claude-opus-5-5", "low")) == "test_claude_claude-opus-5-5_low"
    assert run_name("dev", RulesExtractor()) == "dev_rules"


def test_the_command_runs_the_rules_baseline(eval_dir, capsys):
    assert main(["--provider", "rules", "--split", "dev", "--eval-dir", str(eval_dir)]) == 0
    assert results(eval_dir, "dev_rules")["provider"] == "rules"
    assert "Rules baseline" in (eval_dir / "results" / "summary.md").read_text(encoding="utf-8")


def summary_doc(run, wrong, review, cost):
    metrics = {"ads": 10, "auto_routed": 10 - review, "auto_routed_wrong": wrong,
               "routes": {"tracked": 10 - review, "ineligible": 0, "review": review},
               "cost_per_1000_usd": cost, "median_latency_ms": 1000, "injected": 0, "injected_auto_wrong": 0,
               "field_accuracy": dict.fromkeys(ROUTING_FIELDS, 10)}
    return {"run": run, "split": "dev", "provider": "gemini", "model": run, "setting": "low", "prompt": "abc",
            "metrics": metrics}


def test_the_summary_lists_runs_in_the_order_used_to_pick_the_daily_model():
    text = render_summary([summary_doc("cheap-but-wrong", 2, 1, 1.0), summary_doc("careful", 0, 4, 9.0),
                           summary_doc("careful-and-cheap", 0, 4, 2.0)])
    order = [text.index(f"| {name} (low) |") for name in ("careful-and-cheap", "careful", "cheap-but-wrong")]
    assert order == sorted(order)
