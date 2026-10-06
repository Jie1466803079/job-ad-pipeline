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
