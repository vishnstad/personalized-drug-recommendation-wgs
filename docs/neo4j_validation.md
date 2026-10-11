# Neo4j data validation

`knowledge_graph/validate_graph.py` checks the **loaded graph** against the **live CPIC API** (an
independent source — not our cached or normalised files) and for structural integrity. Run
`python3 knowledge_graph/validate_graph.py` with Neo4j up; it exits non-zero on any failure and
writes `docs/neo4j_validation_report.json`. Result on 2026-10-11 (Neo4j 5.26.31): **23/23 checks pass**.

## What is checked

| Group | Check | Result |
|---|---|---|
| Counts vs CPIC | Gene 132, Drug 324, Guideline 29, Recommendation 2,115 equal the CPIC row counts | pass |
| | `ASSOCIATED_WITH` edges (574) = CPIC pairs with `removed=false` (CPIC has 635 rows in total; 61 are retired/removed and deliberately excluded) | pass |
| Cardinality | every Recommendation has exactly one drug (`RECOMMENDS`) and at least one guideline; every Diplotype has exactly one Phenotype and one Gene | pass |
| Referential | every `Phenotype.gene` is an existing Gene; every ADR node is reachable from a Drug; no duplicate (gene, drug) edges | pass |
| Formats | `Gene.hgnc_id` = `HGNC:<digits>` (all 132); `Publication.pmid` numeric; `cpic_level` ∈ {A, A/B, B, B/C, C, C/D, D, Retired} | pass |
| Spot-checks | 25 random Recommendations re-fetched from CPIC: text, classification and drug identical; 25 random gene–drug pairs: evidence level identical | pass (0 mismatches) |
| Project genes | CYP2C19: 9 Phenotype nodes, 27 drugs; CYP2D6: 6 Phenotype nodes, 79 drugs | pass |

## Findings the check surfaced (state these honestly)

1. **`Drug.rxnorm_id` is not always RxNorm.** The first version of this check assumed it was, and
   failed on 20 of 324 nodes. CPIC itself keys those 20 by other namespaces: ATC *drug-class* entries
   (e.g. "antidepressants", "aminoglycoside antibacterials"), DrugBank, MeSH, MedDRA, and one
   placeholder `RxNorm:NA` (ribostamycin). The loader is correct; the *property name* is misleading — it
   holds CPIC's namespaced `drugid`. The check now asserts `<namespace>:<id>` and reports the split.
   Consequence for the report: do not claim "all drugs are RxNorm-normalised"; ~94% are.
2. **Some "Drug" nodes are classes, not molecules.** Class-level CPIC entries (e.g. ATC:N06A) behave as
   drugs in the graph. A recommendation for a class applies to every member drug.
3. **ADR data is not independently validated.** The 2,774 ADR nodes / 38,165 `CAUSES_ADR` edges come from
   SIDER matched to CPIC drugs by normalised *name*. The check proves they are well-formed and
   attached, not that every name match is the same compound; SIDER (2015) is also old.
4. **Phenotype nodes include a `No Result` placeholder** that CPIC recommendations reference
   (CYP2C19 9 = 8 CPIC categories + it; CYP2D6 6 = 5 + it).
5. **Diplotypes are sampled** (≤6 per gene+phenotype, 365 total) by design; the full 112,820-row CPIC
   table is not in the graph.
6. **Not validated:** MeSH/ChEBI normalisation (not implemented — only HGNC and CPIC's own drug keys).

## Reproducing by hand

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY 2 DESC;
MATCH ()-[e]->() RETURN type(e), count(*) ORDER BY 2 DESC;
MATCH (d:Drug) RETURN split(d.rxnorm_id,':')[0] AS namespace, count(*);
```
