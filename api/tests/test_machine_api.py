import pytest
from fastapi.testclient import TestClient

from helpers import good_greenhouse_payload, load_fixture, make_settings, write_test_config
from jobpipe.app import create_app
from jobpipe.llm.fake import FakeExtractor
from jobpipe.settings import Settings

KEY = {"X-API-Key": "test-key"}
LEVER_LINK = "https://jobs.lever.co/newco/3f2b9a52-1c1e-4c55-9d37-1b7a3a8a0001"


@pytest.fixture
def client(conn, migrated_db, tmp_path):
    settings = make_settings(migrated_db, write_test_config(tmp_path))
    app = create_app(settings, extractor=FakeExtractor(lambda posting: good_greenhouse_payload()))
    with TestClient(app) as test_client:
        yield test_client


def greenhouse_id(client) -> int:
    companies = client.get("/machine/companies", headers=KEY).json()
    return next(c["id"] for c in companies if c["source"] == "greenhouse")


def ingest(client, payload, complete=True):
    return client.post("/machine/ingest", headers=KEY, json={
        "company_id": greenhouse_id(client), "source": "greenhouse", "payload": payload, "complete": complete})


def test_machine_routes_need_the_api_key(client):
    assert client.get("/machine/companies").status_code == 401
    assert client.get("/machine/companies", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_create_app_refuses_to_start_without_an_api_key(migrated_db):
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=migrated_db, machine_api_key=None, llm_provider="fake"))


def test_companies_come_from_config(client):
    names = [c["name"] for c in client.get("/machine/companies", headers=KEY).json()]
    assert names == ["Example AB", "Example GH", "Example LV"]


def test_companies_come_with_their_board_address(client):
    by_name = {c["name"]: c for c in client.get("/machine/companies", headers=KEY).json()}
    assert by_name["Example GH"]["api_url"] == "https://boards-api.greenhouse.io/v1/boards/examplegh/jobs?content=true"
    assert by_name["Example LV"]["api_url"] == "https://api.lever.co/v0/postings/examplelv?mode=json"
    assert by_name["Example AB"]["api_url"] == (
        "https://api.ashbyhq.com/posting-api/job-board/exampleab?includeCompensation=true")


def test_companies_can_be_picked_by_name(client):
    def names(query: str) -> list[str]:
        response = client.get("/machine/companies", headers=KEY, params={"names": query})
        return [c["name"] for c in response.json()]

    assert names("Example LV, Example GH") == ["Example GH", "Example LV"]
    assert names("") == ["Example AB", "Example GH", "Example LV"]
    assert names(" , ") == ["Example AB", "Example GH", "Example LV"]


def test_picking_an_unknown_or_inactive_company_is_an_error(client):
    unknown = client.get("/machine/companies", headers=KEY, params={"names": "Example GH,Nope"})
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "not active companies: Nope"
    client.post("/machine/links/resolve", headers=KEY, json={"url": LEVER_LINK})  # adds newco, not active
    inactive = client.get("/machine/companies", headers=KEY, params={"names": "newco"})
    assert inactive.status_code == 422


def test_ingest_then_ingest_again(client):
    first = ingest(client, load_fixture("greenhouse_board.json"))
    assert first.status_code == 200
    assert first.json()["counts"]["tracked"] == 1
    second = ingest(client, load_fixture("greenhouse_board.json")).json()
    assert second["counts"]["unchanged"] == 2
    assert client.app.state.extractor.calls == ["7001001"]


def test_ingest_rejects_wrong_source_and_unreadable_payload_without_closing_anything(client, conn):
    ingest(client, load_fixture("greenhouse_board.json"))
    wrong_source = client.post("/machine/ingest", headers=KEY, json={
        "company_id": greenhouse_id(client), "source": "lever", "payload": [], "complete": True})
    assert wrong_source.status_code == 422
    unreadable = ingest(client, {"ok": False, "error": "Document not found"})
    assert unreadable.status_code == 422
    assert "board response for Example GH" in unreadable.json()["detail"]
    closed = conn.execute("SELECT count(*) AS n FROM postings WHERE closed_at IS NOT NULL").fetchone()["n"]
    assert closed == 0


def test_ingest_for_an_unknown_company(client):
    response = client.post("/machine/ingest", headers=KEY, json={
        "company_id": 999, "source": "greenhouse", "payload": {"jobs": []}})
    assert response.status_code == 404


def test_links_resolve(client):
    allowed = client.post("/machine/links/resolve", headers=KEY, json={"url": LEVER_LINK})
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["allowed"] is True and body["source"] == "lever"
    assert body["api_url"].startswith("https://api.lever.co/v0/postings/newco/")
    active_slugs = [c["slug"] for c in client.get("/machine/companies", headers=KEY).json()]
    assert "newco" not in active_slugs
    rejected = client.post("/machine/links/resolve", headers=KEY, json={"url": "https://169.254.169.254/latest"})
    assert rejected.status_code == 400
    assert rejected.json()["allowed"] is False


def test_digest_and_maintenance(client):
    ingest(client, load_fixture("greenhouse_board.json"))
    digest = client.get("/machine/digest", headers=KEY).json()
    assert [t["title"] for t in digest["tracked"]] == ["Data Engineer"]
    assert digest["counts"]["fetched"] == 2
    assert digest["review_count"] == 0
    assert set(digest) == {"tracked", "closing_soon", "review_count", "counts", "llm_cost_usd"}
    maintenance = client.post("/machine/maintenance", headers=KEY).json()
    assert set(maintenance) == {"closed", "text_deleted"}


def test_digest_email(client):
    assert client.get("/machine/digest/email").status_code == 401
    ingest(client, load_fixture("greenhouse_board.json"))
    email = client.get("/machine/digest/email", headers=KEY).json()
    assert set(email) == {"subject", "text", "html"}  # never a top-level "error": n8n would retry the call
    assert " 1 new, " in email["subject"]
    assert "- Data Engineer at Example GH." in email["text"]
    assert "http://127.0.0.1:8000/#/postings/" in email["text"]


def test_internal_errors_are_not_reported_as_unreadable_payloads(client, monkeypatch):
    def broken_checks(*args, **kwargs):
        raise ValueError("bug in the checks")

    monkeypatch.setattr("jobpipe.pipeline.run_checks", broken_checks)
    with pytest.raises(ValueError, match="bug in the checks"):
        ingest(client, load_fixture("greenhouse_board.json"))
