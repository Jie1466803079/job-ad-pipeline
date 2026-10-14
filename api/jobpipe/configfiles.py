"""Load the YAML files in config/."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from jobpipe.sources.urls import SLUG_RE
from jobpipe.textutil import normalise_for_match


class CompanyConfig(BaseModel):
    name: str
    source: Literal["greenhouse", "lever", "ashby"]
    slug: str = Field(pattern=SLUG_RE.pattern)  # the board API templates accept nothing else
    active: bool = True


class FilterConfig(BaseModel):
    location_terms: list[str]
    title_include: list[str]
    title_exclude: list[str]


class ProfileSkill(BaseModel):
    name: str
    synonyms: list[str] = []


class Profile(BaseModel):
    skills: list[ProfileSkill]

    def has(self, skill: str) -> bool:
        """True when skill contains one of the profile's names or synonyms as a whole word."""
        return any(contains_term(skill, term) for entry in self.skills for term in [entry.name, *entry.synonyms])


class Price(BaseModel):
    input: float
    output: float


def contains_term(text: str, term: str) -> bool:
    """Whole-word, case-insensitive match of term inside text."""
    needle = normalise_for_match(term)
    if not needle:
        return False
    pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
    return re.search(pattern, normalise_for_match(text)) is not None


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_companies(path: Path) -> list[CompanyConfig]:
    return [CompanyConfig(**company) for company in _load(path).get("companies", [])]


def load_filters(path: Path) -> FilterConfig:
    return FilterConfig(**_load(path))


def load_profile(path: Path) -> Profile:
    return Profile(**_load(path))


def load_prices(path: Path) -> dict[str, Price]:
    return {model: Price(**price) for model, price in _load(path).items()}
