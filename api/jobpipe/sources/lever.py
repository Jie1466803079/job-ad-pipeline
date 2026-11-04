"""Lever Postings API. A board response is a list; a single-posting response is the posting."""

from typing import Any

from jobpipe.models import BoardFields, Posting
from jobpipe.sources.common import (
    from_epoch_ms,
    make_posting,
    map_employment_type,
    map_salary_period,
    map_work_mode,
)
from jobpipe.textutil import html_to_text


def parse(payload: Any, company: str) -> list[Posting]:
    jobs = payload if isinstance(payload, list) else [payload]
    return [_posting(job, company) for job in jobs]


def _posting(job: dict, company: str) -> Posting:
    categories = job.get("categories") or {}
    locations = list(categories.get("allLocations") or [])
    if categories.get("location") and categories["location"] not in locations:
        locations.insert(0, categories["location"])
    sections = [job.get("descriptionPlain") or ""]
    for item in job.get("lists") or []:
        heading = (item.get("text") or "").strip()
        sections.append(f"{heading}\n{html_to_text(item.get('content') or '')}")
    sections.append(job.get("additionalPlain") or "")
    text = "\n\n".join(section.strip() for section in sections if section.strip())
    salary = job.get("salaryRange") or {}
    salary_min = salary.get("min") or None
    salary_max = salary.get("max") or None
    has_salary = salary_min is not None or salary_max is not None
    return make_posting(
        source="lever",
        source_id=job["id"],
        company=company,
        title=job["text"],
        url=job["hostedUrl"],
        posted_at=from_epoch_ms(job.get("createdAt")),
        text=text,
        board=BoardFields(
            locations=locations,
            country=job.get("country"),
            work_mode=map_work_mode(job.get("workplaceType")),
            employment_type=map_employment_type(categories.get("commitment")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary.get("currency") if has_salary else None,
            salary_period=map_salary_period(salary.get("interval")) if has_salary else None,
        ),
    )
