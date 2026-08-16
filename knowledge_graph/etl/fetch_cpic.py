"""
Pull real curated pharmacogenomic data from the public CPIC API
(https://api.cpicpgx.org), which is a free, unauthenticated PostgREST endpoint over
CPIC's guideline database. No mock/synthetic data — everything cached here is a live
API response.

Tables pulled:
  gene, drug, pair, guideline, recommendation, diplotype, publication

Output: one JSON file per table under data/raw/cpic_<table>.json
"""
import json
import time
from pathlib import Path

import requests

API_ROOT = "https://api.cpicpgx.org/v1"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

PAGE_SIZE = 1000


def _get_with_retry(url: str, params: dict, headers: dict, attempts: int = 5) -> requests.Response:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            time.sleep(1.5 * (i + 1))
    raise last_exc  # type: ignore[misc]


def fetch_table(table: str, select: str | None = None) -> list[dict]:
    """Fetch all rows from a CPIC PostgREST table, paging with Range headers."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {}
        if select:
            params["select"] = select
        headers = {"Range-Unit": "items", "Range": f"{offset}-{offset + PAGE_SIZE - 1}"}
        resp = _get_with_retry(f"{API_ROOT}/{table}", params, headers)
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.2)
    return rows


def main() -> None:
    tables = ["gene", "drug", "pair", "guideline", "recommendation", "diplotype", "publication"]
    for table in tables:
        print(f"Fetching CPIC table: {table} ...")
        rows = fetch_table(table)
        out_path = RAW_DIR / f"cpic_{table}.json"
        out_path.write_text(json.dumps(rows, indent=2))
        print(f"  -> {len(rows)} rows written to {out_path}")


if __name__ == "__main__":
    main()
