#!/usr/bin/env bash
# Run the API + web UI without Docker (inside WSL2 Ubuntu / Linux, from anywhere):
#   bash scripts/run_app.sh
# Prerequisites: Neo4j up with the graph loaded (docker compose up -d neo4j; knowledge_graph/etl/run_etl.sh),
# the venv from the README, and .env with BCFTOOLS_BIN / JAVA_BIN. The containerised route is simply:
#   docker compose up -d --build
# Either way: UI http://localhost:8010   API docs http://localhost:8010/docs
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${VENV:-$HOME/venvs/pgx}/bin/uvicorn" backend.app:app --host 0.0.0.0 --port 8010
