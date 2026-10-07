"""Builders shared by the tests."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from jobpipe import repo
from jobpipe.checks import run_checks, verified_closing_date
from jobpipe.configfiles import Profile, ProfileSkill
from jobpipe.fit import fit_score
from jobpipe.llm.schema import (
    ClosingDateField,
    ExtractionPayload,
    LocationsField,
    SkillItem,
    WorkModeField,
    WorkRightsField,
    not_stated_payload,
)
from jobpipe.models import BoardFields, Posting
from jobpipe.routing import decide_route
from jobpipe.settings import Settings
from jobpipe.sources import standardise
from jobpipe.sources.common import make_posting

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def posting_with(text: str, board: BoardFields | None = None, title: str = "Data Engineer",
                 posted: datetime | None = datetime(2026, 9, 20, tzinfo=UTC),
                 source_id: str = "1") -> Posting:
    return make_posting(source="greenhouse", source_id=source_id, company="Example", title=title,
                        url=f"https://example.test/{source_id}", posted_at=posted, text=text,
                        board=board or BoardFields())


TEST_CONFIG = {
    "companies.yaml": (
        "companies:\n"
        "  - {name: Example GH, source: greenhouse, slug: examplegh}\n"
        "  - {name: Example LV, source: lever, slug: examplelv}\n"
        "  - {name: Example AB, source: ashby, slug: exampleab}\n"
    ),
    "filters.yaml": (
        "location_terms: [australia, au, sydney, melbourne]\n"
        "title_include: [data, engineer, analyst, graduate]\n"
        "title_exclude: [sales, account executive]\n"
    ),
    "profile.yaml": "skills:\n  - {name: Python}\n  - {name: SQL, synonyms: [PostgreSQL]}\n",
    "prices.yaml": "fake-1: {input: 1.0, output: 2.0}\n",
}


def write_test_config(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in TEST_CONFIG.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


def payload_with(**fields) -> ExtractionPayload:
    return not_stated_payload().model_copy(update=fields)


def good_greenhouse_payload() -> ExtractionPayload:
    """A correct extraction for fixture job 7001001: every quote is in the ad and agrees with the board."""
    return payload_with(
        work_rights=WorkRightsField(value="any_work_rights", quote="You must have full working rights in Australia."),
        closing_date=ClosingDateField(value="2026-10-31", quote="Applications close 31 October 2026."),
        locations=LocationsField(value=["Sydney"], quote="Join our data team in Sydney."),
        work_mode=WorkModeField(value="hybrid",
                                quote="This is a hybrid role with three days a week in our Sydney office."),
        required_skills=[
            SkillItem(skill="Python", quote="Strong Python and SQL skills"),
            SkillItem(skill="SQL", quote="Strong Python and SQL skills"),
            SkillItem(skill="AWS", quote="Experience with AWS"),
        ],
    )


SAMPLE_AD = (
    "Join our data team in Sydney. This is a hybrid role.\n"
    "Applicants must be Australian citizens or permanent residents.\n"
    "You must hold an NV1 clearance.\n"
    "We are unable to offer visa sponsorship.\n"
    "Salary: $120,000 - $140,000 + super.\n"
    "Applications close 31 October 2026.\n"
    "Strong Python skills are essential."
)


SESSION_SECRET = "test-session-secret-" + "x" * 32


def make_settings(database_url: str, config_dir: Path, **overrides) -> Settings:
    """Settings for an app under test. Keyword arguments replace any value."""
    values = {"database_url": database_url, "machine_api_key": "test-key", "session_secret": SESSION_SECRET,
              "config_dir": str(config_dir), "llm_provider": "fake"}
    return Settings(**(values | overrides))


def greenhouse_posting() -> Posting:
    """Fixture job 7001001, standardised. good_greenhouse_payload() is a correct extraction of it."""
    return standardise("greenhouse", load_fixture("greenhouse_board.json"), "Example GH")[0]


def store_ad(conn, posting: Posting, payload: ExtractionPayload | None, status: str | None = None) -> int:
    """Store an ad as the pipeline would, with real checks, routing and fit, and return its id.

    Without a payload the ad is stored as skipped. status replaces the routed status.
    """
    company = repo.ensure_company(conn, posting.source, "examplegh", name="Example GH")
    posting_id = repo.insert_posting(conn, company["id"], posting, status="review")
    closing, skip_reason = posting.board.deadline, None
    if payload is None:
        status, skip_reason = status or "skipped", "title: no include keyword"
    else:
        checks = run_checks(posting, payload, today=date(2026, 10, 6))
        decision = decide_route(payload, checks)
        fit = fit_score(checks, Profile(skills=[ProfileSkill(name="Python"), ProfileSkill(name="SQL")]))
        repo.insert_extraction(conn, posting_id, posting.text_hash, "fake", "fake-1", payload, checks, decision,
                               fit)
        status = status or decision.route
        closing = verified_closing_date(payload, checks) or closing
    repo.set_status(conn, posting_id, status, skip_reason, closing)
    conn.commit()
    return posting_id
