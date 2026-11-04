from fastapi.testclient import TestClient

from helpers import make_settings, write_test_config
from jobpipe.app import create_app
from jobpipe.llm.fake import FakeExtractor


def test_the_built_page_is_served_beside_the_api(migrated_db, tmp_path):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Job ad review</title>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    settings = make_settings(migrated_db, write_test_config(tmp_path / "config"), web_dir=str(web))
    with TestClient(create_app(settings, extractor=FakeExtractor())) as client:
        assert "Job ad review" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log('ok')"
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/postings").status_code == 401


def test_without_a_build_the_root_says_how_to_make_one(migrated_db, tmp_path):
    settings = make_settings(migrated_db, write_test_config(tmp_path))
    with TestClient(create_app(settings, extractor=FakeExtractor())) as client:
        response = client.get("/")
    assert response.status_code == 404
    assert "make web" in response.text
