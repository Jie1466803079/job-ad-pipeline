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
from jobpipe import auth, repo
from jobpipe.app import create_app
from jobpipe.llm.fake import FakeExtractor
from jobpipe.llm.schema import LocationsField, WorkRightsField

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
