# Personalized Drug Recommendation from Whole Genome Sequencing Data

**Knowledge Graph-Grounded Large Language Models: An Explainable AI Approach**

Final-year project. Pipeline (planned, built incrementally):

```
WGS data → VCF → variant processing → pharmacogene identification
→ pharmacogenomic phenotype calling → Knowledge Graph → graph-based retrieval
→ LLM → drug recommendation + explanation → Streamlit interface
```

## Implementation Status

- **Layer 1 (Genomic Processing):** Built and verified. PharmCAT 3.4.0 runs on patient VCF slices extracted from the 1000 Genomes 30x dataset, calling star-allele diplotypes and metabolizer phenotypes with structural variant and VUS handling (see [`docs/genomic_setup.md`](docs/genomic_setup.md)).
- **Layer 2 (Knowledge Graph):** Built and loaded into Neo4j from live CPIC, HGNC, and SIDER APIs; 23/23 validation checks pass (see [`docs/layer2_writeup.md`](docs/layer2_writeup.md)).
- **Layer 3 (Hybrid Retrieval & Grounded LLM):** Built and verified. Hybrid graph + ChromaDB vector retrieval, RCG4MR semantic plausibility filtering, deterministic action ranking, and strict faithfulness checking (see [`docs/llm_layer.md`](docs/llm_layer.md)).
- **Layer 4 (Explainability):** Built. Attaches CPIC evidence grades (A–D) to every claim and renders interactive PyVis subgraphs (see [`docs/layer4_writeup.md`](docs/layer4_writeup.md)).
- **Layer 5 (Interface):** Next milestone — FastAPI backend and Streamlit UI.

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

### Dataset, validation and literature docs

| Doc | Covers |
|---|---|
| [`docs/dataset_provenance.md`](docs/dataset_provenance.md) | how the 1000 Genomes data was obtained, ancestry breakdown (5 superpopulations / 26 populations), allele frequencies, limitations |
| [`docs/pharmacogenes_biology.md`](docs/pharmacogenes_biology.md) | CYP2C19 and CYP2D6 biology: location, alleles, mechanisms, drugs, phenotype methods |
| [`docs/phenotypes_and_drugs.md`](docs/phenotypes_and_drugs.md) | phenotype categories and frequencies; drugs per gene grouped by CPIC guideline and ATC class |
| [`docs/neo4j_validation.md`](docs/neo4j_validation.md) | graph validation against live CPIC (`knowledge_graph/validate_graph.py`) and findings |
| [`docs/tool_versions.md`](docs/tool_versions.md) | versions of every tool and data release used |
| [`docs/llm_layer.md`](docs/llm_layer.md) | Layer 3: graph-grounded recommender, faithfulness gate, design decisions, limitations |
| [`docs/related_work.md`](docs/related_work.md) | similar systems, and what we absorb from each paper (by category) |

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
analysis/         # ancestry/allele-frequency and phenotype/drug-grouping reports
llm/              # graph-grounded recommendation + faithfulness-checked rationale
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
