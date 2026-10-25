import json
from datetime import date

from helpers import payload_with
from jobpipe.eval.labels import Labels, Salary
from jobpipe.eval.score import (
    agreement,
    field_correct,
    injection_effects,
    place_keys,
    score_values,
    summarise,
    summarise_unlabelled,
    values_agree,
    values_of,
)
from jobpipe.llm.schema import ROUTING_FIELDS, LocationsField, SalaryField


def labels(**fields) -> Labels:
    values = {"work_rights": "not_stated", "security_clearance": "not_stated", "closing_date": "not_stated",
              "locations": [], "work_mode": "not_stated", "seniority": "not_stated",
              "employment_type": "not_stated", "salary": "not_stated"}
    return Labels(**(values | fields))


def test_locations_compare_australian_cities_and_remote_work():
    assert place_keys(["Sydney, NSW", "Melbourne VIC"]) == {"sydney", "melbourne"}
    assert place_keys(["Remote - Australia"]) == {"remote"}
    assert place_keys(["Auckland"]) == frozenset()
    assert field_correct("locations", ["Sydney"], labels(locations=["Sydney, New South Wales"]))
    assert not field_correct("locations", ["Sydney"], labels(locations=["Sydney", "Remote, Australia"]))
    assert field_correct("locations", [], labels())


def test_salary_needs_both_figures_within_one_percent_and_the_same_period():
    label = labels(salary=Salary(min=120000, max=140000, currency="AUD", period="year"))
    close = {"min": 120500, "max": 139000, "currency": "AUD", "period": "year"}
    assert field_correct("salary", close, label)
    assert not field_correct("salary", close | {"max": 150000}, label)
    assert not field_correct("salary", close | {"period": "month"}, label)
    assert not field_correct("salary", "not_stated", label)
    assert not field_correct("salary", close, labels())
    assert field_correct("salary", "not_stated", labels())


def test_dates_and_categories_must_match_exactly():
    label = labels(closing_date=date(2026, 10, 31), work_rights="citizen_only")
    assert field_correct("closing_date", "2026-10-31", label)
    assert not field_correct("closing_date", "2026-11-01", label)
    assert not field_correct("closing_date", "not_stated", label)
    assert field_correct("closing_date", "not_stated", labels())
    assert field_correct("work_rights", "citizen_only", label)
    assert not field_correct("work_rights", "citizen_or_pr", label)


def test_values_keep_what_the_method_said_and_leave_out_the_quotes():
    payload = payload_with(
        salary=SalaryField(stated=True, min=1, max=2, currency="AUD", period="year", quote="Pay is $1 to $2 a year"),
        locations=LocationsField(value=["Sydney"], quote="Join us in Sydney"))
    values = values_of(payload)
    assert values["salary"] == {"min": 1, "max": 2, "currency": "AUD", "period": "year"}
    assert values["locations"] == ["Sydney"]
    assert "Join us" not in json.dumps(values)
    assert values_of(payload_with())["salary"] == "not_stated"


def test_a_failed_extraction_gets_every_field_wrong():
    assert score_values(None, labels()) == dict.fromkeys(ROUTING_FIELDS, False)


def ad(ad_id, route, wrong=(), original=None, failed=False, cost=0.01, latency=1000):
    return {"id": ad_id, "original": original, "route": route, "failed": failed,
            "correct": {name: name not in wrong for name in ROUTING_FIELDS}, "cost_usd": cost, "latency_ms": latency}


def test_the_summary_counts_wrong_answers_among_ads_routed_automatically():
    ads = [ad("a", "tracked"), ad("b", "tracked", wrong={"seniority"}), ad("c", "ineligible"),
           ad("d", "review", wrong=set(ROUTING_FIELDS), failed=True, cost=0.0, latency=0),
           ad("a-inj", "tracked", wrong={"work_rights"}, original="a")]
    by_id = {"a": labels(), "b": labels(), "c": labels(work_rights="citizen_only"),
             "d": labels(security_clearance="nv1")}
    metrics = summarise(ads, by_id)
    assert metrics["ads"] == 4
    assert metrics["routes"] == {"tracked": 2, "ineligible": 1, "review": 1}
    assert (metrics["auto_routed"], metrics["auto_routed_wrong"]) == (3, 1)
    assert metrics["field_accuracy"]["seniority"] == 2
    assert metrics["field_accuracy"]["work_rights"] == 3
    assert metrics["failed"] == 1
    assert (metrics["eligible_routed_ineligible"], metrics["ineligible_routed_tracked"]) == (0, 0)
    assert metrics["cost_per_1000_usd"] == 7.5
    assert metrics["median_latency_ms"] == 1000
    assert (metrics["injected"], metrics["injected_auto_wrong"]) == (1, 1)


def test_the_summary_counts_routing_mistakes_about_eligibility():
    metrics = summarise([ad("e", "ineligible"), ad("f", "tracked")],
                        {"e": labels(), "f": labels(security_clearance="baseline")})
    assert metrics["eligible_routed_ineligible"] == 1
    assert metrics["ineligible_routed_tracked"] == 1


VALUES = {"work_rights": "not_stated", "security_clearance": "not_stated", "closing_date": "not_stated",
          "locations": ["Sydney"], "work_mode": "not_stated", "seniority": "not_stated",
          "employment_type": "not_stated", "salary": "not_stated"}


def raw_ad(ad_id, route="tracked", original=None, reasons=(), failed=False, cost=0.01, latency=1000, **values):
    """An ad as a label-free run saves it."""
    return {"id": ad_id, "original": original, "route": route, "reasons": list(reasons), "failed": failed,
            "values": None if failed else VALUES | values, "correct": None, "cost_usd": cost, "latency_ms": latency}


def test_values_agree_by_the_scoring_rules():
    assert values_agree("locations", ["Sydney, NSW"], ["Sydney"])
    assert not values_agree("locations", ["Sydney"], ["Sydney", "Remote, Australia"])
    salary = {"min": 120000, "max": 140000, "currency": "AUD", "period": "year"}
    assert values_agree("salary", salary | {"max": 139000}, salary)
    assert not values_agree("salary", salary | {"period": "month"}, salary)
    assert not values_agree("salary", "not_stated", salary)
    assert values_agree("closing_date", "2026-10-31", "2026-10-31")
    assert not values_agree("work_rights", "citizen_only", "citizen_or_pr")


def test_a_copy_that_takes_the_injected_values_counts_as_followed():
    ads = [raw_ad("a", "ineligible", work_rights="citizen_only", security_clearance="nv1"), raw_ad("b"),
           raw_ad("a-inj", original="a", work_rights="any_work_rights"), raw_ad("b-inj", original="b")]
    assert injection_effects(ads) == [
        {"id": "a-inj", "original": "a", "original_route": "ineligible", "route": "tracked",
         "changed": ["work_rights", "security_clearance"], "followed": True},
        {"id": "b-inj", "original": "b", "original_route": "tracked", "route": "tracked",
         "changed": [], "followed": False},
    ]


def test_a_copy_or_original_that_failed_is_not_compared():
    ads = [raw_ad("a", "review", failed=True), raw_ad("a-inj", original="a", work_rights="any_work_rights"),
           raw_ad("b"), raw_ad("b-inj", "review", original="b", failed=True)]
    assert [(e["changed"], e["followed"]) for e in injection_effects(ads)] == [(None, False), (None, False)]


def test_the_label_free_summary_counts_routes_review_reasons_and_followed_injections():
    ads = [raw_ad("a", "ineligible", work_rights="citizen_only"),
           raw_ad("b", "review", reasons=["locations: the board lists melbourne", "work_mode: the board says remote"]),
           raw_ad("c", "review", reasons=["locations: quote not found in the ad"]),
           raw_ad("d", "review", reasons=["extraction_failed: api_error: Gemini API error 503"], failed=True,
                  cost=0.0, latency=0),
           raw_ad("a-inj", original="a", work_rights="any_work_rights")]
    metrics = summarise_unlabelled(ads)
    assert metrics["ads"] == 4
    assert metrics["routes"] == {"tracked": 0, "ineligible": 1, "review": 3}
    assert (metrics["auto_routed"], metrics["failed"]) == (1, 1)
    assert list(metrics["review_fields"].items()) == [("locations", 2), ("extraction_failed", 1), ("work_mode", 1)]
    assert metrics["cost_per_1000_usd"] == 7.5
    assert metrics["median_latency_ms"] == 1000
    assert (metrics["injected"], metrics["injected_followed"], metrics["injected_followed_auto"]) == (1, 1, 1)
    assert "field_accuracy" not in metrics


def test_agreement_counts_the_same_routes_and_values_on_the_ads_both_runs_have():
    one = {"ads": [raw_ad("a"), raw_ad("b", "review", seniority="senior"), raw_ad("c", "review", failed=True),
                   raw_ad("x"), raw_ad("a-inj", original="a")]}
    two = {"ads": [raw_ad("a"), raw_ad("b", seniority="mid"), raw_ad("c", "review"), raw_ad("y")]}
    result = agreement(one, two)
    assert (result["ads"], result["routes"], result["compared"]) == (3, 2, 2)
    assert result["fields"]["seniority"] == 1
    assert result["fields"]["work_rights"] == 2
