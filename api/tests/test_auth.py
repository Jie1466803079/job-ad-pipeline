from datetime import UTC, datetime, timedelta

import pytest

from jobpipe import auth, repo
from jobpipe.create_user import main as create_user

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


def add_user(conn, username: str = "jie", password: str = PASSWORD) -> None:
    repo.save_user(conn, username, auth.hash_password(password))
    conn.commit()


def answers(*replies: str):
    """A stand-in for getpass that gives these replies in turn."""
    queue = iter(replies)
    return lambda prompt: next(queue)


def test_password_hashes_are_argon2_and_verify():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("$argon2id$")
    assert auth.verify_password(stored, PASSWORD)
    assert not auth.verify_password(stored, "wrong")
    assert not auth.verify_password("not a hash", PASSWORD)


def test_login_accepts_the_right_password_whatever_the_username_case(conn):
    add_user(conn)
    result = auth.login(conn, "  Jie ", PASSWORD, NOW)
    assert result.ok and result.username == "jie"


def test_unknown_user_and_wrong_password_fail_the_same_way(conn):
    add_user(conn)
    assert auth.login(conn, "nobody", PASSWORD, NOW) == auth.LoginResult()
    assert auth.login(conn, "jie", "wrong", NOW) == auth.LoginResult()


def test_fifth_failed_login_locks_the_account_for_15_minutes(conn):
    add_user(conn)
    for _ in range(4):
        assert auth.login(conn, "jie", "wrong", NOW).locked_minutes == 0
    assert auth.login(conn, "jie", "wrong", NOW).locked_minutes == 15
    during = auth.login(conn, "jie", PASSWORD, NOW + timedelta(minutes=14))
    assert not during.ok and during.locked_minutes == 1
    assert auth.login(conn, "jie", PASSWORD, NOW + timedelta(minutes=15, seconds=1)).ok


def test_a_successful_login_resets_the_count(conn):
    add_user(conn)
    for _ in range(4):
        auth.login(conn, "jie", "wrong", NOW)
    assert auth.login(conn, "jie", PASSWORD, NOW).ok
    for _ in range(4):
        assert auth.login(conn, "jie", "wrong", NOW).locked_minutes == 0


def test_create_user_creates_then_resets_and_clears_a_lockout(conn, migrated_db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    assert create_user(["Jie"], read_password=answers("a long first password", "a long first password")) == 0
    for _ in range(5):
        auth.login(conn, "jie", "wrong", NOW)
    conn.commit()
    assert create_user(["jie"], read_password=answers("a long second password", "a long second password")) == 0
    assert auth.login(conn, "jie", "a long second password", NOW).ok
    out = capsys.readouterr().out
    assert "Created jie." in out
    assert "Set a new password for jie" in out


@pytest.mark.parametrize("replies, message", [
    (("short", "short"), "at least 12 characters"),
    (("a long enough password", "a different password"), "do not match"),
])
def test_create_user_refuses_weak_or_mismatched_passwords(conn, migrated_db, monkeypatch, capsys, replies,
                                                          message):
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    assert create_user(["jie"], read_password=answers(*replies)) == 1
    assert message in capsys.readouterr().err
    assert repo.get_user(conn, "jie") is None
