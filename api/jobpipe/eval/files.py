"""Where the evaluation keeps its files, and the formats of the snapshots and the split."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from jobpipe.models import Posting

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"


class Snapshot(BaseModel):
    """One ad as it was fetched for the evaluation. Snapshots stay out of git: employers own the ad text."""

    id: str
    group: Literal["eligibility", "general"]
    fetched_on: date
    posting: Posting
    altered_from: str | None = None  # on a copy with an injected line: the original ad's id


class Split(BaseModel):
    seed: int
    dev: list[str]
    test: list[str]
    injected: dict[str, str]  # copy id -> original id; every original is a test ad


def snapshot_path(eval_dir: Path, ad_id: str) -> Path:
    return eval_dir / "snapshots" / f"{ad_id}.json"


def load_snapshot(eval_dir: Path, ad_id: str) -> Snapshot:
    return Snapshot.model_validate_json(snapshot_path(eval_dir, ad_id).read_text(encoding="utf-8"))


def load_split(eval_dir: Path) -> Split:
    return Split.model_validate_json((eval_dir / "split.json").read_text(encoding="utf-8"))
