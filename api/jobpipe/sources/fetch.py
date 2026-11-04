"""Fetch board JSON. Used by developer and evaluation scripts only; the running service never fetches."""

from typing import Any

import httpx

from jobpipe.sources.urls import board_api_url


def fetch_json(url: str, timeout: float = 30.0) -> Any:
    response = httpx.get(url, timeout=timeout, follow_redirects=False,
                         headers={"User-Agent": "job-ad-pipeline (personal project)"})
    response.raise_for_status()
    return response.json()


def fetch_board(source: str, slug: str) -> Any:
    return fetch_json(board_api_url(source, slug))
