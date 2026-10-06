from datetime import UTC, date, datetime

import pytest

from helpers import SAMPLE_AD, payload_with, posting_with
from jobpipe.checks import cities_in, numbers_in, run_checks, verified_closing_date
from jobpipe.llm.schema import (
    ClearanceField,
    ClosingDateField,
    EmploymentField,
    LocationsField,
    SalaryField,
    SkillItem,
    WorkModeField,
    WorkRightsField,
    not_stated_payload,
)
from jobpipe.models import BoardFields

TODAY = date(2026, 10, 6)
SEPT = datetime(2026, 9, 20, tzinfo=UTC)
NOV = datetime(2026, 11, 5, tzinfo=UTC)


def get(results, field, name):
    return next(c for c in results if c.field == field and c.name == name)


def checks_for(payload, ad=SAMPLE_AD, **posting_args):
    return run_checks(posting_with(ad, **posting_args), payload, TODAY)


def test_nothing_stated_passes_every_quote_check():
    results = checks_for(not_stated_payload())
    assert {c.status for c in results if c.name == "quote_found"} == {"pass"}
    assert {c.status for c in results if c.name != "quote_found"} == {"na"}


def test_quote_must_appear_in_the_ad():
    payload = payload_with(work_mode=WorkModeField(value="hybrid", quote="fully remote role"))
    assert get(checks_for(payload), "work_mode", "quote_found").status == "fail"


def test_quote_matching_ignores_curly_quotes_dashes_and_line_breaks():
    ad = "We offer a \u201cflexible\u201d hybrid model \u2013 three days\nin the office."
    payload = payload_with(work_mode=WorkModeField(value="hybrid",
                                                   quote='a "flexible" hybrid model - three days in the office'))
    check = get(checks_for(payload, ad=ad), "work_mode", "quote_found")
    assert check.status == "pass"
    start, end = check.span
    assert posting_with(ad).full_text[start:end].startswith("a \u201cflexible\u201d")


def test_a_quote_for_a_not_stated_value_fails():
    payload = payload_with(work_rights=WorkRightsField(value="not_stated", quote="Applications close 31 October 2026."))
    assert get(checks_for(payload), "work_rights", "quote_found").status == "fail"


@pytest.mark.parametrize("value, quote, expected", [
    ("citizen_or_pr", "Applicants must be Australian citizens or permanent residents.", "pass"),
    ("citizen_only", "Applicants must be Australian citizens or permanent residents.", "fail"),
    ("citizen_only", "You must hold an NV1 clearance.", "pass"),
    ("sponsorship_available", "We are unable to offer visa sponsorship.", "fail"),
    ("any_work_rights", "Applications close 31 October 2026.", "fail"),
])
def test_work_rights_value_must_match_its_quote(value, quote, expected):
    payload = payload_with(work_rights=WorkRightsField(value=value, quote=quote))
    assert get(checks_for(payload), "work_rights", "matches_quote").status == expected


@pytest.mark.parametrize("value, expected", [("nv1", "pass"), ("nv2", "fail"), ("baseline", "fail"), ("other", "pass")])
def test_clearance_level_must_appear_in_the_quote(value, expected):
    payload = payload_with(security_clearance=ClearanceField(value=value, quote="You must hold an NV1 clearance."))
    assert get(checks_for(payload), "security_clearance", "matches_quote").status == expected


@pytest.mark.parametrize("value, quote, posted, expected", [
    ("2026-10-31", "Applications close 31 October 2026.", SEPT, "pass"),
    ("2026-11-01", "Applications close 31 October 2026.", SEPT, "fail"),
    ("31/10/2026", "Applications close 31 October 2026.", SEPT, "fail"),
    ("2026-10-31", "Applications close 31 October", SEPT, "pass"),
    ("2026-10-31", "Applications close 31 October", NOV, "fail"),
])
def test_closing_date_must_match_its_quote(value, quote, posted, expected):
    payload = payload_with(closing_date=ClosingDateField(value=value, quote=quote))
    assert get(checks_for(payload, posted=posted), "closing_date", "matches_quote").status == expected


@pytest.mark.parametrize("low, high, expected", [(120000, 140000, "pass"), (120000, 150000, "fail"),
                                                 (140000, 120000, "fail")])
def test_salary_figures_must_match_the_quote(low, high, expected):
    payload = payload_with(salary=SalaryField(stated=True, min=low, max=high, currency="AUD", period="year",
                                              quote="Salary: $120,000 - $140,000 + super."))
    assert get(checks_for(payload), "salary", "matches_quote").status == expected


def test_numbers_in_reads_thousands_and_ranges():
    assert {120000, 140000} <= set(numbers_in("120-140k"))
    assert 95500 in numbers_in("a$95.5k")
    assert 120000 in numbers_in("$120,000 to $140,000")


def test_extracted_values_must_agree_with_the_board():
    board = BoardFields(locations=["Melbourne"], work_mode="remote", employment_type="full_time",
                        deadline=date(2026, 11, 7), salary_min=100000, salary_max=110000)
    payload = payload_with(
        locations=LocationsField(value=["Sydney"], quote="Join our data team in Sydney."),
        work_mode=WorkModeField(value="hybrid", quote="This is a hybrid role."),
        employment_type=EmploymentField(value="graduate_program", quote="Join our data team in Sydney."),
        closing_date=ClosingDateField(value="2026-10-31", quote="Applications close 31 October 2026."),
        salary=SalaryField(stated=True, min=120000, max=140000, currency="AUD", period="year",
                           quote="Salary: $120,000 - $140,000 + super."),
    )
    results = checks_for(payload, board=board)
    assert get(results, "locations", "agrees_with_board").status == "fail"
    assert get(results, "work_mode", "agrees_with_board").status == "fail"
    assert get(results, "employment_type", "agrees_with_board").status == "pass"
    assert get(results, "closing_date", "agrees_with_board").status == "fail"
    assert get(results, "salary", "agrees_with_board").status == "fail"


def test_board_agreement_is_not_applicable_without_board_values():
    payload = payload_with(work_mode=WorkModeField(value="hybrid", quote="This is a hybrid role."))
    assert get(checks_for(payload), "work_mode", "agrees_with_board").status == "na"


def test_cities_in_finds_known_cities():
    assert cities_in(["AU: Sydney (1 Example St)", "Remote, Australia"]) == {"sydney"}


def test_skills_are_checked_one_by_one():
    payload = payload_with(required_skills=[SkillItem(skill="Python", quote="Strong Python skills are essential."),
                                            SkillItem(skill="Rust", quote="Rust experience required")])
    skills = [c for c in checks_for(payload) if c.field == "required_skills"]
    assert [(c.item, c.status) for c in skills] == [("Python", "pass"), ("Rust", "fail")]


def test_verified_closing_date():
    good = payload_with(closing_date=ClosingDateField(value="2026-10-31", quote="Applications close 31 October 2026."))
    assert verified_closing_date(good, checks_for(good)) == date(2026, 10, 31)
    bad = payload_with(closing_date=ClosingDateField(value="2026-11-30", quote="Applications close 31 October 2026."))
    assert verified_closing_date(bad, checks_for(bad)) is None
