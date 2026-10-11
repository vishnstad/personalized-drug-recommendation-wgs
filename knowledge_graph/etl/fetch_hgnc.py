"""
Normalize CPIC gene symbols to HGNC IDs via the free HGNC REST API
(https://www.genenames.org/help/rest/) — no auth required.

Reads data/raw/cpic_gene.json (produced by fetch_cpic.py) and writes
data/raw/hgnc_lookup.json: {symbol: {hgnc_id, name, chromosome}}
"""
import json
import time
from pathlib import Path

import requests

HGNC_URL = "https://rest.genenames.org/fetch/symbol/{symbol}"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> None:
    genes = json.loads((RAW_DIR / "cpic_gene.json").read_text())
    symbols = sorted({g["symbol"] for g in genes if g.get("symbol")})

    lookup: dict[str, dict] = {}
    headers = {"Accept": "application/json"}
    for i, symbol in enumerate(symbols):
        try:
            resp = requests.get(HGNC_URL.format(symbol=symbol), headers=headers, timeout=15)
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
            if docs:
                doc = docs[0]
                lookup[symbol] = {
                    "hgnc_id": doc.get("hgnc_id"),
                    "name": doc.get("name"),
                    "chromosome": doc.get("location"),
                }
            else:
                lookup[symbol] = {"hgnc_id": None, "name": None, "chromosome": None}
        except requests.exceptions.RequestException as exc:
            print(f"  warn: {symbol} lookup failed ({exc})")
            lookup[symbol] = {"hgnc_id": None, "name": None, "chromosome": None}
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(symbols)} genes resolved")
        time.sleep(0.05)

    out_path = RAW_DIR / "hgnc_lookup.json"
    out_path.write_text(json.dumps(lookup, indent=2))
    resolved = sum(1 for v in lookup.values() if v["hgnc_id"])
    print(f"Resolved {resolved}/{len(symbols)} gene symbols to HGNC IDs -> {out_path}")


if __name__ == "__main__":
    main()
