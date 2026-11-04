"""Fetch boards and post them to intake-api, the same way the n8n daily-ingest workflow will.

Usage, from the repo root with the stack running:
    make ingest-once                    every active company
    make ingest-once COMPANY="Mable"    one company
"""

import os
import sys

import httpx

from jobpipe.sources.fetch import fetch_board

API_URL = os.environ.get("INTAKE_API_URL", "http://127.0.0.1:8000")


def main(names: list[str]) -> None:
    headers = {"X-API-Key": os.environ["MACHINE_API_KEY"]}
    companies = httpx.get(f"{API_URL}/machine/companies", headers=headers, timeout=30).json()
    wanted = {name for name in names if name}
    for company in companies:
        if wanted and company["name"] not in wanted:
            continue
        payload = fetch_board(company["source"], company["slug"])
        response = httpx.post(f"{API_URL}/machine/ingest", headers=headers, timeout=900, json={
            "company_id": company["id"], "source": company["source"], "payload": payload, "complete": True})
        response.raise_for_status()
        print(f"{company['name']}: {response.json()['counts']}")


if __name__ == "__main__":
    main(sys.argv[1:])
