"""Helpers shared by the board standardisers."""

from datetime import UTC, date, datetime

from jobpipe.models import BoardFields, EmploymentType, Posting, SalaryPeriod, Source, WorkMode
from jobpipe.textutil import sha256_text


def make_posting(*, source: Source, source_id: str, company: str, title: str, url: str,
                 posted_at: datetime | None, text: str, board: BoardFields) -> Posting:
    """Build a Posting. The hash covers title and text, which is what the LLM reads."""
    title = " ".join(title.split())
    return Posting(source=source, source_id=source_id, company=company, title=title, url=url,
                   posted_at=posted_at, text=text, text_hash=sha256_text(f"{title}\n\n{text}"),
                   board=board)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def from_epoch_ms(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def map_work_mode(value: str | None) -> WorkMode | None:
    key = (value or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    return {"onsite": "onsite", "inoffice": "onsite", "hybrid": "hybrid", "remote": "remote"}.get(key)


def map_employment_type(value: str | None) -> EmploymentType | None:
    text = " ".join((value or "").lower().replace("-", " ").replace("_", " ").split())
    compact = text.replace(" ", "")
    if "graduate" in text:
        return "graduate_program"
    if "intern" in text:
        return "internship"
    if any(word in text for word in ("contract", "fixed term", "max term", "temporary")):
        return "contract"
    if "parttime" in compact:
        return "part_time"
    if "fulltime" in compact or "permanent" in text:
        return "full_time"
    return None


def map_salary_period(value: str | None) -> SalaryPeriod | None:
    text = (value or "").lower()
    for period in ("year", "month", "day", "hour"):
        if period in text:
            return period
    if "annual" in text:
        return "year"
    return None
