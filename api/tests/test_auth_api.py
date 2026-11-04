import pytest
from fastapi.testclient import TestClient

from helpers import make_settings, write_test_config
from jobpipe import auth, repo
from jobpipe.app import SESSION_COOKIE, create_app
from jobpipe.llm.fake import FakeExtractor

PASSWORD = "correct horse battery"
OTHER_SECRET = "another-session-secret-" + "y" * 32


@pytest.fixture
def make_client(conn, migrated_db, tmp_path):
    """Builds clients for an app with one reviewer, jie. Use each client in a with block."""
    repo.save_user(conn, "jie", auth.hash_password(PASSWORD))
    conn.commit()

    def make(**overrides) -> TestClient:
        settings = make_settings(migrated_db, write_test_config(tmp_path), **overrides)
        return TestClient(create_app(settings, extractor=FakeExtractor()))

    return make


def log_in(client, username: str = "jie", password: str = PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def cookie_attributes(response) -> list[str]:
    return [part.strip().lower() for part in response.headers["set-cookie"].split(";")[1:]]


def test_login_me_and_logout(make_client):
    with make_client() as client:
        assert client.get("/auth/me").status_code == 401
        response = log_in(client)
        assert response.status_code == 200 and response.json() == {"username": "jie"}
        assert client.get("/auth/me").json() == {"username": "jie"}
        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me").status_code == 401


def test_session_cookie_is_http_only_strict_and_secure_only_when_asked(make_client):
    with make_client() as client:
        attributes = cookie_attributes(log_in(client))
    assert {"httponly", "samesite=strict", "path=/", "max-age=604800"} <= set(attributes)
    assert "secure" not in attributes
    with make_client(session_cookie_secure=True) as client:
        assert "secure" in cookie_attributes(log_in(client))


def test_wrong_password_is_401_and_the_fifth_is_429(make_client):
    with make_client() as client:
        for _ in range(4):
            assert log_in(client, password="wrong").status_code == 401
        locked = log_in(client, password="wrong")
        assert locked.status_code == 429
        assert locked.json() == {"detail": "Too many failed logins. Try again in 15 minutes."}
        assert log_in(client).status_code == 429
        assert client.get("/auth/me").status_code == 401


def test_unknown_user_gets_the_same_answer_as_a_wrong_password(make_client):
    with make_client() as client:
        unknown = log_in(client, username="nobody")
        wrong = log_in(client, password="wrong")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "Wrong username or password."}


def test_tampered_or_foreign_cookies_and_deleted_users_are_logged_out(make_client, conn):
    with make_client() as client:
        log_in(client)
        token = client.cookies.get(SESSION_COOKIE)
    tampered = token[:-4] + ("abcd" if not token.endswith("abcd") else "dcba")
    for overrides, value in (({}, tampered), ({"session_secret": OTHER_SECRET}, token), ({}, "garbage")):
        with make_client(**overrides) as client:
            response = client.get("/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={value}"})
            assert response.status_code == 401
    with make_client() as client:
        log_in(client)
        conn.execute("DELETE FROM users")
        conn.commit()
        assert client.get("/auth/me").status_code == 401


def test_app_refuses_to_start_without_a_long_session_secret(migrated_db, tmp_path):
    for secret in (None, "", "too-short"):
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            create_app(make_settings(migrated_db, write_test_config(tmp_path), session_secret=secret))
