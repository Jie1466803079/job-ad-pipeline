"""Decide where an ad goes. Only verified checks can mark an ad ineligible."""

from typing import Literal

from pydantic import BaseModel

from jobpipe.checks import CheckResult
from jobpipe.llm.schema import ROUTING_FIELDS, ExtractionPayload


class RouteDecision(BaseModel):
    route: Literal["review", "tracked", "ineligible"]
    reasons: list[str]


def decide_route(payload: ExtractionPayload | None, checks: list[CheckResult],
                 error: str | None = None) -> RouteDecision:
    if payload is None:
        return RouteDecision(route="review", reasons=[f"extraction_failed: {error or 'unknown error'}"])
    failed = [c for c in checks if c.field in ROUTING_FIELDS and c.status == "fail"]
    if failed:
        return RouteDecision(route="review", reasons=[f"{c.field}: {c.reason}" for c in failed])
    if payload.work_rights.value == "citizen_only":
        return RouteDecision(route="ineligible", reasons=["work rights: citizen only"])
    if payload.security_clearance.value != "not_stated":
        return RouteDecision(route="ineligible",
                             reasons=[f"security clearance: {payload.security_clearance.value}"])
    return RouteDecision(route="tracked", reasons=[])
