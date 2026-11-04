"""The rules baseline: regular expressions and keyword lists for the eight fields.

It reads the same ad text as the LLM and answers through the same interface, so the evaluation sends its
answers through the same checks and routing. A field the rules notice but cannot settle, such as a closing-date
sentence with no date the rules can read, comes back as not_stated with that sentence as its quote. The quote
check fails on that, so the ad goes to review: the baseline sends an ad to the tracker only when every field
was found.
"""

import re
import time
from datetime import date

from jobpipe.checks import AU_CITIES, date_from_quote
from jobpipe.llm.base import ExtractionResult, LLMUsage
from jobpipe.llm.schema import (
    ClearanceField,
    ClosingDateField,
    EmploymentField,
    ExtractionPayload,
    LocationsField,
    SalaryField,
    SeniorityField,
    WorkModeField,
    WorkRightsField,
)
from jobpipe.models import Posting
from jobpipe.textutil import normalise_for_match

_BOILERPLATE = re.compile(r"regardless of|irrespective of|without regard|(don't|do not) regard|discriminat"
                          r"|equal opportunit|equal employment")
_NEGATION = r"\b(no|not|without|don't|do not|doesn't|does not|isn't|is not|unable|cannot|can't|won't|will not)\b[^.]{0,40}"
_RIGHTS_TOPIC = re.compile(r"citizen|permanent residen|\bpr\b|\bvisas?\b|sponsor|work(ing)? rights|rights? to work"
                           r"|eligib\w* to work|entitled to work|authori[sz]ed to work|work permit")
_RIGHTS_PHRASE = re.compile(r"work(ing)? rights|rights? to work|eligib\w* to work|entitled to work"
                            r"|authori[sz]ed to work|work permit")
_NO_SPONSOR = re.compile(_NEGATION + r"sponsor")
_NO_CITIZEN = re.compile(_NEGATION + r"citizen")
_CLEARANCE_TOPIC = re.compile(r"clearance|vetting|\bnv-?[12]\b|\bagsva\b")
_NO_CLEARANCE = re.compile(_NEGATION + r"(clearance|vetting)")
_LEVELS = (("baseline", r"\bbaseline\b"), ("nv1", r"\bnv-?1\b|negative vetting (level )?1"),
           ("nv2", r"\bnv-?2\b|negative vetting (level )?2"), ("pv", r"\bpv\b|positive vetting"))
_CLOSING = re.compile(r"applications? (close|closes|closing|are due|due)|closing date|apply by|apply before"
                      r"|application deadline|deadline for applications")
_LOCATION_CUE = re.compile(r"based in|located in|location|office|hybrid|remote|on-?site|work from|relocat")
_MODES = (("hybrid", r"\bhybrid\b|days? (a|per) week in (the|our) office"),
          ("remote", r"fully remote|remote-first|remote first|100% remote|work from home|\bremote (role|position)"),
          ("onsite", r"\bon-?site\b|in-office|office-based|office based|in the office (five|5) days"))
_TITLE_LEVELS = (("graduate_or_entry", r"\b(intern|internship|graduate|grad|entry level|entry-level)\b"),
                 ("junior", r"\b(junior|jr)\b"),
                 ("lead_or_above", r"\b(lead|staff|principal|head|manager|director)\b"),
                 ("senior", r"\b(senior|sr)\b"))
_YEARS = re.compile(r"(\d+)\+?\s*(?:(?:-|to)\s*\d+\s*)?years?")
_EMPLOYMENT = (("graduate_program", r"graduate (program|programme)"), ("internship", r"\bintern(ship)?\b"),
               ("contract", r"(?<!smart )\bcontract\b|fixed-term|fixed term|maximum term|max term|\btemporary\b"),
               ("part_time", r"part-time|part time"),
               ("full_time", r"full-time|full time|\bpermanent\b(?! residen)"))
_PAY_CUE = re.compile(r"salary|\bpay\b|compensation|remuneration|package|\bbase\b|range|per annum|\bp\.?a\b|\bote\b"
                      r"|per hour|hourly|day rate")
_MONEY = r"(aud|usd|nzd|sgd|a\$|us\$|\$)\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_RANGE = re.compile(_MONEY + r"\s*(?:-|to)\s*(?:aud|usd|nzd|sgd|a\$|us\$|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\b")
_SINGLE = re.compile(_MONEY + r"\b")
_PERIODS = (("hour", r"per hour|an hour|hourly|/hr\b|/hour"), ("day", r"per day|a day\b|daily|day rate|/day"),
            ("month", r"per month|a month\b|monthly|/month"),
            ("year", r"per annum|\bp\.?a\b|per year|a year\b|annual|/yr\b|/year|yearly"))
_CURRENCIES = {"usd": "USD", "us$": "USD", "nzd": "NZD", "sgd": "SGD"}


def _sentences(text: str) -> list[str]:
    """Lines and sentences of the ad as written, each cut to 300 characters, so each one is a valid quote."""
    pieces = (piece.strip() for piece in re.split(r"(?<=[.!?])\s+|\n+", text))
    return [piece[:300] for piece in pieces if piece]


def _settle(found: dict[str, str]) -> tuple[str, str]:
    """One value found: that value and its sentence. Several: not settled. None: not stated."""
    if len(found) == 1:
        return next(iter(found.items()))
    if found:
        return "not_stated", next(iter(found.values()))
    return "not_stated", ""


def _work_rights(sentences: list[str], clearance_sentence: str) -> tuple[str, str]:
    found: dict[str, str] = {}
    unread = ""
    for sentence in sentences:
        q = normalise_for_match(sentence)
        if not _RIGHTS_TOPIC.search(q) or _BOILERPLATE.search(q):
            continue
        citizen = "citizen" in q and not _NO_CITIZEN.search(q)
        permanent = "permanent residen" in q or re.search(r"\bpr\b", q) is not None
        if citizen and permanent:
            value = "citizen_or_pr"
        elif citizen:
            value = "citizen_only"
        elif "sponsor" in q and not _NO_SPONSOR.search(q):
            value = "sponsorship_available"
        elif _RIGHTS_PHRASE.search(q) or _NO_SPONSOR.search(q) or re.search(r"\bvisas?\b", q):
            value = "any_work_rights"
        else:
            unread = unread or sentence
            continue
        found.setdefault(value, sentence)
    if len(found) > 1:
        found.pop("any_work_rights", None)  # a more specific statement wins over a general one
    if not found and clearance_sentence:
        return "citizen_only", clearance_sentence  # Australian clearances are for citizens only
    if not found and unread:
        return "not_stated", unread
    return _settle(found)


def _clearance(sentences: list[str]) -> tuple[str, str]:
    named: list[tuple[int, str]] = []
    general = ""
    for sentence in sentences:
        q = normalise_for_match(sentence)
        if not _CLEARANCE_TOPIC.search(q) or _NO_CLEARANCE.search(q):
            continue
        levels = [index for index, (_, pattern) in enumerate(_LEVELS) if re.search(pattern, q)]
        if levels:
            named.append((min(levels), sentence))  # several levels named: the lowest
        elif "clearance" in q:
            general = general or sentence
    if named:
        index, sentence = min(named, key=lambda item: item[0])
        return _LEVELS[index][0], sentence
    if general:
        return "other", general
    return "not_stated", ""


def _closing_date(sentences: list[str], reference: date) -> tuple[str, str]:
    for sentence in sentences:
        if _CLOSING.search(normalise_for_match(sentence)):
            day = date_from_quote(sentence, reference)
            return (day.isoformat(), sentence) if day else ("not_stated", sentence)
    return "not_stated", ""


def _locations(sentences: list[str]) -> tuple[list[str], str]:
    places: list[str] = []
    quote = ""
    for index, sentence in enumerate(sentences):
        q = normalise_for_match(sentence)
        if index > 0 and not _LOCATION_CUE.search(q):  # the first piece is the title
            continue
        found = [city.title() for city in AU_CITIES if re.search(rf"(?<!\w){re.escape(city)}(?!\w)", q)]
        if re.search(r"\bremote\b", q) and re.search(r"australia|\banz\b|\bapac\b", q):
            found.append("Remote, Australia")
        new = [place for place in found if place not in places]
        if new:
            places += new
            quote = quote or sentence
    return places, quote


def _work_mode(sentences: list[str]) -> tuple[str, str]:
    found: dict[str, str] = {}
    for sentence in sentences:
        q = normalise_for_match(sentence)
        for value, pattern in _MODES:
            if re.search(pattern, q):
                found.setdefault(value, sentence)
                break
    if "hybrid" in found:
        return "hybrid", found["hybrid"]  # hybrid roles also talk about remote days and office days
    return _settle(found)


def _seniority(title: str, sentences: list[str]) -> tuple[str, str]:
    t = normalise_for_match(title)
    for value, pattern in _TITLE_LEVELS:
        if re.search(pattern, t):
            return value, title
    for sentence in sentences:
        q = normalise_for_match(sentence)
        match = _YEARS.search(q) if "experience" in q else None
        if match:
            years = int(match.group(1))
            value = "graduate_or_entry" if years < 1 else "junior" if years < 3 else "mid" if years < 5 else "senior"
            return value, sentence
    return "not_stated", ""


def _employment(sentences: list[str]) -> tuple[str, str]:
    found: dict[str, str] = {}
    for sentence in sentences:
        q = normalise_for_match(sentence)
        for value, pattern in _EMPLOYMENT:
            if re.search(pattern, q):
                found.setdefault(value, sentence)
    if "graduate_program" in found:
        found.pop("full_time", None)  # a graduate program is a full-time job
    return _settle(found)


def _amount(number: str, thousands: str | None) -> float:
    return float(number.replace(",", "")) * (1000 if thousands else 1)


def _no_salary(quote: str = "") -> SalaryField:
    return SalaryField(stated=False, min=0, max=0, currency="", period="not_stated", quote=quote)


def _salary(sentences: list[str]) -> SalaryField:
    for sentence in sentences:
        q = normalise_for_match(sentence)
        if not _PAY_CUE.search(q):
            continue
        match = _RANGE.search(q)
        if match:
            symbol, low, low_k, high, high_k = match.groups()
            minimum, maximum = _amount(low, low_k), _amount(high, high_k)
            if high_k and not low_k and minimum < 1000:  # "$120 - $140k"
                minimum *= 1000
        else:
            match = _SINGLE.search(q)
            if not match:
                continue
            symbol, low, low_k = match.groups()
            minimum = maximum = _amount(low, low_k)
        period = next((name for name, pattern in _PERIODS if re.search(pattern, q)), None)
        if period is None and minimum >= 20000:
            period = "year"
        if period is None or minimum > maximum:
            return _no_salary(sentence)  # money in a pay sentence that the rules cannot read: not settled
        return SalaryField(stated=True, min=minimum, max=maximum, currency=_CURRENCIES.get(symbol, "AUD"),
                           period=period, quote=sentence)
    return _no_salary()


class RulesExtractor:
    provider = "rules"
    model = "rules-1"

    def extract(self, posting: Posting) -> ExtractionResult:
        started = time.monotonic()
        sentences = _sentences(posting.full_text)
        reference = posting.posted_at.date() if posting.posted_at else date.today()
        clearance, clearance_quote = _clearance(sentences)
        rights, rights_quote = _work_rights(sentences, clearance_quote if clearance != "not_stated" else "")
        closing, closing_quote = _closing_date(sentences, reference)
        places, places_quote = _locations(sentences)
        mode, mode_quote = _work_mode(sentences)
        level, level_quote = _seniority(posting.title, sentences)
        employment, employment_quote = _employment(sentences)
        payload = ExtractionPayload(
            work_rights=WorkRightsField(value=rights, quote=rights_quote),
            security_clearance=ClearanceField(value=clearance, quote=clearance_quote),
            closing_date=ClosingDateField(value=closing, quote=closing_quote),
            locations=LocationsField(value=places, quote=places_quote),
            work_mode=WorkModeField(value=mode, quote=mode_quote),
            seniority=SeniorityField(value=level, quote=level_quote),
            employment_type=EmploymentField(value=employment, quote=employment_quote),
            salary=_salary(sentences),
            required_skills=[],
            nice_to_have_skills=[],
        )
        usage = LLMUsage(provider=self.provider, model=self.model,
                         latency_ms=int((time.monotonic() - started) * 1000))
        return ExtractionResult(payload=payload, usage=usage)
