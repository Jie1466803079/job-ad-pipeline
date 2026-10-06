import pytest

from jobpipe.sources.urls import LinkRejected, board_api_url, resolve_link

LEVER_ID = "3f2b9a52-1c1e-4c55-9d37-1b7a3a8a0001"
ASHBY_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
GH_API = "https://boards-api.greenhouse.io/v1/boards/examplegh/jobs/7001001?content=true"


@pytest.mark.parametrize("url, source, slug, job_id, api_url", [
    ("https://job-boards.greenhouse.io/examplegh/jobs/7001001?gh_jid=7001001",
     "greenhouse", "examplegh", "7001001", GH_API),
    ("https://boards.greenhouse.io/examplegh/jobs/7001001#app", "greenhouse", "examplegh", "7001001", GH_API),
    ("https://boards.greenhouse.io/embed/job_app?for=examplegh&token=7001001",
     "greenhouse", "examplegh", "7001001", GH_API),
    (f"https://jobs.lever.co/examplelv/{LEVER_ID}/apply", "lever", "examplelv", LEVER_ID,
     f"https://api.lever.co/v0/postings/examplelv/{LEVER_ID}?mode=json"),
    (f"https://jobs.ashbyhq.com/exampleab/{ASHBY_ID}/application", "ashby", "exampleab", ASHBY_ID,
     "https://api.ashbyhq.com/posting-api/job-board/exampleab?includeCompensation=true"),
])
def test_resolve_link_accepts_supported_boards(url, source, slug, job_id, api_url):
    link = resolve_link(url)
    assert (link.source, link.slug, link.job_id, link.api_url) == (source, slug, job_id, api_url)


@pytest.mark.parametrize("url", [
    "http://job-boards.greenhouse.io/examplegh/jobs/7001001",
    "https://169.254.169.254/latest/meta-data",
    "https://[::1]/examplegh/jobs/1",
    "https://localhost/examplegh/jobs/1",
    f"https://user:pass@jobs.lever.co/examplelv/{LEVER_ID}",
    f"https://jobs.lever.co:8443/examplelv/{LEVER_ID}",
    "https://boards.greenhouse.io.evil.example/examplegh/jobs/7001001",
    "https://evil.example/boards.greenhouse.io/examplegh/jobs/7001001",
    "https://job-boards.greenhouse.io/examplegh/jobs/not-a-number",
    "https://jobs.lever.co/examplelv/not-a-uuid",
    "https://jobs.ashbyhq.com/exampleab",
    f"ftp://jobs.lever.co/examplelv/{LEVER_ID}",
    "not a url",
])
def test_resolve_link_rejects_everything_else(url):
    with pytest.raises(LinkRejected):
        resolve_link(url)


def test_board_api_url():
    assert board_api_url("lever", "mable") == "https://api.lever.co/v0/postings/mable?mode=json"
    with pytest.raises(ValueError):
        board_api_url("lever", "../etc")
    with pytest.raises(ValueError):
        board_api_url("workday", "x")
