"""Reviewer passwords and the login rule: five failed logins in a row lock the account for 15 minutes."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from psycopg import Connection

from jobpipe import repo

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)

_hasher = PasswordHasher()
# Checked against when the username is unknown, so that answer takes as long as a wrong password.
_TIMING_HASH = _hasher.hash("only used to spend the same time on unknown usernames")


@dataclass
class LoginResult:
    username: str | None = None
    locked_minutes: int = 0

    @property
    def ok(self) -> bool:
        return self.username is not None


def normalise_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def login(conn: Connection, username: str, password: str, now: datetime) -> LoginResult:
    """Check a login attempt and record it. The caller commits."""
    user = repo.get_user(conn, normalise_username(username))
    if user is None:
        verify_password(_TIMING_HASH, password)
        return LoginResult()
    if user["locked_until"] and user["locked_until"] > now:
        return LoginResult(locked_minutes=_minutes_left(user["locked_until"], now))
    if not verify_password(user["password_hash"], password):
        locked_until = repo.record_failed_login(conn, user["id"], MAX_FAILED_LOGINS, now + LOCKOUT)
        if locked_until and locked_until > now:
            return LoginResult(locked_minutes=_minutes_left(locked_until, now))
        return LoginResult()
    repo.clear_failed_logins(conn, user["id"])
    return LoginResult(username=user["username"])


def _minutes_left(until: datetime, now: datetime) -> int:
    return max(1, math.ceil((until - now).total_seconds() / 60))
