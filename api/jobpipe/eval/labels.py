"""eval/labels.csv: the eight fields of each ad, filled in by a person who has not seen any model output.

    python -m jobpipe.eval.labels     check the file and count the ads labelled so far
"""

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel

from jobpipe.eval.files import EVAL_DIR
from jobpipe.llm.schema import (
    ROUTING_FIELDS,
    ClearanceValue,
    EmploymentValue,
    SeniorityValue,
    WorkModeValue,
    WorkRightsValue,
)

COLUMNS = ["id", "company", "title", "url", *ROUTING_FIELDS, "notes"]
CHOICES = {
    "work_rights": get_args(WorkRightsValue),
    "security_clearance": get_args(ClearanceValue),
    "work_mode": get_args(WorkModeValue),
    "seniority": get_args(SeniorityValue),
    "employment_type": get_args(EmploymentValue),
}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_FIRST = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})$")
_SALARY = re.compile(r"^(\d[\d,]*(?:\.\d+)?)(?:\s*-\s*(\d[\d,]*(?:\.\d+)?))?\s+([a-z]{3})\s+(year|month|day|hour)$")


class Salary(BaseModel):
    min: float
    max: float
    currency: str
    period: Literal["year", "month", "day", "hour"]


class Labels(BaseModel):
    work_rights: WorkRightsValue
    security_clearance: ClearanceValue
    closing_date: date | Literal["not_stated"]
    locations: list[str]
    work_mode: WorkModeValue
    seniority: SeniorityValue
    employment_type: EmploymentValue
    salary: Salary | Literal["not_stated"]


class LabelError(ValueError):
    pass


def parse_cell(field: str, raw: str):
    """One cell as a label value. Raises LabelError with a message a person can act on."""
    value = " ".join(raw.split())
    lowered = value.lower()
    if field in CHOICES:
        if lowered not in CHOICES[field]:
            raise LabelError(f"'{value}' is not one of: {', '.join(CHOICES[field])}")
        return lowered
    if lowered == "not_stated":
        return [] if field == "locations" else "not_stated"
    if field == "closing_date":
        return _parse_date(value)
    if field == "locations":
        return [place.strip() for place in value.split(";") if place.strip()]
    if field == "salary":
        return _parse_salary(lowered, value)
    raise LabelError(f"'{field}' is not a labelled field")


def _parse_date(value: str) -> date:
    try:
        if _ISO_DATE.match(value):
            return date.fromisoformat(value)
        match = _DAY_FIRST.match(value)
        if match:
            day, month, year = (int(part) for part in match.groups())
            return date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        pass
    raise LabelError(f"'{value}' is not a date such as 2026-10-31, or not_stated")


def _parse_salary(lowered: str, value: str) -> Salary:
    match = _SALARY.match(lowered)
    if not match:
        raise LabelError(f"'{value}' is not a salary such as '120000-140000 AUD year', or not_stated")
    low, high, currency, period = match.groups()
    low_value = float(low.replace(",", ""))
    high_value = float(high.replace(",", "")) if high else low_value
    if low_value > high_value:
        raise LabelError(f"'{value}' has a minimum above its maximum")
    return Salary(min=low_value, max=high_value, currency=currency.upper(), period=period)


def read_labels(path: Path) -> tuple[dict[str, Labels], list[str], list[str]]:
    """The labels by ad id, the ids not labelled yet, and every problem found.

    A row whose eight fields are all blank is not labelled yet. A row with any of them filled in needs all
    eight, so a half-finished row is reported instead of being scored.
    """
    labels: dict[str, Labels] = {}
    unlabelled: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    # Excel's plain "CSV" format is not UTF-8. Only titles and notes can hold other characters, and neither is
    # scored, so an unreadable byte becomes a replacement character instead of stopping the check.
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column != "notes" and column not in (reader.fieldnames or [])]
        if missing:
            return {}, [], [f"{path.name} has no column called {', '.join(missing)}"]
        for line, row in enumerate(reader, start=2):
            ad_id = (row.get("id") or "").strip()
            if not ad_id:
                if any(isinstance(cell, str) and cell.strip() for cell in row.values()):
                    problems.append(f"line {line}: the id is blank")
                continue
            if ad_id in seen:
                problems.append(f"line {line}: {ad_id} appears twice")
                continue
            seen.add(ad_id)
            cells = {field: row.get(field) or "" for field in ROUTING_FIELDS}
            if not any(cell.strip() for cell in cells.values()):
                unlabelled.append(ad_id)
                continue
            values, row_problems = {}, []
            for field, cell in cells.items():
                if not cell.strip():
                    row_problems.append(f"line {line} ({ad_id}): {field} is blank")
                    continue
                try:
                    values[field] = parse_cell(field, cell)
                except LabelError as exc:
                    row_problems.append(f"line {line} ({ad_id}): {field} {exc}")
            if row_problems:
                problems += row_problems
            else:
                labels[ad_id] = Labels(**values)
    return labels, unlabelled, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check eval/labels.csv and count the ads labelled so far.")
    parser.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    args = parser.parse_args(argv)
    path = args.eval_dir / "labels.csv"
    if not path.exists():
        print(f"{path} does not exist yet. Run make eval-sample first.")
        return 1
    labels, unlabelled, problems = read_labels(path)
    for problem in problems:
        print(problem)
    print(f"Labelled: {len(labels)}. Not labelled yet: {len(unlabelled)}. Problems: {len(problems)}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
