"""Routes for the review page. Every request needs a logged-in session."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection
from pydantic import BaseModel

from jobpipe import repo, review
from jobpipe.deps import get_conn, require_user

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


class DecisionRequest(BaseModel):
    decision: Literal["approve", "dismiss", "override_ineligible"]


class StatusRequest(BaseModel):
    status: review.ApplicationStatus


@router.get("/postings")
def list_postings(tab: review.Tab = "review", limit: int = Query(default=200, ge=1, le=500),
                  conn: Connection = Depends(get_conn)) -> dict:
    rows, total = repo.list_postings(conn, tab, limit)
    return {"tab": tab, "total": total, "items": [review.queue_item(row) for row in rows]}


@router.get("/postings/{posting_id}")
def get_posting(posting_id: int, conn: Connection = Depends(get_conn)) -> dict:
    return _detail(conn, posting_id)


@router.patch("/postings/{posting_id}/fields")
def correct_fields(posting_id: int, body: review.FieldEdits, username: str = Depends(require_user),
                   conn: Connection = Depends(get_conn)) -> dict:
    posting = _posting(conn, posting_id)
    extraction = repo.current_extraction(conn, posting_id)
    if extraction is None or extraction["fields"] is None:
        raise HTTPException(status_code=409, detail="This ad has no extracted values to correct.")
    changes = body.changes()
    if not changes:
        raise HTTPException(status_code=422, detail="Send at least one field to correct.")
    repo.insert_review(conn, posting_id, extraction["id"], username, "edit", edited_fields=changes)
    if "closing_date" in changes:
        repo.set_closing_date(conn, posting_id, _closing_date(changes["closing_date"], posting["board"]))
    conn.commit()
    return _detail(conn, posting_id)


@router.post("/postings/{posting_id}/decision")
def decide(posting_id: int, body: DecisionRequest, username: str = Depends(require_user),
           conn: Connection = Depends(get_conn)) -> dict:
    posting = _posting(conn, posting_id)
    try:
        target = review.decision_target(body.decision, posting["status"])
    except review.TransitionRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _change_status(conn, posting, username, body.decision, target)
    return _detail(conn, posting_id)


@router.patch("/postings/{posting_id}/status")
def set_application_status(posting_id: int, body: StatusRequest, username: str = Depends(require_user),
                           conn: Connection = Depends(get_conn)) -> dict:
    posting = _posting(conn, posting_id)
    try:
        review.check_status_change(posting["status"])
    except review.TransitionRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if body.status != posting["status"]:
        _change_status(conn, posting, username, "set_status", body.status)
    return _detail(conn, posting_id)


def _posting(conn: Connection, posting_id: int) -> dict:
    posting = repo.get_posting(conn, posting_id)
    if posting is None:
        raise HTTPException(status_code=404, detail="There is no ad with this id.")
    return posting


def _detail(conn: Connection, posting_id: int) -> dict:
    posting = _posting(conn, posting_id)
    return review.build_detail(posting, repo.current_extraction(conn, posting_id),
                               repo.extraction_history(conn, posting_id), repo.reviews_for(conn, posting_id))


def _change_status(conn: Connection, posting: dict, username: str, action: str, target: str) -> None:
    """Set a status a person chose and record it. Refused when the status changed since it was read."""
    if not repo.decide_status(conn, posting["id"], posting["status"], target):
        conn.rollback()
        raise HTTPException(status_code=409, detail="The ad changed while you were looking at it. Reload it.")
    extraction = repo.current_extraction(conn, posting["id"])
    repo.insert_review(conn, posting["id"], extraction["id"] if extraction else None, username, action,
                       from_status=posting["status"], to_status=target)
    conn.commit()


def _closing_date(value: str, board: dict) -> date | None:
    """A corrected closing date. not_stated falls back to the board's deadline, as the pipeline does."""
    if value != "not_stated":
        return date.fromisoformat(value)
    return date.fromisoformat(board["deadline"]) if board.get("deadline") else None
