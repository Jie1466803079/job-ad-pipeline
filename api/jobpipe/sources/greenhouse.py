"""Greenhouse Job Board API. A board response is {"jobs": [...]}; a single-job response is the job."""

from typing import Any

from jobpipe.models import BoardFields, Posting
from jobpipe.sources.common import make_posting, parse_iso_date, parse_iso_datetime
from jobpipe.textutil import html_to_text


def parse(payload: Any, company: str) -> list[Posting]:
    jobs = payload["jobs"] if isinstance(payload, dict) and "jobs" in payload else [payload]
    return [_posting(job, company) for job in jobs]


def _posting(job: dict, company: str) -> Posting:
    locations: list[str] = []
    name = (job.get("location") or {}).get("name")
    if name:
        locations.append(name)
    for office in job.get("offices") or []:
        if office.get("name") and office["name"] not in locations:
            locations.append(office["name"])
    return make_posting(
        source="greenhouse",
        source_id=str(job["id"]),
        company=company,
        title=job["title"],
        url=job["absolute_url"],
        posted_at=parse_iso_datetime(job.get("first_published") or job.get("updated_at")),
        text=html_to_text(job.get("content") or "", escaped=True),
        board=BoardFields(locations=locations, deadline=parse_iso_date(job.get("application_deadline"))),
    )
