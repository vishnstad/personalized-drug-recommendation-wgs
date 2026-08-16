# Personalized Drug Recommendation from Whole Genome Sequencing Data

**Knowledge Graph-Grounded Large Language Models: An Explainable AI Approach**

Final-year project. Pipeline (planned, built incrementally):

```
WGS data → VCF → variant processing → pharmacogene identification
→ pharmacogenomic phenotype calling → Knowledge Graph → graph-based retrieval
→ LLM → drug recommendation + explanation → Streamlit interface
```

## Current milestone: Genomic setup & dataset preparation

We are currently only working on obtaining a real 1000 Genomes sample, inspecting
its VCF, and extracting the CYP2C19 / CYP2D6 pharmacogene regions. See
[`docs/genomic_setup.md`](docs/genomic_setup.md) for full details once available.

Not yet built: LLM/RAG, FastAPI backend, Streamlit frontend. These come in
later milestones.

## Knowledge graph & explainability (Layer 2 / Layer 4)

`knowledge_graph/` and `explainability/` are built and loaded from live data
— no mocks. `knowledge_graph/etl/` pulls real, unauthenticated API data from
CPIC (gene-drug pairs with CPIC A–D evidence grades, phenotype-gated
recommendations, guidelines, publications), HGNC (gene → HGNC ID
normalization), and SIDER (drug → adverse-event associations), normalizes it
into the graph schema documented in `knowledge_graph/schema/schema.md`, and
loads it into Neo4j. `retrieval/queries.py` is the Cypher path-retrieval
interface the LLM/RAG layer calls. `explainability/` renders the exact
subgraph behind any one recommendation (`render_path.py`) and tags every
claim with its CPIC evidence grade before it reaches an LLM prompt
(`evidence.py`). See `docs/layer2_writeup.md` and `docs/layer4_writeup.md`
for the full writeup, and `knowledge_graph/etl/run_etl.sh` to reproduce the
graph end to end (`docker compose up -d && bash knowledge_graph/etl/run_etl.sh`).

## Project structure

```
data/
  raw/         # unmodified downloaded files (VCF/BCF from 1000 Genomes)
  processed/   # derived files (e.g. per-gene VCF subsets)
  test/        # small files used for quick local testing
genomic/       # VCF inspection / processing scripts
knowledge_graph/  # Neo4j schema, ETL (CPIC/HGNC/SIDER), Cypher queries
retrieval/        # graph-based retrieval logic (Layer 3's interface into the KG)
explainability/   # per-recommendation path rendering + CPIC evidence tagging
llm/              # (future) LLM prompting / explanation generation
backend/          # (future) FastAPI service
frontend/         # (future) Streamlit UI
scripts/          # setup / utility scripts
docs/             # written documentation
```

## Environment

- Bioinformatics tools (bcftools, cyvcf2) run inside **WSL2 Ubuntu**, since
  bcftools has no native Windows build.
- Project files live on the Windows filesystem
  (`D:\Documents\College_purpose\Sem7\DNA\personalized-drug-recommendation`),
  visible to WSL at `/mnt/d/Documents/College_purpose/Sem7/DNA/personalized-drug-recommendation`.
- Python virtual environment is created inside WSL (see `docs/genomic_setup.md`).
