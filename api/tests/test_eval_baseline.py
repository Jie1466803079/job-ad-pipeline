from datetime import date

import pytest

from helpers import posting_with
from jobpipe.checks import run_checks
from jobpipe.eval.baseline import RulesExtractor
from jobpipe.llm.schema import WorkRightsField
from jobpipe.routing import decide_route


def extract(text: str, title: str = "Data Engineer"):
    posting = posting_with(text, title=title)
    payload = RulesExtractor().extract(posting).payload
    return payload, decide_route(payload, run_checks(posting, payload, today=date(2026, 10, 15)))


def test_reads_citizenship_and_a_clearance_and_routes_the_ad_as_not_eligible():
    payload, decision = extract("We build autonomy software in Sydney.\n\n"
                                "Must be an Australian citizen and eligible to obtain an NV1 clearance.")
    assert payload.work_rights.value == "citizen_only"
    assert payload.security_clearance.value == "nv1"
    assert decision.route == "ineligible"


def test_a_clearance_on_its_own_means_citizens_only_and_the_lowest_level_counts():
    payload, decision = extract("You need an Australian Government security clearance at Baseline or NV1 level.")
    assert payload.security_clearance.value == "baseline"
    assert payload.work_rights.value == "citizen_only"
    assert decision.route == "ineligible"


def test_reads_pay_closing_date_work_mode_type_level_and_place():
    payload, decision = extract("This is a hybrid role with 3 days a week in our Sydney office.\n\n"
                                "Salary: $120,000 - $140,000 per annum plus super.\n\n"
                                "Applications close 31 October 2026.\n\n"
                                "This is a permanent full-time position.\n\n"
                                "You have 3+ years of experience with Python.")
    salary = payload.salary
    assert (salary.stated, salary.min, salary.max, salary.currency, salary.period) == (True, 120000, 140000,
                                                                                        "AUD", "year")
    assert payload.closing_date.value == "2026-10-31"
    assert payload.work_mode.value == "hybrid"
    assert payload.employment_type.value == "full_time"
    assert payload.seniority.value == "mid"
    assert payload.locations.value == ["Sydney"]
    assert payload.work_rights.value == "not_stated"
    assert decision.route == "tracked"


@pytest.mark.parametrize(("text", "value"), [
    ("You must have full working rights in Australia.", "any_work_rights"),
    ("We are unable to offer visa sponsorship.", "any_work_rights"),
    ("Visa sponsorship is available for this role.", "sponsorship_available"),
    ("Open to Australian citizens and permanent residents.", "citizen_or_pr"),
])
def test_reads_work_rights_phrases(text, value):
    payload, _ = extract(text)
    assert payload.work_rights.value == value


@pytest.mark.parametrize(("title", "value"), [
    ("Graduate Data Analyst", "graduate_or_entry"), ("Junior Data Engineer", "junior"),
    ("Senior Data Engineer", "senior"), ("Staff Engineer", "lead_or_above"), ("Data Engineer", "not_stated"),
])
def test_reads_the_level_from_the_title(title, value):
    payload, _ = extract("Build pipelines.", title=title)
    assert payload.seniority.value == value


def test_reads_pay_in_thousands_and_by_the_hour():
    assert extract("Pay: $120k - $140k + super.")[0].salary.max == 140000
    hourly = extract("Rate: $95 per hour.")[0].salary
    assert (hourly.min, hourly.max, hourly.period) == (95, 95, "hour")


def test_fields_it_cannot_settle_send_the_ad_to_review():
    payload, decision = extract("Applications close soon.\n\nThis role is fully remote.\n\n"
                                "You will work on-site in our lab.")
    assert (payload.closing_date.value, payload.closing_date.quote) == ("not_stated", "Applications close soon.")
    assert payload.work_mode.value == "not_stated" and payload.work_mode.quote
    assert decision.route == "review"
    assert any(reason.startswith("closing_date:") for reason in decision.reasons)


@pytest.mark.parametrize("text", [
    "We hire regardless of race, religion, citizenship or disability.",
    "We don\u2019t regard colour, religion, race, ancestry, citizenship or sex when we hire.",
])
def test_ignores_statements_against_discrimination(text):
    payload, decision = extract(text)
    assert payload.work_rights == WorkRightsField(value="not_stated", quote="")
    assert decision.route == "tracked"
