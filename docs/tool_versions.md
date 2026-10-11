# Tool and data versions

Recorded 2026-10-11. "Verified" = read from the running tool this session; "from repo docs" = stated in
`docs/genomic_setup.md` (genomic layer, run inside WSL2 Ubuntu on the teammate's machine) and not re-checked.

## Knowledge graph / retrieval / explainability layers (this machine: macOS, Apple Silicon)

| Tool | Version | Role | Status |
|---|---|---|---|
| Neo4j Community Server | **5.26.31** (image `neo4j:5-community`) | graph database | verified (`dbms.components()`) |
| Cypher-shell | 5.26.31 | CLI used for constraints / ad-hoc queries | verified |
| Neo4j APOC plugin | loaded via `NEO4J_PLUGINS=["apoc"]` (matches server) | enabled in `docker-compose.yml`; the ETL does not depend on it | from compose file |
| Python | 3.13.9 | all scripts | verified |
| `neo4j` (Python driver) | 5.28.1 | Bolt driver | verified (`pip freeze`, pinned) |
| `requests` | 2.32.3 | CPIC / HGNC / SIDER downloads | verified |
| `pandas` | 2.2.3 | pinned in `requirements.txt` | verified |
| `pyvis` | 0.3.2 | interactive subgraph rendering (Layer 4) | verified |
| `networkx` / `Jinja2` | 3.6.1 / 3.1.6 | pyvis dependencies | verified |
| `python-dotenv` | 1.0.1 | `.env` loading | verified |
| `pytest` | 9.1.1 | `tests/test_retrieval.py` | verified |
| Docker Engine / Compose | 29.1.3 / v5.0.1 | runs Neo4j | verified |

## Genomic layer (from repo docs, WSL2 Ubuntu)

| Tool | Version | Role |
|---|---|---|
| bcftools | **1.24** | remote region query, VCF inspection, slicing |
| htslib / tabix | **1.24** | bgzip + `.tbi` indexing |
| micromamba (bioconda / conda-forge) | not recorded | installs the above without admin rights |
| `cyvcf2`, `pandas` | **not recorded** — add `pip freeze` output from the WSL venv | VCF reading in Python |

## Data resources and reference builds

| Resource | Version / date | Notes |
|---|---|---|
| Human reference | **GRCh38** | all coordinates in this project |
| 1000 Genomes, NYGC 30x | release **2022-04-22** (`20220422_3202_phased_SNV_INDEL_SV`), 3,202 samples | Byrska-Bishop et al., Cell 2022 |
| Sample/population table | `20130606_g1k_3202_samples_ped_population.txt` | IGSR |
| CPIC database | live REST API (`api.cpicpgx.org/v1`), pulled 2026-08-12, re-checked 2026-10-11; CPIC publishes per-row `version`, not a single release number | graph = snapshot of that pull; re-run the ETL to refresh |
| HGNC | live REST API (`rest.genenames.org`) | gene IDs / names |
| SIDER | flat files `meddra_all_se.tsv`, `drug_names.tsv` (SIDER 4.1, last released 2015) | ADR data is static and old |
| WHO ATC | codes from CPIC `drug.atcid`; subgroup names entered manually | used only for drug grouping |

## Planned but NOT yet used (do not claim in the report)

PharmCAT (Docker; star-allele and phenotype calling), VEP/ANNOVAR, Aldy/StellarPGx (CYP2D6 structural
variants), LlamaIndex/LangChain, ChromaDB, an LLM runtime (Ollama/LM Studio), FastAPI, Streamlit.
Phenotypes in this repo today come from **CPIC reference tables**, not from calling the 1000 Genomes samples.

## Reproduce this table

```bash
docker exec pgx-kg-neo4j cypher-shell -u neo4j -p pgxkgpassword "CALL dbms.components() YIELD name, versions RETURN name, versions"
pip freeze | grep -iE "^(neo4j|requests|pandas|pyvis|python-dotenv|pytest)=="
docker --version && docker compose version
```
