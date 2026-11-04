import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from helpers import (
    good_greenhouse_payload,
    greenhouse_posting,
    make_settings,
    payload_with,
    posting_with,
    store_ad,
    write_test_config,
)
from jobpipe import auth, db, repo
from jobpipe.app import create_app
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.schema import LocationsField, WorkRightsField
from jobpipe.routes import review as review_routes

PASSWORD = "correct horse battery"
# A quote that is not in the ad, so the work_rights check fails and the ad goes to review.
UNVERIFIED = payload_with(work_rights=WorkRightsField(value="any_work_rights", quote="not in the ad"))


@pytest.fixture
def client(conn, migrated_db, tmp_path):
    """A logged-in client. The app syncs the test companies, so Example GH exists."""
    repo.save_user(conn, "jie", auth.hash_password(PASSWORD))
    conn.commit()
    app = create_app(make_settings(migrated_db, write_test_config(tmp_path)), extractor=FakeExtractor())
    with TestClient(app) as test_client:
        assert test_client.post("/auth/login", json={"username": "jie", "password": PASSWORD}).status_code == 200
        yield test_client


def ids(client, tab: str) -> list[int]:
    return [item["id"] for item in client.get("/api/postings", params={"tab": tab}).json()["items"]]


def detail(client, posting_id: int) -> dict:
    return client.get(f"/api/postings/{posting_id}").json()


def test_review_routes_need_a_login(client):
    client.post("/auth/logout")
    assert client.get("/api/postings").status_code == 401
    assert client.get("/api/postings/1").status_code == 401


def test_tabs_list_the_right_ads(client, conn):
    tracked = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    in_review = store_ad(conn, posting_with("Some text.", source_id="2"), UNVERIFIED)
    skipped = store_ad(conn, posting_with("Sales.", title="Account Executive", source_id="3"), None)
    closed = store_ad(conn, posting_with("Gone.", source_id="4"), payload_with())
    applied = store_ad(conn, posting_with("Applied.", source_id="5"), payload_with(), status="applied")
    conn.execute("UPDATE postings SET closed_at = now() WHERE id = ANY(%s)", ([closed, applied],))
    conn.commit()
    assert ids(client, "review") == [in_review]
    assert ids(client, "tracked") == [tracked]
    assert ids(client, "skipped") == [skipped]
    assert ids(client, "applied") == [applied]
    assert sorted(ids(client, "closed")) == sorted([closed, applied])
    assert ids(client, "ineligible") == ids(client, "dismissed") == []
    assert client.get("/api/postings", params={"tab": "nope"}).status_code == 422


def test_queue_items_carry_the_columns(client, conn):
    store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    page = client.get("/api/postings", params={"tab": "tracked"}).json()
    assert page["total"] == 1
    item = page["items"][0]
    assert (item["company"], item["title"], item["locations"]) == ("Example GH", "Data Engineer", ["Sydney"])
    assert (item["work_rights"], item["closing_date"]) == ("any_work_rights", "2026-10-31")
    assert item["fit"] == {"matched": 2, "total": 3}


def test_a_long_tab_is_cut_at_the_limit_with_the_total(client, conn):
    for number in range(3):
        store_ad(conn, posting_with(f"Ad {number}.", source_id=f"x{number}"), payload_with())
    page = client.get("/api/postings", params={"tab": "tracked", "limit": 2}).json()
    assert (page["total"], len(page["items"])) == (3, 2)


def test_detail_spans_point_at_the_quotes_in_the_returned_text(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    ad = detail(client, posting_id)
    assert ad["text"].startswith("Data Engineer\n\nJoin our data team in Sydney.")
    spans = {field["name"]: field["span"] for field in ad["fields"] if field["span"]}
    assert set(spans) == {"work_rights", "closing_date", "locations", "work_mode"}
    for field in ad["fields"]:
        if field["span"]:
            start, end = field["span"]
            assert ad["text"][start:end] == field["quote"]
    assert ad["fit"]["summary"] == "2 of 3 required skills; missing: AWS"
    statuses = ["tracked", "applied", "interview", "offer", "rejected"]
    assert ad["actions"] == {"decisions": ["dismiss"], "statuses": statuses, "can_edit": True}


def test_spans_count_code_points_so_emoji_do_not_shift_them(client, conn):
    rocket = chr(0x1F680)
    quote = "Join our data team in Sydney."
    posting = posting_with(f"{rocket}{rocket} We are hiring!\n{quote}", source_id="9")
    posting_id = store_ad(conn, posting, payload_with(locations=LocationsField(value=["Sydney"], quote=quote)))
    ad = detail(client, posting_id)
    start, end = next(field["span"] for field in ad["fields"] if field["name"] == "locations")
    assert ad["text"][start:end] == quote
    assert start == ad["text"].index(quote)


def test_an_extraction_of_older_text_is_not_shown(client, conn):
    posting = greenhouse_posting()
    posting_id = store_ad(conn, posting, good_greenhouse_payload())
    changed = posting.model_copy(update={"text": "Now a sales role.", "text_hash": "changed"})
    repo.update_posting_content(conn, posting_id, changed)
    repo.set_status(conn, posting_id, "skipped", "title: no include keyword", None)
    conn.commit()
    ad = detail(client, posting_id)
    assert (ad["extraction"], ad["fields"]) == (None, [])
    assert ad["text"] == "Data Engineer\n\nNow a sales role."
    assert [event["kind"] for event in ad["history"]] == ["extraction"]
    assert ad["actions"]["can_edit"] is False
    assert client.get("/api/postings", params={"tab": "skipped"}).json()["items"][0]["work_rights"] is None


def test_detail_after_the_text_was_deleted_keeps_the_values(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    conn.execute("UPDATE postings SET closed_at = now() - interval '40 days' WHERE id = %s", (posting_id,))
    assert repo.delete_old_text(conn) == 1
    conn.commit()
    ad = detail(client, posting_id)
    assert ad["text"] is None and ad["text_deleted_at"] is not None
    assert {field["name"]: field["value"] for field in ad["fields"]}["work_mode"] == "hybrid"


def test_unknown_ad_is_404(client):
    assert client.get("/api/postings/999").status_code == 404


def test_write_routes_need_a_login(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    client.post("/auth/logout")
    assert client.patch(f"/api/postings/{posting_id}/fields", json={"work_mode": "remote"}).status_code == 401
    assert client.post(f"/api/postings/{posting_id}/decision", json={"decision": "dismiss"}).status_code == 401
    assert client.patch(f"/api/postings/{posting_id}/status", json={"status": "applied"}).status_code == 401
    assert conn.execute("SELECT count(*) AS n FROM reviews").fetchone()["n"] == 0


def test_a_correction_is_stored_beside_the_extraction(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    ad = client.patch(f"/api/postings/{posting_id}/fields", json={"work_rights": "citizen_or_pr"}).json()
    rights = next(field for field in ad["fields"] if field["name"] == "work_rights")
    assert (rights["value"], rights["extracted"], rights["edited"]) == ("citizen_or_pr", "any_work_rights", True)
    assert repo.current_extraction(conn, posting_id)["fields"]["work_rights"]["value"] == "any_work_rights"
    row = conn.execute("SELECT username, action, edited_fields FROM reviews").fetchone()
    assert row == {"username": "jie", "action": "edit", "edited_fields": {"work_rights": "citizen_or_pr"}}
    assert ad["history"][0]["fields"] == ["work_rights"]
    items = client.get("/api/postings", params={"tab": "tracked"}).json()["items"]
    assert items[0]["work_rights"] == "citizen_or_pr"


def test_correcting_the_closing_date_updates_the_date_used_for_closing(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    client.patch(f"/api/postings/{posting_id}/fields", json={"closing_date": "2026-11-14"})
    assert repo.get_posting(conn, posting_id)["closing_date"] == date(2026, 11, 14)
    client.patch(f"/api/postings/{posting_id}/fields", json={"closing_date": "not_stated"})
    assert repo.get_posting(conn, posting_id)["closing_date"] == date(2026, 10, 31)  # the board's deadline


def test_invalid_corrections_change_nothing(client, conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    for body in ({"work_rights": "maybe"}, {"colour": "blue"}, {}, {"work_mode": None}):
        assert client.patch(f"/api/postings/{posting_id}/fields", json=body).status_code == 422
    assert conn.execute("SELECT count(*) AS n FROM reviews").fetchone()["n"] == 0


def test_an_ad_without_extracted_values_cannot_be_corrected(client, conn):
    skipped = store_ad(conn, posting_with("Sales.", title="Account Executive", source_id="3"), None)
    assert client.patch(f"/api/postings/{skipped}/fields", json={"work_mode": "remote"}).status_code == 409


def test_decisions_follow_the_allowed_moves_and_are_recorded_once(client, conn):
    posting_id = store_ad(conn, posting_with("Some text.", source_id="2"), UNVERIFIED)

    def decide(decision):
        return client.post(f"/api/postings/{posting_id}/decision", json={"decision": decision})

    assert decide("approve").json()["status"] == "tracked"
    assert decide("approve").status_code == 409
    assert decide("override_ineligible").status_code == 409
    assert decide("dismiss").json()["status"] == "dismissed"
    assert decide("approve").json()["status"] == "tracked"
    rows = conn.execute("SELECT action, from_status, to_status FROM reviews ORDER BY id").fetchall()
    assert [tuple(row.values()) for row in rows] == [("approve", "review", "tracked"),
                                                     ("dismiss", "tracked", "dismissed"),
                                                     ("approve", "dismissed", "tracked")]
    assert repo.get_posting(conn, posting_id)["decided_at"] is not None


def test_override_moves_an_ineligible_ad_to_tracked(client, conn):
    text = "Applicants must be Australian citizens."
    posting_id = store_ad(conn, posting_with(text, source_id="6"),
                          payload_with(work_rights=WorkRightsField(value="citizen_only", quote=text)))
    assert repo.get_posting(conn, posting_id)["status"] == "ineligible"
    response = client.post(f"/api/postings/{posting_id}/decision", json={"decision": "override_ineligible"})
    assert response.json()["status"] == "tracked"


def test_application_status_needs_a_tracked_ad(client, conn):
    in_review = store_ad(conn, posting_with("Some text.", source_id="2"), UNVERIFIED)
    assert client.patch(f"/api/postings/{in_review}/status", json={"status": "applied"}).status_code == 409
    tracked = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    for status in ("applied", "interview", "rejected", "tracked"):
        assert client.patch(f"/api/postings/{tracked}/status", json={"status": status}).json()["status"] == status
    assert client.patch(f"/api/postings/{tracked}/status", json={"status": "dismissed"}).status_code == 422
    assert client.patch(f"/api/postings/{tracked}/status", json={"status": "tracked"}).status_code == 200
    assert conn.execute("SELECT count(*) AS n FROM reviews").fetchone()["n"] == 4


def test_stats_count_tabs_today_and_this_month(client, conn):
    store_ad(conn, greenhouse_posting(), good_greenhouse_payload())
    store_ad(conn, posting_with("Some text.", source_id="2"), UNVERIFIED)
    store_ad(conn, posting_with("Sales.", title="Account Executive", source_id="3"), None)
    company_id = repo.ensure_company(conn, "greenhouse", "examplegh", name="Example GH")["id"]
    conn.execute("""INSERT INTO ingest_calls (company_id, started_at, fetched, created, tracked, review)
                    VALUES (%s, now(), 5, 3, 1, 1), (%s, now() - interval '40 days', 9, 9, 9, 9)""",
                 (company_id, company_id))
    conn.execute("INSERT INTO llm_calls (provider, model, outcome, cost_usd) VALUES ('fake', 'fake-1', 'ok', 0.0125)")
    conn.commit()
    stats = client.get("/api/stats").json()
    assert stats["tabs"] == {"review": 1, "tracked": 1, "ineligible": 0, "applied": 0, "closed": 0,
                             "skipped": 1, "dismissed": 0}
    assert (stats["today"]["fetched"], stats["today"]["created"], stats["today"]["tracked"]) == (5, 3, 1)
    assert stats["month"] == {"extracted": 2, "auto_routed": 1, "llm_cost_usd": 0.0125}
    client.post("/auth/logout")
    assert client.get("/api/stats").status_code == 401


def test_writes_to_an_ad_that_an_ingest_is_updating_fail_fast(client, conn, migrated_db, monkeypatch):
    """The daily ingest holds an ad's row while it waits for the LLM (up to about 100 s). Writes must not hang."""
    posting_id = store_ad(conn, posting_with("Some text.", source_id="2"), UNVERIFIED)
    monkeypatch.setattr(review_routes, "LOCK_TIMEOUT", "200ms")
    ingest = db.connect(migrated_db)
    ingest.execute("UPDATE postings SET last_seen_at = now() WHERE id = %s", (posting_id,))
    release = threading.Timer(3, ingest.rollback)  # without a lock timeout the requests wait this long
    release.start()
    try:
        started = time.monotonic()
        decision = client.post(f"/api/postings/{posting_id}/decision", json={"decision": "approve"})
        correction = client.patch(f"/api/postings/{posting_id}/fields", json={"closing_date": "2026-11-14"})
        elapsed = time.monotonic() - started
    finally:
        release.cancel()
        ingest.rollback()
        ingest.close()
    assert (decision.status_code, correction.status_code) == (409, 409)
    assert "ingest" in decision.json()["detail"]
    assert elapsed < 2
    assert repo.get_posting(conn, posting_id)["status"] == "review"
    assert conn.execute("SELECT count(*) AS n FROM reviews").fetchone()["n"] == 0
