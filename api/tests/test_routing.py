from datetime import date

from helpers import SAMPLE_AD, payload_with, posting_with
from jobpipe.checks import run_checks
from jobpipe.llm.schema import ClearanceField, SkillItem, WorkModeField, WorkRightsField, not_stated_payload
from jobpipe.routing import decide_route

TODAY = date(2026, 10, 6)


def route_for(payload):
    return decide_route(payload, run_checks(posting_with(SAMPLE_AD), payload, TODAY))


def test_failed_extraction_goes_to_review():
    decision = decide_route(None, [], error="api_error: boom")
    assert decision.route == "review"
    assert decision.reasons == ["extraction_failed: api_error: boom"]


def test_any_failed_routing_check_goes_to_review():
    decision = route_for(payload_with(work_mode=WorkModeField(value="hybrid", quote="not in the ad")))
    assert decision.route == "review"
    assert "work_mode: quote not found in the ad" in decision.reasons


def test_skill_failures_do_not_affect_routing():
    payload = payload_with(required_skills=[SkillItem(skill="Rust", quote="Rust experience required")])
    assert route_for(payload).route == "tracked"


def test_verified_citizen_only_is_ineligible():
    decision = route_for(payload_with(work_rights=WorkRightsField(value="citizen_only",
                                                                  quote="You must hold an NV1 clearance.")))
    assert decision.route == "ineligible"
    assert decision.reasons == ["work rights: citizen only"]


def test_verified_clearance_is_ineligible():
    decision = route_for(payload_with(security_clearance=ClearanceField(value="nv1",
                                                                        quote="You must hold an NV1 clearance.")))
    assert decision.route == "ineligible"
    assert decision.reasons == ["security clearance: nv1"]


def test_unverified_citizen_only_goes_to_review_not_ineligible():
    quote = "Applicants must be Australian citizens or permanent residents."
    assert route_for(payload_with(work_rights=WorkRightsField(value="citizen_only", quote=quote))).route == "review"


def test_everything_checked_is_tracked():
    assert route_for(not_stated_payload()).route == "tracked"
