"""Reviewer login. The session lives in a signed cookie set by Starlette's SessionMiddleware."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg import Connection
from pydantic import BaseModel, Field

from jobpipe import auth
from jobpipe.deps import get_conn, require_user

router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(body: LoginRequest, request: Request, conn: Connection = Depends(get_conn)) -> dict:
    result = auth.login(conn, body.username, body.password, now=datetime.now(UTC))
    conn.commit()
    if result.locked_minutes:
        minutes = "1 minute" if result.locked_minutes == 1 else f"{result.locked_minutes} minutes"
        raise HTTPException(status_code=429, detail=f"Too many failed logins. Try again in {minutes}.")
    if not result.ok:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    request.session.clear()
    request.session["username"] = result.username
    return {"username": result.username}


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)


@router.get("/me")
def me(username: str = Depends(require_user)) -> dict:
    return {"username": username}
