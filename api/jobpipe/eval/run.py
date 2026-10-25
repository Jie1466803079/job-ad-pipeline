"""Run one method over the dev or test ads and score it against the labels, or over every ad without labels.

    python -m jobpipe.eval.run --provider rules --split dev
    python -m jobpipe.eval.run --provider gemini --split all                   every ad and copy, no labels needed
    python -m jobpipe.eval.run --provider gemini --model gemini-3.8-flash --thinking-level low --split dev
    python -m jobpipe.eval.run --provider claude --effort low --split dev     needs ANTHROPIC_API_KEY
    python -m jobpipe.eval.run --rescore                                       score every saved run again

A run writes eval/results/<run>.json and <run>.md and rewrites eval/results/summary.md. A test run also runs
the copies with an injected line. The test split is scored once per method, so a second test run of the same
method is refused; after fixing a label, --rescore recomputes every score from the saved values. A run with
--split all reads every ad and every copy and no labels, so its numbers say nothing about accuracy.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from jobpipe.checks import run_checks
from jobpipe.configfiles import Price, load_prices
from jobpipe.eval.baseline import RulesExtractor
from jobpipe.eval.files import EVAL_DIR, Snapshot, load_snapshot, load_split
from jobpipe.eval.labels import Labels, read_labels
from jobpipe.eval.report import render_run, render_summary
from jobpipe.eval.score import score_values, summarise, summarise_unlabelled, values_of
from jobpipe.llm.base import ExtractionError, Extractor
from jobpipe.llm.factory import make_extractor
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.pricing import cost_usd
from jobpipe.llm.prompt import SYSTEM_PROMPT
from jobpipe.routing import decide_route
from jobpipe.settings import DEFAULT_CONFIG_DIR, Settings


def setting_of(extractor: Extractor) -> str | None:
    """The thinking level or effort an LLM ran at. The rules and the fake extractor have none."""
    if extractor.provider == "gemini":
        return extractor.thinking_level or "default"
    if extractor.provider == "claude":
        return extractor.effort
    return None


def run_name(split: str, extractor: Extractor) -> str:
    if extractor.provider in ("rules", "fake"):
        return f"{split}_{extractor.provider}"
    return f"{split}_{extractor.provider}_{extractor.model}_{setting_of(extractor)}"


def prompt_version() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def score_ad(snapshot: Snapshot, extractor: Extractor, labels: dict[str, Labels] | None,
             prices: dict[str, Price]) -> dict:
    """Extract, check and route one ad as the pipeline does, then score it if there are labels. Nothing from the ad
    text is kept."""
    posting = snapshot.posting
    payload, usage, error = None, None, None
    try:
        result = extractor.extract(posting)
        payload, usage = result.payload, result.usage
    except ExtractionError as exc:
        usage, error = exc.usage, f"{exc.kind}: {exc}"
    except Exception as exc:  # a network failure or SDK surprise must not stop the run
        error = f"api_error: {type(exc).__name__}: {exc}"
    checks = run_checks(posting, payload, today=snapshot.fetched_on) if payload else []
    decision = decide_route(payload, checks, error)
    values = values_of(payload) if payload else None
    cost = (cost_usd(usage.model, usage.input_tokens, usage.output_tokens, prices, fallback_model=extractor.model)
            if usage else 0.0)
    return {
        "id": snapshot.id, "original": snapshot.altered_from, "route": decision.route,
        "reasons": decision.reasons, "failed": payload is None, "values": values,
        "correct": score_values(values, labels[snapshot.altered_from or snapshot.id]) if labels is not None else None,
        "input_tokens": usage.input_tokens if usage else 0, "output_tokens": usage.output_tokens if usage else 0,
        "latency_ms": usage.latency_ms if usage else 0, "cost_usd": cost or 0.0,
    }


def write_results(results_dir: Path, doc: dict) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{doc['run']}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    (results_dir / f"{doc['run']}.md").write_text(render_run(doc), encoding="utf-8")


def write_summary(results_dir: Path) -> None:
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(results_dir.glob("*.json"))]
    (results_dir / "summary.md").write_text(render_summary(docs), encoding="utf-8")


def _labels_for(eval_dir: Path, needed: set[str], report: Callable[[str], None]) -> dict[str, Labels] | None:
    if not (eval_dir / "labels.csv").exists():
        report("eval/labels.csv does not exist yet. Run make eval-sample first.")
        return None
    labels, _, problems = read_labels(eval_dir / "labels.csv")
    missing = sorted(needed - set(labels))
    for problem in problems:
        report(problem)
    if missing:
        report(f"Label these ads first: {', '.join(missing)}")
    return None if problems or missing else labels


def evaluate(eval_dir: Path, split_name: str, extractor: Extractor, prices: dict[str, Price], concurrency: int = 4,
             now: Callable[[], datetime] = lambda: datetime.now(UTC), report: Callable[[str], None] = print) -> int:
    results_dir = eval_dir / "results"
    name = run_name(split_name, extractor)
    if split_name == "test" and (results_dir / f"{name}.json").exists():
        report(f"{name} has already been scored on the test split, which is scored once per method. "
               "To recompute its scores after fixing a label, use --rescore.")
        return 1
    if extractor.model not in prices:
        report(f"config/prices.yaml has no price for {extractor.model}. Add one before running.")
        return 1
    if not (eval_dir / "split.json").exists():
        report("eval/split.json does not exist yet. Run make eval-sample first.")
        return 1
    split = load_split(eval_dir)
    if split_name == "all":
        ids, labels = sorted(split.dev + split.test) + sorted(split.injected), None
    else:
        ids = split.dev if split_name == "dev" else split.test + list(split.injected)
        labels = _labels_for(eval_dir, {split.injected.get(ad_id, ad_id) for ad_id in ids}, report)
        if labels is None:
            return 1
    snapshots = [load_snapshot(eval_dir, ad_id) for ad_id in ids]
    started = now()

    def one(snapshot: Snapshot) -> dict:
        ad = score_ad(snapshot, extractor, labels, prices)
        report(f"{ad['id']}: {ad['route']}" + (" (extraction failed)" if ad["failed"] else ""))
        return ad

    with ThreadPoolExecutor(max_workers=max(concurrency, 1)) as pool:
        ads = list(pool.map(one, snapshots))
    if all(ad["failed"] for ad in ads):
        report(f"Every extraction failed, so nothing was written. The first error: {ads[0]['reasons'][0]}")
        return 1
    llm = extractor.provider not in ("rules", "fake")
    doc = {"run": name, "split": split_name, "provider": extractor.provider, "model": extractor.model,
           "setting": setting_of(extractor), "prompt": prompt_version() if llm else None,
           "date": started.isoformat(),
           "metrics": summarise(ads, labels) if labels is not None else summarise_unlabelled(ads), "ads": ads}
    write_results(results_dir, doc)
    write_summary(results_dir)
    m = doc["metrics"]
    outcome = (f"{m['auto_routed_wrong']} of them with a wrong field" if labels is not None
               else f"{m['routes']['review']} sent to review")
    report(f"{name}: {m['auto_routed']} of {m['ads']} ads routed automatically, {outcome}. "
           f"Report: {results_dir / (name + '.md')}")
    return 0


def rescore(eval_dir: Path, report: Callable[[str], None] = print) -> int:
    results_dir = eval_dir / "results"
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(results_dir.glob("*.json"))]
    docs = [doc for doc in docs if doc["split"] != "all"]  # runs without labels have nothing to rescore
    needed = {ad["original"] or ad["id"] for doc in docs for ad in doc["ads"]}
    labels = _labels_for(eval_dir, needed, report)
    if labels is None:
        return 1
    for doc in docs:
        for ad in doc["ads"]:
            ad["correct"] = score_values(ad["values"], labels[ad["original"] or ad["id"]])
        doc["metrics"] = summarise(doc["ads"], labels)
        write_results(results_dir, doc)
    if results_dir.exists():
        write_summary(results_dir)
    report(f"Scored {len(docs)} runs again with the current labels.")
    return 0


def extractor_from(args: argparse.Namespace) -> Extractor:
    if args.provider == "rules":
        return RulesExtractor()
    if args.provider == "fake":
        return FakeExtractor()
    overrides: dict = {"llm_provider": args.provider}
    if args.model:
        overrides["gemini_model" if args.provider == "gemini" else "claude_model"] = args.model
    if args.thinking_level:
        overrides["gemini_thinking_level"] = args.thinking_level
    if args.effort:
        overrides["claude_effort"] = args.effort
    return make_extractor(Settings(**overrides))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one method over the dev or test ads and score it.")
    parser.add_argument("--provider", choices=["gemini", "claude", "rules", "fake"])
    parser.add_argument("--model", help="instead of GEMINI_MODEL or CLAUDE_MODEL")
    parser.add_argument("--thinking-level", help="Gemini only, for example low or high")
    parser.add_argument("--effort", help="Claude only, for example low or high")
    parser.add_argument("--split", choices=["dev", "test", "all"])
    parser.add_argument("--concurrency", type=int, default=4, help="ads sent at the same time (default 4)")
    parser.add_argument("--rescore", action="store_true", help="score every saved run again with the current labels")
    parser.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    args = parser.parse_args(argv)
    if args.rescore:
        return rescore(args.eval_dir)
    if not args.provider or not args.split:
        parser.error("give --provider and --split, or --rescore")
    try:
        extractor = extractor_from(args)
    except RuntimeError as exc:
        print(exc)
        return 1
    return evaluate(args.eval_dir, args.split, extractor, load_prices(DEFAULT_CONFIG_DIR / "prices.yaml"),
                    args.concurrency)


if __name__ == "__main__":
    sys.exit(main())
