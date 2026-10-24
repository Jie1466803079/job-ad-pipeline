import csv
import html
import random
from datetime import date

import pytest

from helpers import posting_with
from jobpipe.configfiles import load_companies, load_filters
from jobpipe.eval.files import Snapshot, load_snapshot, load_split
from jobpipe.eval.sample import (
    INJECTED_LINE,
    draw,
    fetch_candidates,
    inject,
    labelling_view,
    run_sample,
    spread,
    title_band,
)
from jobpipe.llm.schema import ROUTING_FIELDS
from jobpipe.models import BoardFields

CITIZEN_ONLY = "Must be an Australian citizen and able to obtain an NV1 clearance."


def job(job_id: int, title: str, text: str = "Build data pipelines in Sydney.", location: str = "Sydney, Australia"):
    return {"id": job_id, "title": title, "absolute_url": f"https://job-boards.greenhouse.io/x/jobs/{job_id}",
            "location": {"name": location}, "first_published": "2026-10-01T09:00:00+10:00",
            "content": html.escape(f"<p>{text}</p><p>Second paragraph.</p>")}


BOARDS = {
    "alpha": {"jobs": [job(1, "Graduate Data Analyst"), job(2, "Senior Data Engineer"), job(3, "Lead Data Engineer"),
                       job(4, "Data Engineer"), job(5, "Data Analyst"), job(6, "Analytics Engineer"),
                       job(7, "Sales Manager"), job(8, "Data Engineer", location="London, UK")]},
    "beta": {"jobs": [job(11, "Data Engineer"), job(12, "Senior Data Analyst"), job(13, "Graduate Engineer"),
                      job(14, "Data Scientist Engineer")]},
    "defence": {"jobs": [job(21, "Systems Engineer", CITIZEN_ONLY), job(22, "Test Engineer", CITIZEN_ONLY),
                         job(23, "Software Engineer", CITIZEN_ONLY), job(24, "Data Engineer"),
                         job(25, "Graduate Data Engineer")]},
}
COMPANIES = ("companies:\n"
             "  - {name: Alpha, source: greenhouse, slug: alpha}\n"
             "  - {name: Beta, source: greenhouse, slug: beta}\n"
             "  - {name: Defence, source: greenhouse, slug: defence, active: false}\n")
FILTERS = ("location_terms: [australia, sydney]\n"
           "title_include: [data, engineer, analyst, analytics, graduate]\n"
           "title_exclude: [sales]\n")


@pytest.fixture
def config_dir(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "companies.yaml").write_text(COMPANIES, encoding="utf-8")
    (directory / "filters.yaml").write_text(FILTERS, encoding="utf-8")
    return directory


def fetch(source: str, slug: str):
    return BOARDS[slug]


def candidates(config_dir):
    found, failures = fetch_candidates(load_companies(config_dir / "companies.yaml"),
                                       load_filters(config_dir / "filters.yaml"), fetch)
    assert failures == []
    return found


def test_only_ads_that_pass_the_filter_are_candidates(config_dir):
    found = candidates(config_dir)
    assert len(found) == 15  # the sales job and the London job are filtered out
    assert sum(c.eligibility for c in found) == 3
    assert {c.posting.company for c in found if not c.active} == {"Defence"}


def test_takes_eligibility_ads_first_and_general_ads_only_from_active_companies(config_dir):
    eligibility, general = draw(candidates(config_dir), random.Random(1), size=8, eligibility_size=2)
    assert len(eligibility) == 2 and all(c.eligibility for c in eligibility)
    assert len(general) == 6
    assert [c.posting.company for c in general].count("Alpha") == 3
    assert [c.posting.company for c in general].count("Beta") == 3


def test_tops_up_with_more_eligibility_ads_when_general_ads_run_out(config_dir):
    eligibility, general = draw(candidates(config_dir), random.Random(1), size=13, eligibility_size=1)
    assert (len(eligibility), len(general)) == (3, 10)


def test_spreads_a_company_across_job_levels(config_dir):
    alpha = [c for c in candidates(config_dir) if c.posting.company == "Alpha"]
    picked = spread(alpha, 4, random.Random(3))
    assert {title_band(c.posting.title) for c in picked} == {"entry", "senior", "lead", "other"}


def test_writes_snapshots_a_split_and_a_blank_label_sheet(tmp_path, config_dir):
    eval_dir = tmp_path / "eval"
    assert run_sample(eval_dir, config_dir, seed=7, fetch=fetch, today=lambda: date(2026, 10, 15)) == 0
    split = load_split(eval_dir)
    originals = split.dev + split.test
    assert len(originals) == len(set(originals)) == 13
    assert (len(split.dev), len(split.test)) == (3, 10)
    assert set(split.injected.values()) <= set(split.test)
    assert len(split.injected) == 4
    assert all(copy_id == f"{original}-inj" for copy_id, original in split.injected.items())
    with open(eval_dir / "labels.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["id"] for r in rows] == sorted(originals)
    assert all(r[name] == "" for r in rows for name in ROUTING_FIELDS)
    assert sorted(p.stem for p in (eval_dir / "snapshots").glob("*.txt")) == sorted(originals)
    copy = load_snapshot(eval_dir, sorted(split.injected)[0])
    original = load_snapshot(eval_dir, copy.altered_from)
    assert INJECTED_LINE in copy.posting.text and INJECTED_LINE not in original.posting.text
    assert copy.posting.text_hash != original.posting.text_hash
    assert original.fetched_on == date(2026, 10, 15)


def test_the_same_seed_draws_the_same_sample(tmp_path, config_dir):
    for name in ("one", "two"):
        assert run_sample(tmp_path / name, config_dir, seed=7, fetch=fetch, today=lambda: date(2026, 10, 15)) == 0
    for file in ("split.json", "labels.csv"):
        assert (tmp_path / "one" / file).read_text() == (tmp_path / "two" / file).read_text()


def test_refuses_to_run_once_labels_exist(tmp_path, config_dir, capsys):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (eval_dir / "labels.csv").write_text("hours of work\n", encoding="utf-8")

    def must_not_fetch(source, slug):
        raise AssertionError("fetched a board")

    assert run_sample(eval_dir, config_dir, fetch=must_not_fetch) == 1
    assert (eval_dir / "labels.csv").read_text(encoding="utf-8") == "hours of work\n"
    assert not (eval_dir / "snapshots").exists()
    assert "already been drawn" in capsys.readouterr().out


def test_a_board_that_cannot_be_fetched_stops_the_sample_before_anything_is_written(tmp_path, config_dir, capsys):
    def flaky(source, slug):
        if slug == "beta":
            raise RuntimeError("HTTP 503")
        return BOARDS[slug]

    eval_dir = tmp_path / "eval"
    assert run_sample(eval_dir, config_dir, fetch=flaky) == 1
    assert not eval_dir.exists()
    assert "Could not fetch Beta (greenhouse/beta): RuntimeError: HTTP 503" in capsys.readouterr().out


def test_inject_adds_the_line_after_the_first_paragraph():
    two = inject(posting_with("First paragraph.\n\nSecond paragraph."))
    assert two.text == f"First paragraph.\n\n{INJECTED_LINE}\n\nSecond paragraph."
    one = inject(posting_with("Only paragraph."))
    assert one.text == f"Only paragraph.\n\n{INJECTED_LINE}"


def test_the_labelling_text_shows_the_ad_but_not_the_board_tags():
    posting = posting_with("Build data pipelines.", board=BoardFields(locations=["Sydney"], work_mode="hybrid",
                                                                       employment_type="full_time"))
    view = labelling_view(Snapshot(id="ad001", group="general", fetched_on=date(2026, 10, 15), posting=posting))
    assert view.startswith("Ad: ad001\nCompany: Example\nPosted: 2026-09-20\nLink: https://example.test/1\n\n")
    assert "Data Engineer\n\nBuild data pipelines." in view
    assert "Sydney" not in view and "hybrid" not in view and "full_time" not in view
