"""Ashby Posting API. A board response is {"jobs": [...]}. There is no single-job endpoint."""

from typing import Any

from jobpipe.models import BoardFields, Posting
from jobpipe.sources.common import (make_posting, map_employment_type, map_salary_period, map_work_mode,
                                    parse_iso_datetime)
from jobpipe.textutil import html_to_text


def parse(payload: Any, company: str) -> list[Posting]:
    jobs = payload["jobs"] if isinstance(payload, dict) and "jobs" in payload else [payload]
    return [_posting(job, company) for job in jobs if job.get("isListed", True)]


def _locations(job: dict) -> tuple[list[str], str | None]:
    locations: list[str] = []
    country = None
    entries = [{"location": job.get("location"), "address": job.get("address")}]
    entries += job.get("secondaryLocations") or []
    for entry in entries:
        name = entry.get("location")
        if name and name not in locations:
            locations.append(name)
        postal = (entry.get("address") or {}).get("postalAddress") or {}
        locality = postal.get("addressLocality")
        if locality and locality not in locations:
            locations.append(locality)
        country = country or postal.get("addressCountry")
    return locations, country


def _salary(job: dict) -> dict:
    for part in (job.get("compensation") or {}).get("summaryComponents") or []:
        if part.get("compensationType") == "Salary" and (part.get("minValue") or part.get("maxValue")):
            return {
                "salary_min": part.get("minValue"),
                "salary_max": part.get("maxValue"),
                "salary_currency": part.get("currencyCode"),
                "salary_period": map_salary_period(part.get("interval")),
            }
    return {}


def _posting(job: dict, company: str) -> Posting:
    locations, country = _locations(job)
    text = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
    return make_posting(
        source="ashby",
        source_id=job["id"],
        company=company,
        title=job["title"],
        url=job["jobUrl"],
        posted_at=parse_iso_datetime(job.get("publishedAt")),
        text=text.strip(),
        board=BoardFields(
            locations=locations,
            country=country,
            work_mode=map_work_mode(job.get("workplaceType")),
            employment_type=map_employment_type(job.get("employmentType")),
            **_salary(job),
        ),
    )
