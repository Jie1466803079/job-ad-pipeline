"""FastAPI dependencies."""

import hmac
from collections.abc import Iterator

from fastapi import Header, HTTPException, Request
from psycopg import Connection

from jobpipe import db


def get_conn(request: Request) -> Iterator[Connection]:
    with db.connect(request.app.state.settings.database_url) as conn:
        yield conn


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.machine_api_key
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid API key")
