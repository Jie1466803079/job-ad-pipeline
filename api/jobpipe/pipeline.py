"""Process one board response: standardise, filter, extract, check, route and store each ad."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import Connection

from jobpipe import repo
from jobpipe.checks import run_checks, verified_closing_date
from jobpipe.clock import sydney_today
from jobpipe.configfiles import FilterConfig, Price, Profile
from jobpipe.fit import fit_score
from jobpipe.llm.base import ExtractionError, Extractor, LLMUsage
from jobpipe.llm.pricing import cost_usd
from jobpipe.models import Posting
from jobpipe.prefilter import prefilter
from jobpipe.routing import decide_route
from jobpipe.sources import standardise

HUMAN_STATUSES = {"dismissed", "applied", "interview", "offer", "rejected"}


class UnreadablePayload(Exception):
    """The board response is not in the shape its source uses."""


@dataclass
class IngestCounts:
    fetched: int = 0
    created: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    extracted: int = 0
    tracked: int = 0
    review: int = 0
    ineligible: int = 0
    closed: int = 0
    failed: int = 0


@dataclass
class PostingOutcome:
    source_id: str
    posting_id: int
    title: str
    action: str
    status: str
    reasons: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, conn: Connection, extractor: Extractor, filters: FilterConfig, profile: Profile,
                 prices: dict[str, Price], today: Callable[[], date] = sydney_today):
        self.conn = conn
        self.extractor = extractor
        self.filters = filters
        self.profile = profile
        self.prices = prices
        self.today = today

    def ingest(self, company: dict, payload: Any, complete: bool,
               only_source_id: str | None = None) -> tuple[IngestCounts, list[PostingOutcome]]:
        try:
            postings = standardise(company["source"], payload, company["name"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise UnreadablePayload(f"could not read the {company['source']} response: {exc!r}") from exc
        if only_source_id is not None:
            postings = [p for p in postings if p.source_id == only_source_id]
            complete = False
        counts = IngestCounts(fetched=len(postings))
        outcomes = [self._process(company, posting, counts) for posting in postings]
        if complete:
            counts.closed = repo.close_missing(self.conn, company["id"], [p.source_id for p in postings])
        repo.insert_ingest_call(self.conn, company["id"], counts)
        self.conn.commit()
        return counts, outcomes

    def _process(self, company: dict, posting: Posting, counts: IngestCounts) -> PostingOutcome:
        existing = repo.find_posting(self.conn, posting.source, posting.source_id)
        if existing and existing["text_hash"] == posting.text_hash and existing["text_deleted_at"] is None:
            repo.touch_posting(self.conn, existing["id"])
            self.conn.commit()
            counts.unchanged += 1
            return PostingOutcome(posting.source_id, existing["id"], posting.title, "unchanged", existing["status"])
        if existing:
            posting_id = existing["id"]
            repo.update_posting_content(self.conn, posting_id, posting)
            counts.changed += 1
            action = "changed"
        else:
            posting_id = repo.insert_posting(self.conn, company["id"], posting, status="review")
            counts.created += 1
            action = "created"
        skip_reason = prefilter(posting, self.filters)
        if skip_reason:
            counts.skipped += 1
            status, reasons, closing = "skipped", [skip_reason], posting.board.deadline
        else:
            status, reasons, closing = self._extract(posting_id, posting, counts)
        if existing and existing["status"] in HUMAN_STATUSES:
            status = existing["status"]  # never undo a person's decision
        repo.set_status(self.conn, posting_id, status, skip_reason, closing)
        self.conn.commit()
        return PostingOutcome(posting.source_id, posting_id, posting.title, action, status, reasons)

    def _extract(self, posting_id: int, posting: Posting, counts: IngestCounts) -> tuple[str, list[str], date | None]:
        try:
            result = self.extractor.extract(posting)
        except ExtractionError as exc:
            return self._failed(posting_id, posting, counts, exc.kind, str(exc), exc.usage)
        except Exception as exc:  # a network failure or SDK surprise must not stop the batch
            return self._failed(posting_id, posting, counts, "api_error", f"{type(exc).__name__}: {exc}", None)
        self._log_call(posting_id, result.usage, "ok", None)
        counts.extracted += 1
        checks = run_checks(posting, result.payload, today=self.today())
        decision = decide_route(result.payload, checks)
        fit = fit_score(checks, self.profile)
        repo.insert_extraction(self.conn, posting_id, posting.text_hash, self.extractor.provider,
                               result.usage.model, result.payload, checks, decision, fit)
        setattr(counts, decision.route, getattr(counts, decision.route) + 1)
        closing = verified_closing_date(result.payload, checks) or posting.board.deadline
        return decision.route, decision.reasons, closing

    def _failed(self, posting_id: int, posting: Posting, counts: IngestCounts, kind: str, message: str,
                usage: LLMUsage | None) -> tuple[str, list[str], date | None]:
        self._log_call(posting_id, usage, kind, message)
        decision = decide_route(None, [], error=f"{kind}: {message}")
        repo.insert_extraction(self.conn, posting_id, posting.text_hash, self.extractor.provider,
                               usage.model if usage else self.extractor.model, None, [], decision, None)
        counts.failed += 1
        counts.review += 1
        return decision.route, decision.reasons, posting.board.deadline

    def _log_call(self, posting_id: int, usage: LLMUsage | None, outcome: str, error: str | None) -> None:
        provider = usage.provider if usage else self.extractor.provider
        model = usage.model if usage else self.extractor.model
        cost = (cost_usd(model, usage.input_tokens, usage.output_tokens, self.prices,
                         fallback_model=self.extractor.model) if usage else None)
        repo.insert_llm_call(self.conn, posting_id, provider, model, usage, cost, outcome, error)
