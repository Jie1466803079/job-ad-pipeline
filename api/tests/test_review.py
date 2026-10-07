import json
from datetime import UTC, date, datetime

import pytest

from helpers import good_greenhouse_payload, greenhouse_posting, payload_with
from jobpipe import review
from jobpipe.checks import run_checks
from jobpipe.llm.schema import SalaryField, SkillItem


def stored(posting, payload, extraction_id: int = 1) -> dict:
    """An extraction row as it comes back from Postgres: JSON fields, spans as lists."""
    checks = run_checks(posting, payload, today=date(2026, 10, 6))
    return {"id": extraction_id, "provider": "fake", "model": "fake-1", "route": "tracked", "reasons": [],
            "created_at": datetime(2026, 10, 7, 7, 0, tzinfo=UTC), "fit": None,
            "fields": json.loads(payload.model_dump_json()),
            "checks": json.loads(json.dumps([check.model_dump() for check in checks]))}


def posting_row(posting, **overrides) -> dict:
    row = {"id": 1, "company": "Example GH", "title": posting.title, "url": posting.url, "source": posting.source,
           "status": "tracked", "closing_date": None, "closed_at": None, "posted_at": posting.posted_at,
           "skip_reason": None, "text": posting.text, "text_deleted_at": None}
    return row | overrides


def test_field_views_carry_spans_corrections_and_options():
    posting = greenhouse_posting()
    extraction = stored(posting, good_greenhouse_payload())
    edits = [{"work_rights": "citizen_or_pr"}]
    views = {view["name"]: view for view in review.field_views(extraction["fields"], extraction["checks"], edits)}
    rights = views["work_rights"]
    assert (rights["value"], rights["extracted"], rights["edited"]) == ("citizen_or_pr", "any_work_rights", True)
    start, end = rights["span"]
    assert posting.full_text[start:end] == "You must have full working rights in Australia."
    assert [check["name"] for check in rights["checks"]] == ["quote_found", "matches_quote", "agrees_with_board"]
    assert rights["options"][0] == "citizen_only"
    salary = views["salary"]
    assert salary["span"] is None and salary["options"] is None and salary["edited"] is False
    assert salary["value"] == {"stated": False, "min": 0, "max": 0, "currency": "", "period": "not_stated"}
    assert views["locations"]["value"] == ["Sydney"]


def test_later_corrections_win_and_salary_keeps_its_quote():
    payload = payload_with(salary=SalaryField(stated=True, min=100000, max=120000, currency="AUD", period="year",
                                              quote="$100k - $120k"))
    fields = json.loads(payload.model_dump_json())
    salary = {"stated": True, "min": 110000, "max": 130000, "currency": "AUD", "period": "year"}
    current, edited = review.apply_edits(fields, [{"work_mode": "remote"},
                                                  {"work_mode": "hybrid", "salary": salary}])
    assert current["work_mode"]["value"] == "hybrid"
    assert current["salary"] == salary | {"quote": "$100k - $120k"}
    assert edited == {"work_mode", "salary"}
    assert fields["work_mode"]["value"] == "not_stated"


def test_skill_views_mark_skills_whose_quote_was_not_found():
    posting = greenhouse_posting()
    payload = payload_with(required_skills=[SkillItem(skill="Python", quote="Strong Python and SQL skills"),
                                            SkillItem(skill="Rust", quote="Rust experience")])
    extraction = stored(posting, payload)
    skills = review.skill_views(extraction["fields"], extraction["checks"])
    python, rust = skills["required"]
    start, end = python["span"]
    assert python["verified"] and posting.full_text[start:end] == "Strong Python and SQL skills"
    assert rust == {"skill": "Rust", "quote": "Rust experience", "verified": False, "span": None}
    assert skills["nice_to_have"] == []


def test_queue_item_falls_back_to_board_locations_without_an_extraction():
    row = {"id": 3, "company": "Example GH", "title": "Account Executive", "url": "https://example.test/3",
           "status": "skipped", "skip_reason": "title: no include keyword", "closing_date": None,
           "closed_at": None, "board": {"locations": ["London, UK"]}, "fields": None, "fit": None,
           "reasons": None, "edits": []}
    item = review.queue_item(row)
    assert item["locations"] == ["London, UK"]
    assert (item["work_rights"], item["fit"], item["reasons"], item["closed"]) == (None, None, [], False)


def test_history_is_newest_first():
    early, late = datetime(2026, 10, 6, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC)
    events = review.history(
        [{"model": "fake-1", "route": "review", "failed": False, "created_at": early}],
        [{"username": "jie", "action": "edit", "edited_fields": {"work_mode": "remote", "seniority": "mid"},
          "from_status": None, "to_status": None, "created_at": late}])
    assert [event["kind"] for event in events] == ["review", "extraction"]
    assert events[0]["fields"] == ["seniority", "work_mode"]


@pytest.mark.parametrize("status, decisions, statuses", [
    ("review", ["approve", "dismiss"], []),
    ("tracked", ["dismiss"], ["tracked", "applied", "interview", "offer", "rejected"]),
    ("ineligible", ["override_ineligible", "dismiss"], []),
    ("skipped", ["approve"], []),
    ("dismissed", ["approve"], []),
    ("applied", [], ["tracked", "applied", "interview", "offer", "rejected"]),
])
def test_allowed_actions_follow_the_status(status, decisions, statuses):
    expected = {"decisions": decisions, "statuses": statuses, "can_edit": True}
    assert review.allowed_actions(status, can_edit=True) == expected


def test_build_detail_without_text_or_extraction():
    posting = greenhouse_posting()
    row = posting_row(posting, status="skipped", text=None, skip_reason="location: London")
    detail = review.build_detail(row, None, [], [])
    assert detail["text"] is None
    assert (detail["extraction"], detail["fields"], detail["fit"]) == (None, [], None)
    assert detail["skills"] == {"required": [], "nice_to_have": []}
    assert detail["actions"] == {"decisions": ["approve"], "statuses": [], "can_edit": False}
