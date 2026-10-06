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
from jobpipe.pipeline import Pipeline
from jobpipe.sources.urls import LinkRejected, resolve_link

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
def companies(conn: Connection = Depends(get_conn)) -> list[dict]:
    return repo.active_companies(conn)


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
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"could not read the {body.source} response: {exc!r}") from exc
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


@router.post("/maintenance")
def maintenance(conn: Connection = Depends(get_conn)) -> dict:
    closed = repo.close_past_deadline(conn, sydney_today())
    deleted = repo.delete_old_text(conn)
    conn.commit()
    return {"closed": closed, "text_deleted": deleted}
