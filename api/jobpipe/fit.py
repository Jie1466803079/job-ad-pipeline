"""Fit score: verified required skills compared with config/profile.yaml. Used for sorting only."""

from pydantic import BaseModel

from jobpipe.checks import CheckResult
from jobpipe.configfiles import Profile


class FitResult(BaseModel):
    matched: list[str]
    missing: list[str]
    total: int

    def summary(self) -> str:
        if self.total == 0:
            return "no verified required skills"
        text = f"{len(self.matched)} of {self.total} required skills"
        return f"{text}; missing: {', '.join(self.missing)}" if self.missing else text


def fit_score(checks: list[CheckResult], profile: Profile) -> FitResult:
    seen: set[str] = set()
    matched: list[str] = []
    missing: list[str] = []
    for check in checks:
        if check.field != "required_skills" or check.status != "pass" or not check.item:
            continue
        key = check.item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        (matched if profile.has(check.item) else missing).append(check.item)
    return FitResult(matched=matched, missing=missing, total=len(matched) + len(missing))
