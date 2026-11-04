from datetime import date

from helpers import SAMPLE_AD, payload_with, posting_with, write_test_config
from jobpipe.checks import run_checks
from jobpipe.configfiles import load_profile
from jobpipe.fit import fit_score
from jobpipe.llm.schema import SkillItem, not_stated_payload

TODAY = date(2026, 10, 6)


def test_fit_counts_verified_required_skills_against_the_profile(tmp_path):
    profile = load_profile(write_test_config(tmp_path) / "profile.yaml")
    payload = payload_with(required_skills=[
        SkillItem(skill="Python", quote="Strong Python skills are essential."),
        SkillItem(skill="TypeScript", quote="Join our data team in Sydney."),
        SkillItem(skill="Rust", quote="not in the ad"),
        SkillItem(skill="python", quote="Strong Python skills are essential."),
    ])
    fit = fit_score(run_checks(posting_with(SAMPLE_AD), payload, TODAY), profile)
    assert (fit.matched, fit.missing, fit.total) == (["Python"], ["TypeScript"], 2)
    assert fit.summary() == "1 of 2 required skills; missing: TypeScript"


def test_fit_with_no_verified_skills(tmp_path):
    profile = load_profile(write_test_config(tmp_path) / "profile.yaml")
    fit = fit_score(run_checks(posting_with(SAMPLE_AD), not_stated_payload(), TODAY), profile)
    assert fit.total == 0
    assert fit.summary() == "no verified required skills"
