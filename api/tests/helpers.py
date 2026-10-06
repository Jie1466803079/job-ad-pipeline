"""Builders shared by the tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

from jobpipe.models import BoardFields, Posting
from jobpipe.sources.common import make_posting

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def posting_with(text: str, board: BoardFields | None = None, title: str = "Data Engineer",
                 posted: datetime | None = datetime(2026, 9, 20, tzinfo=UTC),
                 source_id: str = "1") -> Posting:
    return make_posting(source="greenhouse", source_id=source_id, company="Example", title=title,
                        url=f"https://example.test/{source_id}", posted_at=posted, text=text,
                        board=board or BoardFields())


TEST_CONFIG = {
    "companies.yaml": (
        "companies:\n"
        "  - {name: Example GH, source: greenhouse, slug: examplegh}\n"
        "  - {name: Example LV, source: lever, slug: examplelv}\n"
        "  - {name: Example AB, source: ashby, slug: exampleab}\n"
    ),
    "filters.yaml": (
        "location_terms: [australia, au, sydney, melbourne]\n"
        "title_include: [data, engineer, analyst, graduate]\n"
        "title_exclude: [sales, account executive]\n"
    ),
    "profile.yaml": "skills:\n  - {name: Python}\n  - {name: SQL, synonyms: [PostgreSQL]}\n",
    "prices.yaml": "fake-1: {input: 1.0, output: 2.0}\n",
}


def write_test_config(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in TEST_CONFIG.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory
