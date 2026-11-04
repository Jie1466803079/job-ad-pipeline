"""Job-board API addresses, and the allowlist for submitted job links.

A submitted link is never fetched as given. It is parsed, checked against the three supported boards,
and turned into an API address built from a fixed template.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

BOARD_API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}
JOB_API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}/{job_id}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
GREENHOUSE_ID_RE = re.compile(r"^\d{1,12}$")
GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}


class LinkRejected(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedLink:
    source: str
    slug: str
    job_id: str
    api_url: str


def board_api_url(source: str, slug: str) -> str:
    if source not in BOARD_API:
        raise ValueError(f"unknown source: {source}")
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid board slug: {slug!r}")
    return BOARD_API[source].format(slug=slug)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _resolved(source: str, slug: str, job_id: str, id_re: re.Pattern) -> ResolvedLink:
    if not SLUG_RE.match(slug):
        raise LinkRejected("invalid board name in the link")
    if not id_re.match(job_id):
        raise LinkRejected("invalid job id in the link")
    return ResolvedLink(source, slug, job_id, JOB_API[source].format(slug=slug, job_id=job_id))


def resolve_link(url: str) -> ResolvedLink:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise LinkRejected("the link could not be parsed") from None
    if parts.scheme != "https":
        raise LinkRejected("only https links are accepted")
    if parts.username or parts.password:
        raise LinkRejected("links with credentials are not accepted")
    try:
        port = parts.port
    except ValueError:
        raise LinkRejected("invalid port in the link") from None
    if port is not None:
        raise LinkRejected("links with a port are not accepted")
    host = (parts.hostname or "").lower()
    if _is_ip(host):
        raise LinkRejected("IP addresses are not accepted")
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in GREENHOUSE_HOSTS:
        if segments[:2] == ["embed", "job_app"]:
            query = parse_qs(parts.query)
            return _resolved("greenhouse", (query.get("for") or [""])[0], (query.get("token") or [""])[0],
                             GREENHOUSE_ID_RE)
        if len(segments) >= 3 and segments[1] == "jobs":
            return _resolved("greenhouse", segments[0], segments[2], GREENHOUSE_ID_RE)
        raise LinkRejected("not a Greenhouse job link")
    if host == "jobs.lever.co":
        if len(segments) >= 2:
            return _resolved("lever", segments[0], segments[1], UUID_RE)
        raise LinkRejected("not a Lever job link")
    if host == "jobs.ashbyhq.com":
        if len(segments) >= 2:
            return _resolved("ashby", segments[0], segments[1], UUID_RE)
        raise LinkRejected("not an Ashby job link")
    raise LinkRejected(f"host not allowed: {host or 'missing'}")
