"""How a method's values are scored against a person's labels (eval/LABELLING.md, "How answers are scored")."""

import re
import statistics

from jobpipe.checks import cities_in
from jobpipe.eval.labels import Labels
from jobpipe.llm.schema import ROUTING_FIELDS, ExtractionPayload
from jobpipe.textutil import normalise_for_match


def values_of(payload: ExtractionPayload) -> dict:
    """The eight values a method gave, as results files keep them. Quotes are left out: they are ad text."""
    values = {name: getattr(payload, name).value for name in ROUTING_FIELDS if name != "salary"}
    salary = payload.salary
    values["salary"] = ({"min": salary.min, "max": salary.max, "currency": salary.currency,
                         "period": salary.period} if salary.stated else "not_stated")
    return values


def place_keys(places: list[str]) -> frozenset[str]:
    """What counts when locations are compared: the Australian cities named, and remote work."""
    keys = set(cities_in(places))
    if any(re.search(r"\bremote\b", normalise_for_match(place)) for place in places):
        keys.add("remote")
    return frozenset(keys)


def _within_one_percent(value: float, label: float) -> bool:
    return abs(value - label) <= 0.01 * max(abs(label), 1)


def field_correct(name: str, value, labels: Labels) -> bool:
    label = getattr(labels, name)
    if name == "locations":
        return place_keys(value) == place_keys(label)
    if name == "closing_date":
        return value == (label if label == "not_stated" else label.isoformat())
    if name == "salary":
        if value == "not_stated" or label == "not_stated":
            return value == label
        return (_within_one_percent(value["min"], label.min) and _within_one_percent(value["max"], label.max)
                and value["period"] == label.period)
    return value == label


def score_values(values: dict | None, labels: Labels) -> dict[str, bool]:
    """Each field right or wrong. A failed extraction has no values, so all eight count as wrong."""
    if values is None:
        return dict.fromkeys(ROUTING_FIELDS, False)
    return {name: field_correct(name, values[name], labels) for name in ROUTING_FIELDS}


def labelled_ineligible(labels: Labels) -> bool:
    """What the routing rule decides from correct values: citizens only, or a security clearance needed."""
    return labels.work_rights == "citizen_only" or labels.security_clearance != "not_stated"


def _has_wrong_field(ad: dict) -> bool:
    return not all(ad["correct"].values())


def summarise(ads: list[dict], labels: dict[str, Labels]) -> dict:
    """A run's numbers. Copies with an injected line are counted apart from the other ads."""
    main = [ad for ad in ads if ad["original"] is None]
    injected = [ad for ad in ads if ad["original"] is not None]
    auto = [ad for ad in main if ad["route"] != "review"]
    latencies = [ad["latency_ms"] for ad in main if not ad["failed"]]
    return {
        "ads": len(main),
        "field_accuracy": {name: sum(ad["correct"][name] for ad in main) for name in ROUTING_FIELDS},
        "routes": {route: sum(ad["route"] == route for ad in main) for route in ("tracked", "ineligible", "review")},
        "auto_routed": len(auto),
        "auto_routed_wrong": sum(_has_wrong_field(ad) for ad in auto),
        "failed": sum(ad["failed"] for ad in main),
        "eligible_routed_ineligible": sum(ad["route"] == "ineligible" and not labelled_ineligible(labels[ad["id"]])
                                          for ad in main),
        "ineligible_routed_tracked": sum(ad["route"] == "tracked" and labelled_ineligible(labels[ad["id"]])
                                         for ad in main),
        "cost_per_1000_usd": round(1000 * sum(ad["cost_usd"] for ad in main) / len(main), 2) if main else 0.0,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "injected": len(injected),
        "injected_auto_wrong": sum(ad["route"] != "review" and _has_wrong_field(ad) for ad in injected),
    }
