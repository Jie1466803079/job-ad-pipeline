from datetime import UTC, date, datetime, timedelta

from helpers import good_greenhouse_payload, greenhouse_posting, posting_with, store_ad
from jobpipe import db, repo
from jobpipe.configfiles import CompanyConfig


def a_company(conn) -> dict:
    repo.sync_companies(conn, [CompanyConfig(name="A", source="greenhouse", slug="a")])
    return repo.active_companies(conn)[0]


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []


def test_sync_companies_adds_renames_and_deactivates(conn):
    repo.sync_companies(conn, [CompanyConfig(name="A", source="greenhouse", slug="a"),
                               CompanyConfig(name="B", source="lever", slug="b")])
    repo.sync_companies(conn, [CompanyConfig(name="A renamed", source="greenhouse", slug="a")])
    assert [(c["name"], c["slug"]) for c in repo.active_companies(conn)] == [("A renamed", "a")]


def test_ensure_company_adds_an_inactive_company_once(conn):
    first = repo.ensure_company(conn, "lever", "newco", "newco")
    again = repo.ensure_company(conn, "lever", "newco", "newco")
    assert first["id"] == again["id"]
    assert first["active"] is False
    assert repo.active_companies(conn) == []


def test_insert_find_and_close_missing(conn):
    company = a_company(conn)
    one = repo.insert_posting(conn, company["id"], posting_with("text one", source_id="1"), status="tracked")
    repo.insert_posting(conn, company["id"], posting_with("text two", source_id="2"), status="tracked")
    assert repo.find_posting(conn, "greenhouse", "1")["id"] == one
    assert repo.find_posting(conn, "greenhouse", "missing") is None
    assert repo.close_missing(conn, company["id"], ["1"]) == 1
    assert repo.close_missing(conn, company["id"], ["1"]) == 0


def test_close_past_deadline_and_delete_old_text(conn):
    company = a_company(conn)
    posting_id = repo.insert_posting(conn, company["id"], posting_with("text", source_id="1"), status="tracked")
    repo.set_status(conn, posting_id, "tracked", None, date(2026, 10, 1))
    assert repo.close_past_deadline(conn, date(2026, 10, 6)) == 1
    conn.execute("UPDATE postings SET closed_at = now() - interval '31 days' WHERE id = %s", (posting_id,))
    assert repo.delete_old_text(conn) == 1
    row = conn.execute("SELECT text, text_deleted_at FROM postings WHERE id = %s", (posting_id,)).fetchone()
    assert row["text"] is None and row["text_deleted_at"] is not None


def test_touch_reopens_unless_the_closing_date_has_passed(conn):
    company = a_company(conn)
    posting_id = repo.insert_posting(conn, company["id"], posting_with("text", source_id="1"), status="tracked")
    conn.execute("UPDATE postings SET closed_at = now() WHERE id = %s", (posting_id,))
    repo.touch_posting(conn, posting_id)
    assert repo.find_posting(conn, "greenhouse", "1")["closed_at"] is None
    repo.set_status(conn, posting_id, "tracked", None, date.today() - timedelta(days=2))
    conn.execute("UPDATE postings SET closed_at = now() WHERE id = %s", (posting_id,))
    repo.touch_posting(conn, posting_id)
    assert repo.find_posting(conn, "greenhouse", "1")["closed_at"] is not None


def test_set_status_keeps_a_status_a_person_chose(conn):
    company = a_company(conn)
    posting_id = repo.insert_posting(conn, company["id"], posting_with("Some text."), status="review")
    assert repo.set_status(conn, posting_id, "tracked", None, None) == "tracked"
    assert repo.decide_status(conn, posting_id, "tracked", "dismissed")
    assert repo.set_status(conn, posting_id, "review", None, date(2026, 11, 1)) == "dismissed"
    assert repo.get_posting(conn, posting_id)["closing_date"] == date(2026, 11, 1)


def test_decide_status_refuses_a_status_that_changed_meanwhile(conn):
    company = a_company(conn)
    posting_id = repo.insert_posting(conn, company["id"], posting_with("Some text."), status="review")
    assert repo.decide_status(conn, posting_id, "review", "tracked")
    assert not repo.decide_status(conn, posting_id, "review", "dismissed")
    assert repo.get_posting(conn, posting_id)["status"] == "tracked"


def test_digest_lists_ads_a_person_tracked_in_the_last_day(conn):
    posting_id = store_ad(conn, greenhouse_posting(), None)  # skipped by the filter, so no extraction
    assert repo.decide_status(conn, posting_id, "skipped", "tracked")  # "Track anyway"
    conn.commit()
    digest = repo.digest(conn, since=datetime.now(UTC) - timedelta(hours=24), today=date(2026, 10, 6))
    assert [(ad["id"], ad["fit"]) for ad in digest["tracked"]] == [(posting_id, None)]


def test_digest_leaves_out_ads_a_person_had_already_tracked(conn):
    posting_id = store_ad(conn, greenhouse_posting(), good_greenhouse_payload())  # the pipeline tracked it today
    conn.execute("UPDATE postings SET decided_at = now() - interval '2 days' WHERE id = %s", (posting_id,))
    conn.commit()
    digest = repo.digest(conn, since=datetime.now(UTC) - timedelta(hours=24), today=date(2026, 10, 6))
    assert digest["tracked"] == []
