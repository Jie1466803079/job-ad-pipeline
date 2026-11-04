from datetime import date

import pytest

from helpers import load_fixture
from jobpipe.sources import standardise
from jobpipe.sources.common import map_employment_type, map_salary_period, map_work_mode
from jobpipe.textutil import sha256_text

GH_TEXT = (
    "Join our data team in Sydney. This is a hybrid role with three days a week in our Sydney office.\n\n"
    "- Strong Python and SQL skills\n- Experience with AWS\n\n"
    "You must have full working rights in Australia.\n\nApplications close 31 October 2026."
)
LV_TEXT = (
    "Our analytics team is growing.\n\nWhat you'll need\n- Graduate degree in a quantitative field\n"
    "- Python or R\n\nWe are an equal opportunity employer."
)


def test_greenhouse_board_response():
    postings = standardise("greenhouse", load_fixture("greenhouse_board.json"), "Example GH")
    assert [p.source_id for p in postings] == ["7001001", "7001002"]
    first = postings[0]
    assert first.title == "Data Engineer"
    assert first.company == "Example GH"
    assert first.url == "https://job-boards.greenhouse.io/examplegh/jobs/7001001"
    assert first.text == GH_TEXT
    assert first.board.locations == ["Sydney, New South Wales, Australia", "Sydney"]
    assert first.board.deadline == date(2026, 10, 31)
    assert first.posted_at.isoformat() == "2026-09-20T22:33:35-04:00"
    assert first.text_hash == sha256_text(first.full_text)
    assert first.full_text.startswith("Data Engineer\n\nJoin our data team")


def test_greenhouse_single_job_response_matches_the_board_entry():
    board = load_fixture("greenhouse_board.json")
    single = standardise("greenhouse", board["jobs"][0], "Example GH")
    assert len(single) == 1
    assert single[0] == standardise("greenhouse", board, "Example GH")[0]


def test_lever_postings_response():
    postings = standardise("lever", load_fixture("lever_postings.json"), "Example LV")
    assert len(postings) == 1
    posting = postings[0]
    assert posting.source_id == "3f2b9a52-1c1e-4c55-9d37-1b7a3a8a0001"
    assert posting.title == "Graduate Data Analyst"
    assert posting.url == "https://jobs.lever.co/examplelv/3f2b9a52-1c1e-4c55-9d37-1b7a3a8a0001"
    assert posting.text == LV_TEXT
    assert posting.posted_at.date() == date(2026, 8, 27)
    board = posting.board
    assert (board.locations, board.country, board.work_mode, board.employment_type) == (
        ["Sydney"], "AU", "hybrid", "full_time")
    assert (board.salary_min, board.salary_max, board.salary_currency, board.salary_period) == (
        85000, 95000, "AUD", "year")


def test_lever_zero_salary_range_means_no_salary():
    job = load_fixture("lever_postings.json")[0]
    job["salaryRange"] = {"currency": "AUD", "interval": "per-year-salary", "min": 0, "max": 0}
    board = standardise("lever", [job], "Example LV")[0].board
    assert (board.salary_min, board.salary_max, board.salary_currency, board.salary_period) == (
        None, None, None, None)


def test_ashby_board_response_skips_unlisted_jobs():
    postings = standardise("ashby", load_fixture("ashby_board.json"), "Example AB")
    assert [p.title for p in postings] == ["Data Engineer"]
    posting = postings[0]
    assert posting.url == "https://jobs.ashbyhq.com/exampleab/7c9e6679-7425-40de-944b-e07fc1f90ae7"
    assert posting.text == "Build data pipelines for our finance products.\n\nSalary: $90,000 - $110,000 + super."
    board = posting.board
    assert board.locations == ["AU: Sydney (1 Example St)", "Sydney", "AU: Melbourne (2 Example Rd)", "Melbourne"]
    assert (board.country, board.work_mode, board.employment_type) == ("Australia", "hybrid", "full_time")
    assert (board.salary_min, board.salary_max, board.salary_currency, board.salary_period) == (
        90000, 110000, "AUD", "year")


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        standardise("workday", {}, "Example")


def test_wrong_shape_payload_raises():
    with pytest.raises(KeyError):
        standardise("lever", {"ok": False, "error": "Document not found"}, "Example LV")


@pytest.mark.parametrize("raw, expected", [
    ("Permanent - Full time", "full_time"),
    ("Max term contract - Full time", "contract"),
    ("FullTime", "full_time"),
    ("PartTime", "part_time"),
    ("Intern", "internship"),
    ("Graduate Program", "graduate_program"),
    (None, None),
])
def test_map_employment_type(raw, expected):
    assert map_employment_type(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("hybrid", "hybrid"), ("OnSite", "onsite"), ("Remote", "remote"), ("unspecified", None), (None, None)])
def test_map_work_mode(raw, expected):
    assert map_work_mode(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("per-year-salary", "year"), ("1 YEAR", "year"), ("1 HOUR", "hour"), ("per-month-salary", "month"),
    ("NONE", None)])
def test_map_salary_period(raw, expected):
    assert map_salary_period(raw) == expected
