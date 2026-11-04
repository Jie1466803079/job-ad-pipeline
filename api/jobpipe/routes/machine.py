"""Routes called by n8n. Every request needs the X-API-Key header."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel

from jobpipe import repo
from jobpipe.clock import sydney_today
from jobpipe.deps import get_conn, require_api_key
from jobpipe.digest_email import render_digest
from jobpipe.pipeline import Pipeline, UnreadablePayload
from jobpipe.sources.urls import LinkRejected, board_api_url, resolve_link

router = APIRouter(prefix="/machine", dependencies=[Depends(require_api_key)])


class IngestRequest(BaseModel):
    company_id: int
    source: str
    payload: Any
    complete: bool = False
    only_source_id: str | None = None


class ResolveRequest(BaseModel):
    url: str


@router.get("/companies")
def companies(names: str = "", conn: Connection = Depends(get_conn)) -> list[dict]:
    """Active companies, each with its board's API address. names (comma-separated) picks some of them."""
    rows = repo.active_companies(conn)
    wanted = {name.strip() for name in names.split(",") if name.strip()}
    unknown = wanted - {row["name"] for row in rows}
    if unknown:
        raise HTTPException(status_code=422, detail=f"not active companies: {', '.join(sorted(unknown))}")
    return [row | {"api_url": board_api_url(row["source"], row["slug"])}
            for row in rows if not wanted or row["name"] in wanted]


@router.post("/ingest")
def ingest(body: IngestRequest, request: Request, conn: Connection = Depends(get_conn)) -> dict:
    company = repo.get_company(conn, body.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="unknown company")
    if company["source"] != body.source:
        raise HTTPException(status_code=422,
                            detail=f"{company['name']} is on {company['source']}, not {body.source}")
    state = request.app.state
    pipeline = Pipeline(conn, state.extractor, state.filters, state.profile, state.prices)
    try:
        counts, outcomes = pipeline.ingest(company, body.payload, complete=body.complete,
                                           only_source_id=body.only_source_id)
    except UnreadablePayload as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"counts": asdict(counts), "outcomes": [asdict(outcome) for outcome in outcomes]}


@router.post("/links/resolve")
def resolve(body: ResolveRequest, conn: Connection = Depends(get_conn)):
    try:
        link = resolve_link(body.url)
    except LinkRejected as exc:
        return JSONResponse(status_code=400, content={"allowed": False, "reason": str(exc)})
    company = repo.ensure_company(conn, link.source, link.slug, name=link.slug)
    conn.commit()
    return {"allowed": True, "source": link.source, "company_id": company["id"], "job_id": link.job_id,
            "api_url": link.api_url}


@router.get("/digest")
def digest(conn: Connection = Depends(get_conn)) -> dict:
    since = datetime.now(UTC) - timedelta(hours=24)
    return repo.digest(conn, since=since, today=sydney_today())


@router.get("/digest/email")
def digest_email(request: Request, conn: Connection = Depends(get_conn)) -> dict:
    today = sydney_today()
    since = datetime.now(UTC) - timedelta(hours=24)
    email = render_digest(repo.digest(conn, since=since, today=today), today,
                          request.app.state.settings.review_url)
    return asdict(email)


@router.post("/maintenance")
def maintenance(conn: Connection = Depends(get_conn)) -> dict:
    closed = repo.close_past_deadline(conn, sydney_today())
    deleted = repo.delete_old_text(conn)
    conn.commit()
    return {"closed": closed, "text_deleted": deleted}
