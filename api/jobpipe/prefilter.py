"""Rules applied before any LLM call. Returns the reason an ad is skipped, or None to keep it."""

from jobpipe.configfiles import FilterConfig, contains_term
from jobpipe.models import Posting


def prefilter(posting: Posting, filters: FilterConfig) -> str | None:
    if not posting.text.strip():
        return "no ad text"
    location_text = " | ".join([*posting.board.locations, posting.board.country or ""]).strip(" |")
    if location_text and not any(contains_term(location_text, term) for term in filters.location_terms):
        return "location: not in Australia"
    for term in filters.title_exclude:
        if contains_term(posting.title, term):
            return f"title: excluded keyword '{term}'"
    if not any(contains_term(posting.title, term) for term in filters.title_include):
        return "title: no include keyword"
    return None
