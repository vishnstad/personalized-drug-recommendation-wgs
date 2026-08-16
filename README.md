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

Not yet built: Neo4j knowledge graph, LLM/RAG, FastAPI backend, Streamlit
frontend, Docker Compose. These come in later milestones.

## Project structure

```
data/
  raw/         # unmodified downloaded files (VCF/BCF from 1000 Genomes)
  processed/   # derived files (e.g. per-gene VCF subsets)
  test/        # small files used for quick local testing
genomic/       # VCF inspection / processing scripts
knowledge_graph/  # (future) Neo4j schema, loaders, Cypher queries
retrieval/        # (future) graph-based retrieval logic
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
