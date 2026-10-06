"""Convert a job board's API response into Posting records."""

from typing import Any

from jobpipe.models import Posting
from jobpipe.sources import ashby, greenhouse, lever

_PARSERS = {"greenhouse": greenhouse.parse, "lever": lever.parse, "ashby": ashby.parse}


def standardise(source: str, payload: Any, company: str) -> list[Posting]:
    try:
        parser = _PARSERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source}") from None
    return parser(payload, company)
