# Personalized Drug Recommendation from Whole Genome Sequencing Data

**Knowledge Graph-Grounded Large Language Models: An Explainable AI Approach**

Final-year project. Pipeline:

```
WGS data → VCF → variant processing → pharmacogene identification
→ pharmacogenomic phenotype calling → Knowledge Graph → graph-based retrieval
→ LLM → drug recommendation + explanation → web interface (FastAPI + Cytoscape.js; the plan named Streamlit)
```

## Implementation Status

- **Layer 1 (Genomic Processing):** Built and verified. PharmCAT 3.4.0 runs on patient VCF slices extracted from the 1000 Genomes 30x dataset, calling star-allele diplotypes and metabolizer phenotypes with structural variant and VUS handling (see [`docs/genomic_setup.md`](docs/genomic_setup.md)).
- **Layer 2 (Knowledge Graph):** Built and loaded into Neo4j from live CPIC, HGNC, and SIDER APIs; 23/23 validation checks pass (see [`docs/layer2_writeup.md`](docs/layer2_writeup.md)).
- **Layer 3 (Patient-level Retrieval & Grounded LLM):** Built and verified. Patient-level Cypher retrieval matches each CPIC recommendation's *full* condition (multi-gene rules, CYP2D6 activity score, population); deterministic action ranking cross-checked by pharmacological (RCG4MR) rules; on-demand local-LLM rationales behind a faithfulness gate that checks PMIDs, CPIC levels, drug names and phenotype claims (see [`docs/llm_layer.md`](docs/llm_layer.md)).
- **Layer 4 (Explainability):** Built. Attaches CPIC evidence grades (A–D) to every claim and renders interactive PyVis subgraphs — one branch per gene for multi-gene rules, linked to the patient's own diplotypes (see [`docs/layer4_writeup.md`](docs/layer4_writeup.md)).
- **Layer 5 (Interface):** Built. FastAPI backend (`backend/app.py`, Docker image with the full genomics toolchain) serving a web UI (`frontend/`) that walks through Genome → Genotype → Knowledge graph → Recommendations, with interactive graph views (Cytoscape.js).
- **Evaluation:** [`docs/evaluation.md`](docs/evaluation.md). **Challenges & how we solved them:** [`docs/challenges_and_solutions.md`](docs/challenges_and_solutions.md).

## Quick start

```bash
# 0. One-time: load the knowledge graph (needs Python + requirements.txt; any OS)
docker compose up -d neo4j
bash knowledge_graph/etl/run_etl.sh && python knowledge_graph/validate_graph.py   # 23 checks vs live CPIC

# 1. Run everything (Neo4j + API + web UI; bcftools/Java/PharmCAT are inside the backend image)
docker compose up -d --build
#    UI:   http://localhost:8010        API docs: http://localhost:8010/docs
#    Logs: docker compose logs -f backend

# 2. Optional LLM explanations: any OpenAI-compatible endpoint; we use Ollama
docker exec <ollama-container> ollama pull qwen2.5:3b     # backend reaches it at host.docker.internal:11434
```

Presentation deep links (bookmark each step; ← → keys move between steps, and through the walkthrough):

| Link | Shows |
|---|---|
| `/?sample=NA12878&step=genome` | the variants on the CYP2C19/CYP2D6 gene tracks (GeT-RM reference genome) |
| `/?sample=NA12878&step=genotype` | two alleles → activity score → CPIC phenotype scale |
| `/?sample=NA12878&step=graph` | every matching CPIC rule for the patient, grouped by action |
| `/?sample=NA12878&step=graph&drug=amitriptyline&walk=1` | guided walkthrough of a two-gene evidence path |
| `/?sample=HG01583&step=recs&drug=clopidogrel` | CYP2C19 *2/*2: clopidogrel per patient group, with sources |
| `/?sample=NA12878&step=recs&drug=amitriptyline&explain=1` | opens a drug and generates its detailed, evidence-checked explanation |

Without Docker for the backend (WSL2/Linux): `cp .env.example .env` (set `BCFTOOLS_BIN`, `JAVA_BIN`), create the venv
from `requirements.txt`, download PharmCAT into `tools/pharmcat/` (jar + `pharmcat_positions_3.4.0.vcf.bgz[.csi]`),
then `bash scripts/run_app.sh`. Tests: `pytest tests/`. Benchmark: `python llm/evaluate.py`.

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
backend/          # FastAPI service + Dockerfile (Layer 5)
frontend/         # web UI: index.html, app.js, style.css, vendor/cytoscape (Layer 5)
scripts/          # setup / utility scripts
docs/             # written documentation
```

## Environment

- Bioinformatics tools (bcftools, Java for PharmCAT) run inside **WSL2 Ubuntu**, since bcftools has no native
  Windows build. Their paths are read from `.env` (`genomic/toolchain.py`); Python code called from Windows
  runs them through `wsl -d Ubuntu`.
- Neo4j runs in Docker (`docker-compose.yml`); the LLM is any OpenAI-compatible endpoint — we reuse an existing
  Ollama container with `qwen2.5:3b`, which fits fully on a 4 GB laptop GPU (see `docs/evaluation.md`).
- The backend runs in Docker (or WSL via `scripts/run_app.sh`) on port 8010 and serves the UI at `/`.
