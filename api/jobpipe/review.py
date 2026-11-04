"""Review rules that need no database: queue rows, the detail view and the actions a status allows.

Quote spans are Unicode code point offsets into compose_full_text(title, text), the text the checks ran on.
The page splits that text into code points before using them.
"""

import copy
from datetime import date
from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from jobpipe.fit import FitResult
from jobpipe.llm.schema import (
    ROUTING_FIELDS,
    ClearanceValue,
    EmploymentValue,
    PeriodValue,
    SeniorityValue,
    WorkModeValue,
    WorkRightsValue,
)
from jobpipe.models import compose_full_text

Tab = Literal["review", "tracked", "ineligible", "applied", "closed", "skipped", "dismissed"]
ApplicationStatus = Literal["tracked", "applied", "interview", "offer", "rejected"]
APPLICATION_STATUSES: tuple[str, ...] = get_args(ApplicationStatus)

# Each decision: the statuses it can be made from, and the status it sets.
DECISIONS: dict[str, tuple[frozenset[str], str]] = {
    "approve": (frozenset({"review", "skipped", "dismissed"}), "tracked"),
    "override_ineligible": (frozenset({"ineligible"}), "tracked"),
    "dismiss": (frozenset({"review", "tracked", "ineligible"}), "dismissed"),
}

FIELD_OPTIONS: dict[str, list[str]] = {
    "work_rights": list(get_args(WorkRightsValue)),
    "security_clearance": list(get_args(ClearanceValue)),
    "work_mode": list(get_args(WorkModeValue)),
    "seniority": list(get_args(SeniorityValue)),
    "employment_type": list(get_args(EmploymentValue)),
}
_SALARY_KEYS = ("stated", "min", "max", "currency", "period")


def allowed_actions(status: str, can_edit: bool) -> dict:
    return {
        "decisions": [name for name, (sources, _) in DECISIONS.items() if status in sources],
        "statuses": list(APPLICATION_STATUSES) if status in APPLICATION_STATUSES else [],
        "can_edit": can_edit,
    }


class TransitionRefused(Exception):
    """The ad's status does not allow this action."""


def decision_target(decision: str, status: str) -> str:
    """The status a decision moves an ad to. Raises TransitionRefused when the status does not allow it."""
    sources, target = DECISIONS[decision]
    if status not in sources:
        raise TransitionRefused(f"An ad that is {status} cannot get the decision {decision}.")
    return target


def check_status_change(status: str) -> None:
    """Application statuses can be set only once an ad is tracked."""
    if status not in APPLICATION_STATUSES:
        raise TransitionRefused(f"Approve the ad before setting an application status. It is {status}.")


Place = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class SalaryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stated: bool
    min: float = Field(default=0, ge=0)
    max: float = Field(default=0, ge=0)
    currency: str = Field(default="", max_length=10)
    period: PeriodValue = "not_stated"

    @model_validator(mode="after")
    def _complete_when_stated(self) -> Self:
        if self.stated and (self.min > self.max or self.period == "not_stated"):
            raise ValueError("a stated salary needs a minimum no higher than its maximum, and a pay period")
        return self


class FieldEdits(BaseModel):
    """A reviewer's corrections. Only the fields that are sent are stored."""

    model_config = ConfigDict(extra="forbid")

    work_rights: WorkRightsValue | None = None
    security_clearance: ClearanceValue | None = None
    closing_date: date | Literal["not_stated"] | None = None
    locations: Annotated[list[Place], Field(max_length=20)] | None = None
    work_mode: WorkModeValue | None = None
    seniority: SeniorityValue | None = None
    employment_type: EmploymentValue | None = None
    salary: SalaryEdit | None = None

    @field_validator("locations")
    @classmethod
    def _drop_empty_places(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [place for place in value if place]

    def changes(self) -> dict:
        """The corrections as stored in reviews.edited_fields. A salary is always stored whole."""
        changes = self.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if self.salary is not None:
            salary = self.salary if self.salary.stated else SalaryEdit(stated=False)
            changes["salary"] = salary.model_dump(mode="json")
        return changes


def apply_edits(fields: dict, edits: list[dict]) -> tuple[dict, set[str]]:
    """The extracted fields with the reviewer's corrections laid over them in order, and the names corrected."""
    current = copy.deepcopy(fields)
    edited: set[str] = set()
    for edit in edits:
        for name, value in edit.items():
            if name == "salary":
                current["salary"] = {**value, "quote": current["salary"]["quote"]}
            else:
                current[name] = {**current[name], "value": value}
            edited.add(name)
    return current, edited


def edits_for(extraction: dict | None, reviews: list[dict]) -> list[dict]:
    """Corrections made to this extraction, oldest first. Corrections to older extractions do not apply."""
    if extraction is None:
        return []
    return [review["edited_fields"] for review in reviews
            if review["action"] == "edit" and review["extraction_id"] == extraction["id"]]


def field_views(fields: dict, checks: list[dict], edits: list[dict]) -> list[dict]:
    """The eight routing fields: current value, the model's value, quote, quote span and check results."""
    current, edited = apply_edits(fields, edits)
    views = []
    for name in ROUTING_FIELDS:
        own = [check for check in checks if check["field"] == name]
        found = next((check for check in own if check["name"] == "quote_found"), None)
        views.append({
            "name": name,
            "value": _value(name, current[name]),
            "extracted": _value(name, fields[name]),
            "edited": name in edited,
            "quote": fields[name]["quote"],
            "span": found["span"] if found and found["status"] == "pass" else None,
            "checks": [{"name": check["name"], "status": check["status"], "reason": check["reason"]}
                       for check in own],
            "options": FIELD_OPTIONS.get(name),
        })
    return views


def skill_views(fields: dict, checks: list[dict]) -> dict:
    """Skills and whether their quote was found. checks holds one quote check per skill, in the same order."""
    views = {}
    for field, key in (("required_skills", "required"), ("nice_to_have_skills", "nice_to_have")):
        own = [check for check in checks if check["field"] == field]
        items = []
        for index, item in enumerate(fields[field]):
            check = own[index] if index < len(own) else None
            verified = bool(check and check["status"] == "pass")
            items.append({"skill": item["skill"], "quote": item["quote"], "verified": verified,
                          "span": check["span"] if verified else None})
        views[key] = items
    return views


def queue_item(row: dict) -> dict:
    """One row of a queue tab, from a repo.list_postings row."""
    fields = apply_edits(row["fields"], row["edits"])[0] if row["fields"] else None
    locations = fields["locations"]["value"] if fields else []
    fit = row["fit"]
    return {
        "id": row["id"], "company": row["company"], "title": row["title"], "url": row["url"],
        "status": row["status"], "closed": row["closed_at"] is not None,
        "locations": locations or row["board"].get("locations", []),
        "work_rights": fields["work_rights"]["value"] if fields else None,
        "closing_date": row["closing_date"],
        "fit": {"matched": len(fit["matched"]), "total": fit["total"]} if fit else None,
        "reasons": row["reasons"] or [],
        "skip_reason": row["skip_reason"],
    }


def history(extractions: list[dict], reviews: list[dict]) -> list[dict]:
    """What happened to the ad, newest first."""
    events = [{"kind": "extraction", "at": e["created_at"], "model": e["model"], "route": e["route"],
               "failed": e["failed"]} for e in extractions]
    events += [{"kind": "review", "at": r["created_at"], "username": r["username"], "action": r["action"],
                "fields": sorted(r["edited_fields"] or {}), "from_status": r["from_status"],
                "to_status": r["to_status"]} for r in reviews]
    return sorted(events, key=lambda event: event["at"], reverse=True)


def build_detail(posting: dict, extraction: dict | None, extractions: list[dict], reviews: list[dict]) -> dict:
    """Everything the detail page shows. extraction is the newest one made from the ad's current text."""
    fields = extraction["fields"] if extraction else None
    checks = extraction["checks"] if extraction else []
    fit = extraction["fit"] if extraction else None
    text = posting["text"]
    return {
        "id": posting["id"], "company": posting["company"], "title": posting["title"], "url": posting["url"],
        "source": posting["source"], "status": posting["status"], "closing_date": posting["closing_date"],
        "closed_at": posting["closed_at"], "posted_at": posting["posted_at"],
        "skip_reason": posting["skip_reason"],
        "text": compose_full_text(posting["title"], text) if text is not None else None,
        "text_deleted_at": posting["text_deleted_at"],
        "extraction": None if extraction is None else {
            "provider": extraction["provider"], "model": extraction["model"],
            "created_at": extraction["created_at"], "route": extraction["route"],
            "reasons": extraction["reasons"], "failed": fields is None,
        },
        "fields": field_views(fields, checks, edits_for(extraction, reviews)) if fields else [],
        "skills": skill_views(fields, checks) if fields else {"required": [], "nice_to_have": []},
        "fit": {**fit, "summary": FitResult(**fit).summary()} if fit else None,
        "history": history(extractions, reviews),
        "actions": allowed_actions(posting["status"], can_edit=fields is not None),
    }


def _value(name: str, field: dict):
    if name == "salary":
        return {key: field[key] for key in _SALARY_KEYS}
    return field["value"]
