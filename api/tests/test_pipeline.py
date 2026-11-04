import copy
from datetime import date

import pytest

from helpers import good_greenhouse_payload, load_fixture, write_test_config
from jobpipe import repo
from jobpipe.configfiles import load_companies, load_filters, load_prices, load_profile
from jobpipe.llm.base import ExtractionError
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.schema import WorkRightsField
from jobpipe.pipeline import Pipeline


@pytest.fixture
def setup(conn, tmp_path):
    config = write_test_config(tmp_path)
    repo.sync_companies(conn, load_companies(config / "companies.yaml"))
    conn.commit()
    company = next(c for c in repo.active_companies(conn) if c["source"] == "greenhouse")

    def make(payload_for=None):
        extractor = FakeExtractor(payload_for or (lambda posting: good_greenhouse_payload()))
        pipeline = Pipeline(conn, extractor, load_filters(config / "filters.yaml"),
                            load_profile(config / "profile.yaml"), load_prices(config / "prices.yaml"),
                            today=lambda: date(2026, 10, 6))
        return pipeline, extractor

    return company, make


def board():
    return load_fixture("greenhouse_board.json")


def test_new_ads_are_routed_and_stored(conn, setup):
    company, make = setup
    pipeline, extractor = make()
    counts, outcomes = pipeline.ingest(company, board(), complete=True)
    assert (counts.fetched, counts.created, counts.skipped, counts.extracted, counts.tracked) == (2, 2, 1, 1, 1)
    assert [(o.source_id, o.status) for o in outcomes] == [("7001001", "tracked"), ("7001002", "skipped")]
    assert outcomes[1].reasons == ["location: not in Australia"]
    assert extractor.calls == ["7001001"]
    row = conn.execute("SELECT closing_date FROM postings WHERE source_id = '7001001'").fetchone()
    assert row["closing_date"] == date(2026, 10, 31)
    call = conn.execute("SELECT provider, input_tokens, cost_usd, outcome FROM llm_calls").fetchone()
    assert (call["provider"], call["input_tokens"], float(call["cost_usd"]), call["outcome"]) == (
        "fake", 1000, 0.0014, "ok")
    extraction = repo.latest_extraction(conn, outcomes[0].posting_id)
    assert extraction["route"] == "tracked"
    assert extraction["fit"]["matched"] == ["Python", "SQL"]


def test_unchanged_ads_are_not_extracted_again(conn, setup):
    company, make = setup
    pipeline, extractor = make()
    pipeline.ingest(company, board(), complete=True)
    counts, _ = pipeline.ingest(company, board(), complete=True)
    assert (counts.unchanged, counts.extracted) == (2, 0)
    assert extractor.calls == ["7001001"]


def test_same_ad_twice_in_one_response_is_stored_once(conn, setup):
    company, make = setup
    pipeline, extractor = make()
    payload = board()
    payload["jobs"] = [payload["jobs"][0], copy.deepcopy(payload["jobs"][0])]
    counts, _ = pipeline.ingest(company, payload, complete=False)
    assert (counts.created, counts.unchanged) == (1, 1)
    assert extractor.calls == ["7001001"]


def test_changed_text_is_extracted_again_but_a_persons_status_is_kept(conn, setup):
    company, make = setup
    pipeline, extractor = make()
    _, outcomes = pipeline.ingest(company, board(), complete=True)
    repo.set_status(conn, outcomes[0].posting_id, "applied", None, None)
    conn.commit()
    changed = board()
    changed["jobs"][0]["content"] = changed["jobs"][0]["content"].replace("31 October", "7 November")
    counts, outcomes = pipeline.ingest(company, changed, complete=True)
    assert counts.changed == 1
    assert extractor.calls == ["7001001", "7001001"]
    assert outcomes[0].status == "applied"


def test_a_complete_fetch_closes_missing_ads(conn, setup):
    company, make = setup
    pipeline, _ = make()
    pipeline.ingest(company, board(), complete=True)
    smaller = board()
    smaller["jobs"] = smaller["jobs"][:1]
    counts, _ = pipeline.ingest(company, smaller, complete=True)
    assert counts.closed == 1


def test_only_source_id_processes_one_ad_and_closes_nothing(conn, setup):
    company, make = setup
    pipeline, _ = make()
    counts, outcomes = pipeline.ingest(company, board(), complete=True, only_source_id="7001001")
    assert (counts.fetched, counts.closed) == (1, 0)
    assert [o.source_id for o in outcomes] == ["7001001"]


def test_extraction_failure_goes_to_review_and_is_logged(conn, setup):
    company, make = setup
    pipeline, _ = make(lambda posting: ExtractionError("api_error", "Gemini API error 503"))
    counts, outcomes = pipeline.ingest(company, board(), complete=True)
    assert (counts.failed, counts.review) == (1, 1)
    assert outcomes[0].status == "review"
    assert outcomes[0].reasons == ["extraction_failed: api_error: Gemini API error 503"]
    assert conn.execute("SELECT outcome FROM llm_calls").fetchone()["outcome"] == "api_error"


def test_unexpected_exceptions_do_not_stop_the_batch(conn, setup):
    company, make = setup
    pipeline, _ = make(lambda posting: RuntimeError("socket closed"))
    counts, outcomes = pipeline.ingest(company, board(), complete=True)
    assert counts.failed == 1
    assert outcomes[0].status == "review"


def test_verified_citizen_only_is_ineligible(conn, setup):
    company, make = setup
    ad = board()
    ad["jobs"][0]["content"] += "&lt;p&gt;Only Australian citizens may apply.&lt;/p&gt;"
    payload = good_greenhouse_payload().model_copy(update={
        "work_rights": WorkRightsField(value="citizen_only", quote="Only Australian citizens may apply.")})
    pipeline, _ = make(lambda posting: payload)
    _, outcomes = pipeline.ingest(company, ad, complete=True)
    assert outcomes[0].status == "ineligible"
    assert outcomes[0].reasons == ["work rights: citizen only"]


def test_ad_without_text_is_skipped_without_an_llm_call(conn, setup):
    company, make = setup
    pipeline, extractor = make()
    ad = board()
    ad["jobs"][0]["content"] = ""
    _, outcomes = pipeline.ingest(company, ad, complete=True)
    assert outcomes[0].status == "skipped"
    assert outcomes[0].reasons == ["no ad text"]
    assert extractor.calls == []


def test_a_person_approving_an_ad_is_not_undone_by_a_later_ingest(conn, setup):
    company, make = setup
    unverified = good_greenhouse_payload().model_copy(
        update={"work_rights": WorkRightsField(value="any_work_rights", quote="not in the ad")})
    pipeline, extractor = make(lambda posting: unverified)
    _, outcomes = pipeline.ingest(company, board(), complete=True)
    assert outcomes[0].status == "review"
    assert repo.decide_status(conn, outcomes[0].posting_id, "review", "tracked")
    conn.commit()
    changed = board()
    changed["jobs"][0]["content"] = changed["jobs"][0]["content"].replace("31 October", "7 November")
    _, outcomes = pipeline.ingest(company, changed, complete=True)
    assert extractor.calls == ["7001001", "7001001"]
    assert outcomes[0].status == "tracked"
    assert repo.get_posting(conn, outcomes[0].posting_id)["status"] == "tracked"
