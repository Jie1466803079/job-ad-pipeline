from pathlib import Path

import pytest
from pydantic import ValidationError

from helpers import posting_with, write_test_config
from jobpipe.configfiles import (
    CompanyConfig,
    contains_term,
    load_companies,
    load_filters,
    load_prices,
    load_profile,
)
from jobpipe.models import BoardFields
from jobpipe.prefilter import prefilter

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def filters(tmp_path):
    return load_filters(write_test_config(tmp_path) / "filters.yaml")


def test_keeps_a_relevant_australian_role(filters):
    posting = posting_with("Some ad text", board=BoardFields(locations=["Sydney"]))
    assert prefilter(posting, filters) is None


@pytest.mark.parametrize("title, locations, text, reason", [
    ("Data Engineer", ["London, UK"], "Some ad text", "location: not in Australia"),
    ("Senior Sales Manager", ["Sydney"], "Some ad text", "title: excluded keyword 'sales'"),
    ("Office Manager", ["Sydney"], "Some ad text", "title: no include keyword"),
    ("Data Engineer", ["Sydney"], "   ", "no ad text"),
])
def test_skips_with_reason(filters, title, locations, text, reason):
    posting = posting_with(text, board=BoardFields(locations=locations), title=title)
    assert prefilter(posting, filters) == reason


def test_missing_board_location_does_not_skip(filters):
    assert prefilter(posting_with("Some ad text"), filters) is None


def test_country_code_counts_as_a_location(filters):
    posting = posting_with("Some ad text", board=BoardFields(locations=["Remote"], country="AU"))
    assert prefilter(posting, filters) is None


def test_whole_word_matching():
    assert contains_term("AI Engineer", "ai")
    assert not contains_term("Maintenance Planner", "ai")
    assert contains_term("Strong scikit-learn skills", "scikit-learn")


def test_loaders_read_the_test_config(tmp_path):
    config = write_test_config(tmp_path)
    assert [c.name for c in load_companies(config / "companies.yaml")] == ["Example GH", "Example LV", "Example AB"]
    profile = load_profile(config / "profile.yaml")
    assert profile.has("Strong Python skills") and profile.has("PostgreSQL") and not profile.has("TypeScript")
    assert load_prices(config / "prices.yaml")["fake-1"].output == 2.0


def test_repo_config_files_load():
    assert load_companies(REPO_CONFIG / "companies.yaml")
    assert load_filters(REPO_CONFIG / "filters.yaml").title_include
    assert load_profile(REPO_CONFIG / "profile.yaml").has("PySpark")
    assert "gemini-3.8-flash" in load_prices(REPO_CONFIG / "prices.yaml")


def test_a_company_slug_must_fit_the_board_address_templates():
    assert CompanyConfig(name="Octopus", source="greenhouse", slug="octopus.deploy-2").slug == "octopus.deploy-2"
    for slug in ["", "bad slug", "a/../b", "-dash-first"]:
        with pytest.raises(ValidationError):
            CompanyConfig(name="Bad", source="lever", slug=slug)
