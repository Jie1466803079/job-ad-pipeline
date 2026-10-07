"""FastAPI dependencies."""

import hmac
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request
from psycopg import Connection

from jobpipe import db, repo


def get_conn(request: Request) -> Iterator[Connection]:
    with db.connect(request.app.state.settings.database_url) as conn:
        yield conn


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.machine_api_key
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid API key")


def require_user(request: Request, conn: Connection = Depends(get_conn)) -> str:
    """The logged-in reviewer. A missing, tampered or expired cookie, or a deleted account, gets 401."""
    username = request.session.get("username")
    if not isinstance(username, str) or repo.get_user(conn, username) is None:
        raise HTTPException(status_code=401, detail="Log in first.")
    return username
