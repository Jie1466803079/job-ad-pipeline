"""Routes for the review page. Every request needs a logged-in session."""

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from jobpipe import repo, review
from jobpipe.deps import get_conn, require_user

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


@router.get("/postings")
def list_postings(tab: review.Tab = "review", limit: int = Query(default=200, ge=1, le=500),
                  conn: Connection = Depends(get_conn)) -> dict:
    rows, total = repo.list_postings(conn, tab, limit)
    return {"tab": tab, "total": total, "items": [review.queue_item(row) for row in rows]}


@router.get("/postings/{posting_id}")
def get_posting(posting_id: int, conn: Connection = Depends(get_conn)) -> dict:
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
