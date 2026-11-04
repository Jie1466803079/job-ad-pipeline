"""The extraction schema.

EXTRACTION_JSON_SCHEMA is sent to the provider. It uses only plain keywords (type, properties, required,
items, enum, description, additionalProperties) and no nulls, so Gemini and Claude both accept it. The
Pydantic models validate every response again on our side.
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

WorkRightsValue = Literal["citizen_only", "citizen_or_pr", "any_work_rights", "sponsorship_available", "not_stated"]
ClearanceValue = Literal["not_stated", "baseline", "nv1", "nv2", "pv", "other"]
WorkModeValue = Literal["onsite", "hybrid", "remote", "not_stated"]
SeniorityValue = Literal["graduate_or_entry", "junior", "mid", "senior", "lead_or_above", "not_stated"]
EmploymentValue = Literal["full_time", "part_time", "contract", "internship", "graduate_program", "not_stated"]
PeriodValue = Literal["year", "month", "day", "hour", "not_stated"]

ROUTING_FIELDS = ("work_rights", "security_clearance", "closing_date", "locations", "work_mode",
                  "seniority", "employment_type", "salary")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkRightsField(_Strict):
    value: WorkRightsValue
    quote: str


class ClearanceField(_Strict):
    value: ClearanceValue
    quote: str


class ClosingDateField(_Strict):
    value: str  # YYYY-MM-DD or "not_stated"; checks.py verifies the format
    quote: str


class LocationsField(_Strict):
    value: list[str]
    quote: str


class WorkModeField(_Strict):
    value: WorkModeValue
    quote: str


class SeniorityField(_Strict):
    value: SeniorityValue
    quote: str


class EmploymentField(_Strict):
    value: EmploymentValue
    quote: str


class SalaryField(_Strict):
    stated: bool
    min: float
    max: float
    currency: str
    period: PeriodValue
    quote: str


class SkillItem(_Strict):
    skill: str
    quote: str


class ExtractionPayload(_Strict):
    work_rights: WorkRightsField
    security_clearance: ClearanceField
    closing_date: ClosingDateField
    locations: LocationsField
    work_mode: WorkModeField
    seniority: SeniorityField
    employment_type: EmploymentField
    salary: SalaryField
    required_skills: list[SkillItem]
    nice_to_have_skills: list[SkillItem]


def _choice(values: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "properties": {"value": {"type": "string", "enum": list(values)}, "quote": {"type": "string"}},
        "required": ["value", "quote"],
        "additionalProperties": False,
    }


_SKILL = {
    "type": "object",
    "properties": {"skill": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["skill", "quote"],
    "additionalProperties": False,
}

EXTRACTION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "work_rights": _choice(get_args(WorkRightsValue)),
        "security_clearance": _choice(get_args(ClearanceValue)),
        "closing_date": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "YYYY-MM-DD, or not_stated"},
                "quote": {"type": "string"},
            },
            "required": ["value", "quote"],
            "additionalProperties": False,
        },
        "locations": {
            "type": "object",
            "properties": {"value": {"type": "array", "items": {"type": "string"}}, "quote": {"type": "string"}},
            "required": ["value", "quote"],
            "additionalProperties": False,
        },
        "work_mode": _choice(get_args(WorkModeValue)),
        "seniority": _choice(get_args(SeniorityValue)),
        "employment_type": _choice(get_args(EmploymentValue)),
        "salary": {
            "type": "object",
            "properties": {
                "stated": {"type": "boolean"},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "currency": {"type": "string"},
                "period": {"type": "string", "enum": list(get_args(PeriodValue))},
                "quote": {"type": "string"},
            },
            "required": ["stated", "min", "max", "currency", "period", "quote"],
            "additionalProperties": False,
        },
        "required_skills": {"type": "array", "items": _SKILL},
        "nice_to_have_skills": {"type": "array", "items": _SKILL},
    },
    "required": ["work_rights", "security_clearance", "closing_date", "locations", "work_mode", "seniority",
                 "employment_type", "salary", "required_skills", "nice_to_have_skills"],
    "additionalProperties": False,
}


def strip_keys(schema, keys: set[str]):
    """Copy of schema without the given keys at any depth."""
    if isinstance(schema, dict):
        return {key: strip_keys(value, keys) for key, value in schema.items() if key not in keys}
    if isinstance(schema, list):
        return [strip_keys(value, keys) for value in schema]
    return schema


def not_stated_payload() -> ExtractionPayload:
    """A payload in which nothing is stated. Used by the fake extractor and as a base in tests."""
    return ExtractionPayload(
        work_rights=WorkRightsField(value="not_stated", quote=""),
        security_clearance=ClearanceField(value="not_stated", quote=""),
        closing_date=ClosingDateField(value="not_stated", quote=""),
        locations=LocationsField(value=[], quote=""),
        work_mode=WorkModeField(value="not_stated", quote=""),
        seniority=SeniorityField(value="not_stated", quote=""),
        employment_type=EmploymentField(value="not_stated", quote=""),
        salary=SalaryField(stated=False, min=0, max=0, currency="", period="not_stated", quote=""),
        required_skills=[],
        nice_to_have_skills=[],
    )
