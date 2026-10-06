"""Checks that decide whether an extracted value can be trusted. They run in code, never in the model."""

import re
from datetime import date, datetime
from typing import Literal

from dateutil import parser as date_parser
from pydantic import BaseModel

from jobpipe.llm.schema import ROUTING_FIELDS, ExtractionPayload
from jobpipe.models import Posting
from jobpipe.textutil import find_quote, normalise_for_match

AU_CITIES = ("sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra", "hobart", "darwin",
             "gold coast", "sunshine coast", "newcastle", "wollongong", "geelong", "parramatta",
             "townsville", "cairns", "launceston")

_RIGHTS_PHRASES = ("right to work", "rights to work", "working rights", "work rights", "eligible to work",
                   "eligibility to work", "entitled to work", "live and work", "permission to work",
                   "authorised to work", "authorized to work", "work permit", "visa")
_CLEARANCE_WORDS = ("baseline", "nv1", "nv2", "negative vetting", "positive vetting", "clearance")
_NO_SPONSOR = re.compile(r"\b(no|not|unable|cannot|can't|don't|do not|won't|will not)\b[^.]{0,40}sponsor")
_RANGE_K = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|to)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*k\b")
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?\b")
_COMPATIBLE_EMPLOYMENT = {frozenset({"graduate_program", "full_time"})}


class CheckResult(BaseModel):
    field: str
    name: Literal["quote_found", "matches_quote", "agrees_with_board"]
    status: Literal["pass", "fail", "na"]
    reason: str = ""
    item: str | None = None
    span: tuple[int, int] | None = None


def run_checks(posting: Posting, payload: ExtractionPayload, today: date) -> list[CheckResult]:
    text = posting.full_text
    reference = posting.posted_at.date() if posting.posted_at else today
    results: list[CheckResult] = []
    for field in ROUTING_FIELDS:
        stated, quote = _stated_and_quote(payload, field)
        found = _quote_check(field, stated, quote, text)
        results.append(found)
        if stated and found.status == "pass":
            results.append(_matches_quote(field, payload, quote, reference))
        else:
            results.append(CheckResult(field=field, name="matches_quote", status="na"))
        results.append(_agrees_with_board(field, payload, posting))
    for field in ("required_skills", "nice_to_have_skills"):
        for item in getattr(payload, field):
            check = _quote_check(field, True, item.quote, text)
            results.append(check.model_copy(update={"item": item.skill}))
    return results


def verified_closing_date(payload: ExtractionPayload, checks: list[CheckResult]) -> date | None:
    """The extracted closing date, if its quote was found and matched."""
    statuses = {c.name: c.status for c in checks if c.field == "closing_date"}
    if statuses.get("quote_found") == "pass" and statuses.get("matches_quote") == "pass":
        return date.fromisoformat(payload.closing_date.value)
    return None


def cities_in(values: list[str]) -> set[str]:
    found: set[str] = set()
    for value in values:
        text = normalise_for_match(value)
        for city in AU_CITIES:
            if re.search(rf"(?<!\w){re.escape(city)}(?!\w)", text):
                found.add(city)
    return found


def numbers_in(text: str) -> list[float]:
    """Numbers in normalised text. "120k" and the 120 in "120-140k" become thousands."""
    found = [_to_float(low) * 1000 for low, _ in _RANGE_K.findall(text)]
    found += [_to_float(number) * (1000 if k else 1) for number, k in _NUMBER.findall(text)]
    return found


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1)


def _stated_and_quote(payload: ExtractionPayload, field: str) -> tuple[bool, str]:
    value = getattr(payload, field)
    if field == "salary":
        return value.stated, value.quote
    if field == "locations":
        return bool(value.value), value.quote
    return value.value != "not_stated", value.quote


def _quote_check(field: str, stated: bool, quote: str, text: str) -> CheckResult:
    def result(status: str, reason: str = "", span: tuple[int, int] | None = None) -> CheckResult:
        return CheckResult(field=field, name="quote_found", status=status, reason=reason, span=span)

    if not stated:
        if quote.strip():
            return result("fail", "a quote was given for a value marked not stated")
        return result("pass", "not stated")
    if not quote.strip():
        return result("fail", "no quote given")
    span = find_quote(text, quote)
    if span is None:
        return result("fail", "quote not found in the ad")
    return result("pass", span=span)


def _matches_quote(field: str, payload: ExtractionPayload, quote: str, reference: date) -> CheckResult:
    def result(ok: bool, reason: str) -> CheckResult:
        return CheckResult(field=field, name="matches_quote", status="pass" if ok else "fail",
                           reason="" if ok else reason)

    q = normalise_for_match(quote)
    if field == "closing_date":
        try:
            value = date.fromisoformat(payload.closing_date.value)
        except ValueError:
            return result(False, "value is not a date in YYYY-MM-DD form")
        quoted = _date_from_quote(quote, reference)
        if quoted is None:
            return result(False, "no date could be read from the quote")
        return result(quoted == value, f"the quote says {quoted.isoformat()}")
    if field == "work_rights":
        return result(_work_rights_ok(payload.work_rights.value, q), "the quote does not support this value")
    if field == "security_clearance":
        return result(_clearance_ok(payload.security_clearance.value, q),
                      "the quote does not mention this clearance level")
    if field == "salary":
        salary = payload.salary
        numbers = numbers_in(q)
        ok = (salary.min <= salary.max and any(_close(n, salary.min, 0.005) for n in numbers)
              and any(_close(n, salary.max, 0.005) for n in numbers))
        return result(ok, "the salary figures do not match the quote")
    return CheckResult(field=field, name="matches_quote", status="na")


def _date_from_quote(quote: str, reference: date) -> date | None:
    try:
        first = date_parser.parse(quote, fuzzy=True, dayfirst=True, default=datetime(1904, 1, 1))
        second = date_parser.parse(quote, fuzzy=True, dayfirst=True, default=datetime(1908, 1, 1))
    except (ValueError, OverflowError):
        return None
    if first.year == second.year:
        return first.date()
    try:
        candidate = date(reference.year, first.month, first.day)
        if candidate < reference:
            candidate = date(reference.year + 1, first.month, first.day)
    except ValueError:
        return None
    return candidate


def _work_rights_ok(value: str, q: str) -> bool:
    citizen = "citizen" in q
    permanent = "permanent resident" in q or re.search(r"\bpr\b", q) is not None
    clearance = any(word in q for word in _CLEARANCE_WORDS)
    rights = any(phrase in q for phrase in _RIGHTS_PHRASES)
    if value == "citizen_only":
        return (citizen and not permanent) or clearance
    if value == "citizen_or_pr":
        return citizen and permanent
    if value == "any_work_rights":
        return rights
    if value == "sponsorship_available":
        return "sponsor" in q and _NO_SPONSOR.search(q) is None
    return False


def _clearance_ok(value: str, q: str) -> bool:
    if value == "baseline":
        return "baseline" in q
    if value == "nv1":
        return re.search(r"\bnv-?1\b", q) is not None or re.search(r"negative vetting (level )?1", q) is not None
    if value == "nv2":
        return re.search(r"\bnv-?2\b", q) is not None or re.search(r"negative vetting (level )?2", q) is not None
    if value == "pv":
        return re.search(r"\bpv\b", q) is not None or "positive vetting" in q
    if value == "other":
        return "clearance" in q
    return False


def _agrees_with_board(field: str, payload: ExtractionPayload, posting: Posting) -> CheckResult:
    board = posting.board

    def result(ok: bool | None, reason: str = "") -> CheckResult:
        if ok is None:
            return CheckResult(field=field, name="agrees_with_board", status="na")
        return CheckResult(field=field, name="agrees_with_board", status="pass" if ok else "fail",
                           reason="" if ok else reason)

    if field == "locations":
        ours, theirs = cities_in(payload.locations.value), cities_in(board.locations)
        if not ours or not theirs:
            return result(None)
        return result(bool(ours & theirs), f"the board lists {', '.join(sorted(theirs))}")
    if field == "work_mode":
        if board.work_mode is None or payload.work_mode.value == "not_stated":
            return result(None)
        return result(board.work_mode == payload.work_mode.value, f"the board says {board.work_mode}")
    if field == "employment_type":
        ours = payload.employment_type.value
        if board.employment_type is None or ours == "not_stated":
            return result(None)
        same = ours == board.employment_type or frozenset({ours, board.employment_type}) in _COMPATIBLE_EMPLOYMENT
        return result(same, f"the board says {board.employment_type}")
    if field == "closing_date":
        if board.deadline is None or payload.closing_date.value == "not_stated":
            return result(None)
        return result(payload.closing_date.value == board.deadline.isoformat(),
                      f"the board deadline is {board.deadline.isoformat()}")
    if field == "salary":
        salary = payload.salary
        if not salary.stated or board.salary_min is None or board.salary_max is None:
            return result(None)
        ok = _close(salary.min, board.salary_min, 0.01) and _close(salary.max, board.salary_max, 0.01)
        return result(ok, f"the board range is {board.salary_min:g} to {board.salary_max:g}")
    return result(None)
