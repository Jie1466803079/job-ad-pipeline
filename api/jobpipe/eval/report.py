"""The Markdown reports: one for each run, and a summary that compares the runs."""

from jobpipe.eval.score import agreement, injection_effects
from jobpipe.llm.schema import ROUTING_FIELDS


def share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({round(100 * part / whole)}%)" if whole else f"{part} of 0"


def seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.1f} s"


def method_label(doc: dict) -> str:
    if doc["provider"] == "rules":
        return "Rules baseline"
    if doc["provider"] == "fake":
        return "Fake extractor"
    return f"{doc['model']} ({doc['setting']})"


def wrong_fields(ad: dict) -> str:
    return ", ".join(name for name, right in ad["correct"].items() if not right) or "none"


def _changed(effect: dict) -> str:
    if effect["changed"] is None:
        return "not compared (an extraction failed)"
    return ", ".join(effect["changed"]) or "none"


def _render_unlabelled_run(doc: dict) -> str:
    m = doc["metrics"]
    n = m["ads"]
    prompt = f" Prompt version {doc['prompt']}." if doc["prompt"] else ""
    lines = [
        f"# {doc['run']}", "",
        f"{method_label(doc)} on all {n} ads, without labels, run on {doc['date'][:10]}.{prompt}", "",
        "These numbers do not measure accuracy: nobody has checked the values against the ads.", "",
        "## Routing", "",
        f"- Routed automatically: {share(m['auto_routed'], n)}: {m['routes']['tracked']} to the tracker and "
        f"{m['routes']['ineligible']} as not eligible.",
        f"- Sent to review: {share(m['routes']['review'], n)}.",
        f"- Failed extractions: {m['failed']}.", "",
        "## Why ads went to review", "",
        "Each ad counts once for every field that failed a check.", "",
    ]
    if m["review_fields"]:
        lines += ["| Field | Ads |", "|---|---|",
                  *[f"| {name} | {count} |" for name, count in m["review_fields"].items()], ""]
    else:
        lines += ["None.", ""]
    lines += ["## Cost and speed", "",
              f"US${m['cost_per_1000_usd']:.2f} per 1,000 ads; median {seconds(m['median_latency_ms'])} per ad.", ""]
    if m["injected"]:
        lines += ["## Copies with an injected instruction", "",
                  f"Followed the injected instruction: {m['injected_followed']} of {m['injected']}, routed "
                  f"automatically: {m['injected_followed_auto']}.", "",
                  "| Copy | Original route | Copy route | Changed fields |", "|---|---|---|---|",
                  *[f"| {effect['id']} | {effect['original_route']} | {effect['route']} | {_changed(effect)} |"
                    for effect in injection_effects(doc["ads"])], ""]
    return "\n".join(lines)


def render_run(doc: dict) -> str:
    if doc["split"] == "all":
        return _render_unlabelled_run(doc)
    m = doc["metrics"]
    n = m["ads"]
    prompt = f" Prompt version {doc['prompt']}." if doc["prompt"] else ""
    lines = [
        f"# {doc['run']}", "",
        f"{method_label(doc)} on the {doc['split']} split ({n} ads), run on {doc['date'][:10]}.{prompt}", "",
        "## Routing", "",
        f"- Routed automatically: {share(m['auto_routed'], n)}.",
        f"- With a wrong field among those: {share(m['auto_routed_wrong'], m['auto_routed'])}.",
        f"- Sent to review: {share(m['routes']['review'], n)}.",
        f"- Eligible ads routed as not eligible: {m['eligible_routed_ineligible']}. "
        f"Ineligible ads routed to the tracker: {m['ineligible_routed_tracked']}.",
        f"- Failed extractions: {m['failed']}.", "",
        "## Field accuracy", "", "| Field | Correct |", "|---|---|",
        *[f"| {name} | {share(count, n)} |" for name, count in m["field_accuracy"].items()], "",
        "## Cost and speed", "",
        f"US${m['cost_per_1000_usd']:.2f} per 1,000 ads; median {seconds(m['median_latency_ms'])} per ad.", "",
    ]
    if m["injected"]:
        lines += ["## Copies with an injected instruction", "",
                  f"Routed automatically with a wrong value: {m['injected_auto_wrong']} of {m['injected']}.", "",
                  "| Copy | Route | Wrong fields |", "|---|---|---|",
                  *[f"| {ad['id']} | {ad['route']} | {wrong_fields(ad)} |" for ad in doc["ads"] if ad["original"]], ""]
    wrong = [ad for ad in doc["ads"] if not ad["original"] and not all(ad["correct"].values())]
    lines += ["## Ads with a wrong field", ""]
    if wrong:
        lines += ["| Ad | Route | Wrong fields |", "|---|---|---|",
                  *[f"| {ad['id']} | {ad['route']} | {wrong_fields(ad)} |" for ad in wrong]]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def rank(doc: dict) -> tuple:
    """The order used to pick the daily model: wrong answers among ads routed automatically, then review, then cost."""
    m = doc["metrics"]
    wrong_share = m["auto_routed_wrong"] / m["auto_routed"] if m["auto_routed"] else 1.0
    return wrong_share, m["routes"]["review"] / max(m["ads"], 1), m["cost_per_1000_usd"], doc["run"]


def rank_unlabelled(doc: dict) -> tuple:
    """The order of runs without labels: the fewest sent to review, then cost."""
    m = doc["metrics"]
    return m["routes"]["review"] / max(m["ads"], 1), m["cost_per_1000_usd"], doc["run"]


def _unlabelled_summary(runs: list[dict]) -> list[str]:
    n = runs[0]["metrics"]["ads"]
    lines = [f"## All ads, without labels ({n} ads)", "",
             "These runs have no labels, so they say nothing about accuracy. They are listed by the share sent to "
             "review, then cost.", "",
             "| Method | Routed automatically | Sent to review | Failed | Cost per 1,000 ads | Median time per ad "
             "| Injected instruction followed | Prompt |",
             "|---|---|---|---|---|---|---|---|"]
    for doc in runs:
        m = doc["metrics"]
        lines.append(f"| {method_label(doc)} | {share(m['auto_routed'], m['ads'])} "
                     f"| {share(m['routes']['review'], m['ads'])} | {m['failed']} | US${m['cost_per_1000_usd']:.2f} "
                     f"| {seconds(m['median_latency_ms'])} | {m['injected_followed']} of {m['injected']} "
                     f"({m['injected_followed_auto']} routed automatically) | {doc['prompt'] or '-'} |")
    if len(runs) > 1:
        lines += ["", "How often two methods route an ad the same way, and give the same value for each field where "
                  "both extractions worked, compared by the scoring rules in eval/LABELLING.md. Agreement is not "
                  "accuracy: two methods can agree and both be wrong.", "",
                  "| Methods | Ads | Same route | Values compared | " + " | ".join(ROUTING_FIELDS) + " |",
                  "|---" * (len(ROUTING_FIELDS) + 4) + "|"]
        for index, doc in enumerate(runs):
            for other in runs[index + 1:]:
                result = agreement(doc, other)
                lines.append(f"| {method_label(doc)} vs {method_label(other)} | {result['ads']} | {result['routes']} "
                             f"| {result['compared']} | "
                             + " | ".join(str(result["fields"][name]) for name in ROUTING_FIELDS) + " |")
    lines.append("")
    return lines


def render_summary(docs: list[dict]) -> str:
    lines = ["# Evaluation results", "",
             "Written by `python -m jobpipe.eval.run` from the JSON files in this folder. Runs over all ads without "
             "labels are listed by the share sent to review, then cost. Runs on the dev and test splits, which are "
             "scored against hand labels, are listed in the order used to pick the daily model: the smallest share "
             "of ads with a wrong field among those routed automatically, then the fewest sent to review, then the "
             "lowest cost.", ""]
    unlabelled = sorted((doc for doc in docs if doc["split"] == "all"), key=rank_unlabelled)
    if unlabelled:
        lines += _unlabelled_summary(unlabelled)
    for split in ("dev", "test"):
        runs = sorted((doc for doc in docs if doc["split"] == split), key=rank)
        if not runs:
            continue
        n = runs[0]["metrics"]["ads"]
        lines += [f"## {split.capitalize()} split ({n} ads)", "",
                  "| Method | Routed automatically | Wrong among those | Sent to review | Cost per 1,000 ads "
                  "| Median time per ad | Prompt |",
                  "|---|---|---|---|---|---|---|"]
        for doc in runs:
            m = doc["metrics"]
            lines.append(f"| {method_label(doc)} | {share(m['auto_routed'], m['ads'])} "
                         f"| {share(m['auto_routed_wrong'], m['auto_routed'])} "
                         f"| {share(m['routes']['review'], m['ads'])} | US${m['cost_per_1000_usd']:.2f} "
                         f"| {seconds(m['median_latency_ms'])} | {doc['prompt'] or '-'} |")
        lines += ["", f"Correct values out of {n}:", "",
                  "| Method | " + " | ".join(ROUTING_FIELDS) + " |", "|---" * (len(ROUTING_FIELDS) + 1) + "|"]
        lines += [f"| {method_label(doc)} | " + " | ".join(str(doc["metrics"]["field_accuracy"][name])
                                                         for name in ROUTING_FIELDS) + " |" for doc in runs]
        injected = [doc for doc in runs if doc["metrics"]["injected"]]
        if injected:
            lines += ["", "Copies with an injected instruction that were routed automatically with a wrong value:", ""]
            lines += [f"- {method_label(doc)}: {doc['metrics']['injected_auto_wrong']} of "
                      f"{doc['metrics']['injected']}" for doc in injected]
        lines.append("")
    return "\n".join(lines)
