# Layer 2 — Knowledge Graph: Implementation Writeup

## What was built

A Neo4j pharmacogenomic knowledge graph loaded entirely from live, authoritative sources
— no synthetic or hand-written placeholder data:

| Source | What we pulled | How |
|---|---|---|
| **CPIC** (`api.cpicpgx.org`) | genes, drugs (RxNorm-keyed), gene-drug pairs with CPIC evidence level (A–D), guidelines, phenotype-conditioned drug recommendations, diplotype→phenotype mappings, publications | free, unauthenticated PostgREST API |
| **HGNC** (`rest.genenames.org`) | gene symbol → HGNC ID + official name (enrichment; CPIC's own `gene.hgncid` is the primary source) | free REST API |
| **SIDER** (`sideeffects.embl.de`) | drug → adverse-event associations, best-effort matched to CPIC drug names | free flat-file download |

Resulting graph: **6,959 nodes / 47,084 relationships** (132 genes, 324 drugs, 100
phenotypes, 365 representative diplotypes, 2,115 phenotype-conditioned recommendations,
574 evidence-graded gene-drug pairs, 2,774 ADR terms, 1,120 publications).

## Mapping to the reference papers this layer absorbs from

**[2] Lauschke et al., 2023** — their layered annotation scheme (genomic → computational
→ pharmacogenomic → diplotype/phenotype) defines exactly where this graph's entry point
sits: it starts at the **phenotype** layer, because star-allele diplotype calling and VUS
handling is Layer 1's job (PharmCAT), not this one. The graph is deliberately shaped so
Layer 1's output (`gene`, `phenotype`) is a direct, single Cypher parameter into
`retrieval/queries.py`.

**[3] "A Large-Scale Pharmacogenomic KG..." (medRxiv 2025.09.24.25336269)** — we absorbed
their source-integration recipe (curated PGx evidence is fragmented across sources; unify
it) and their ontology-alignment standards. Concretely: genes carry HGNC IDs, drugs carry
RxNorm IDs (native to CPIC's `drug.drugid`), matching their alignment targets. Their
reported link-prediction baseline (bilinear model, MRR 0.347) is a reasonable target if
Layer 3 later adds a learned link-prediction component on top of this graph; we don't
reproduce that model here since our retrieval is deterministic Cypher, not learned
embeddings — flagged as a possible extension, not attempted.

**[4] RCG4MR (Springer, 2025)** — its warning that graph-derived paths are not
automatically pharmacologically valid shaped the evidence-grading design: every
`ASSOCIATED_WITH` edge carries CPIC's own reviewed evidence level (A–D) rather than an
inferred/co-occurrence-based confidence score, and every `Recommendation` node traces to
a `Guideline` and `Publication` (PMID). See `docs/layer4_writeup.md` for the plausibility
filter this feeds into.

## Honest gaps / not integrated

- **DrugBank**: requires an academic-license account; not scriptable unattended. RxNorm
  IDs from CPIC's `drug` table already satisfy the drug-normalization requirement, and
  `drug.drugbank_id` is captured where CPIC itself provides the crosswalk (so a future
  DrugBank pull is a drop-in join, not a schema change).
- **Full PharmGKB bulk download**: PharmGKB's download page requires a browser session
  with license click-through. CPIC's guideline database is itself sourced from /
  coordinated with PharmGKB clinical annotations, so its coverage substantially overlaps
  what a raw PharmGKB pull would add for the gene-drug-recommendation triad specifically.
- **ClinVar variant-level clinical significance**: deliberately out of scope for this
  layer — that's raw-VCF-adjacent (Layer 1 territory), not phenotype-level, and the full
  ClinVar VCF is multi-GB. Flagged as a clean extension point (`Variant` node type) if
  Layer 1 needs it, not silently skipped.
- **Disease/indication nodes**: CPIC pairs are gene-drug, not drug-disease, so no
  `Disease` label is populated in this pass. Adding one is a clean extension once a
  disease-indication source (e.g. DrugBank indications) is integrated.
- **SIDER matching is name-based, not ID-based**: SIDER keys drugs by STITCH/PubChem
  compound ID, not RxNorm; without a paid/registered crosswalk we join on normalized drug
  name, which matched 226/324 CPIC drugs (38,165 drug-ADR pairs). Documented, not hidden.
