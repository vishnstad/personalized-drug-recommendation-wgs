# Pharmacogenomic Knowledge Graph — Schema (Layer 2)

Entry point for this graph is the **patient phenotype**, not raw variant calls — Layer 1
(PharmCAT/VEP, out of scope here) converts a patient's VCF into star-allele diplotypes and
CPIC metabolizer phenotypes upstream of this layer. This graph picks up from there and
answers: *given a gene's phenotype (and optionally a candidate drug/indication), what does
the evidence say, and what's the traceable path behind that answer?*

## Node labels

| Label | Key property | Other properties | Source |
|---|---|---|---|
| `Gene` | `symbol` (HGNC symbol) | `hgnc_id`, `name`, `chromosome` | CPIC `gene`, HGNC REST |
| `Diplotype` | `id` (`gene:diplotype_name`) | `gene`, `name` (e.g. `*1/*4`) | CPIC `diplotype` |
| `Phenotype` | `id` (`gene:phenotype_name`) | `gene`, `name` (e.g. `CYP2D6 Poor Metabolizer`), `activity_score`, `ehr_priority` | CPIC `diplotype`/`gene_result` |
| `Drug` | `rxnorm_id` | `name` | CPIC `drug` (already RxNorm-keyed) |
| `Guideline` | `id` | `name`, `url`, `source` | CPIC `guideline` |
| `Recommendation` | `id` | `drug_recommendation`, `classification`, `implications`, `population`, `comments` | CPIC `recommendation` |
| `Publication` | `pmid` | `title` (if available) | CPIC `publication` |
| `ADR` | `id` (meddra term, normalized lowercase) | `name`, `meddra_id` | SIDER (best-effort drug-name matched) |

Normalization: genes → **HGNC** id via `rest.genenames.org`; drugs → **RxNorm** id (native to
CPIC's `drug.drugid`); ADR terms carry SIDER's own MedDRA identifiers — a full MeSH crosswalk
is flagged as a documented extension point (see `docs/layer2_writeup.md`), not silently faked.
Diseases/indications are not modeled as a separate node type in this pass — CPIC pairs/guidelines
are drug-gene, not drug-disease; adding `Disease` nodes is a clean extension once a
disease-indication source (e.g. DrugBank indications) is integrated.

## Relationship types

```
(Gene)-[:HAS_DIPLOTYPE]->(Diplotype)
(Diplotype)-[:RESULTS_IN_PHENOTYPE]->(Phenotype)
(Gene)-[:ASSOCIATED_WITH {cpic_level, clinpgx_level, pgx_testing, used_for_recommendation}]->(Drug)
(Phenotype)-[:HAS_RECOMMENDATION]->(Recommendation)
(Recommendation)-[:RECOMMENDS]->(Drug)
(Recommendation)-[:FOLLOWS_GUIDELINE]->(Guideline)
(Guideline)-[:CITES]->(Publication)
(Drug)-[:CAUSES_ADR]->(ADR)
```

Evidence is not a separate node — it's attached as **properties on the relevant relationship**
(`cpic_level`, `clinpgx_level`, `citations`) so a single Cypher path already carries its own
evidence grade. `citations` on `ASSOCIATED_WITH` is a list of PMIDs (from CPIC `pair.citations`);
Neo4j relationships can't themselves be the source of another relationship, so those PMIDs are
stored as a property array rather than a graph edge, and are resolvable against the `Publication`
nodes by PMID. That's what Layer 4's evidence tagging reads off directly (see
`explainability/evidence.py`).

### Diplotype sampling note

CPIC's raw diplotype table has ~113K rows (e.g. CYP2D6 alone has 16,836 distinct diplotype
strings due to copy-number notation, but they collapse to only 5 phenotypes). Modeling every
row as a graph node would bloat the KG with redundant nodes that all resolve to the same
handful of phenotypes, and duplicates work that belongs to Layer 1 (PharmCAT already resolves
a patient's specific diplotype to a phenotype upstream of this graph). So the graph stores a
**representative sample** (shortest/simplest notation, up to 6 per gene+phenotype) as
`Diplotype` nodes for explainability/traceability, while the full CPIC diplotype→phenotype
table is kept as a flat lookup (`data/processed/diplotype_phenotype_lookup.csv`) for the actual
patient-diplotype resolution step at the Layer 1/2 boundary.

## Why this shape

- CPIC's `pair` table is exactly a `(Gene)-[evidence]->(Drug)` edge with a real evidence grade
  (A/B/C/D) attached — no need to invent an `Evidence` node type, the grade lives on the edge
  it grades.
- `Recommendation` sits between `Phenotype` and `Drug` because CPIC recommendations are
  genuinely phenotype-conditioned ("if CYP2D6 Poor Metabolizer, avoid codeine, use
  non-tramadol/non-codeine analgesic") — collapsing that into a flat Gene→Drug edge would lose
  the actionable part.
- `Publication` nodes make every recommendation and every evidence-graded pair traceable to a
  PMID, which is what "explanation traceable to specific genomic evidence" in the abstract
  actually requires.
