#!/usr/bin/env bash
# Full ETL pipeline: fetch real data -> normalize -> load into Neo4j.
# Assumes: `docker compose up -d` already running, venv activated with requirements.txt installed.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/5 Fetching CPIC data =="
python3 etl/fetch_cpic.py

echo "== 2/5 Fetching HGNC gene normalization =="
python3 etl/fetch_hgnc.py

echo "== 3/5 Fetching SIDER ADR data =="
python3 etl/fetch_sider.py

echo "== 4/5 Normalizing into graph schema =="
python3 etl/normalize.py

echo "== 5/5 Loading into Neo4j =="
python3 etl/load_neo4j.py

echo "Done. Try: python3 retrieval/queries.py"
