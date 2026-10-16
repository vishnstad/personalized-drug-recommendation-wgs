# Evaluation

All numbers come from `python llm/evaluate.py` against the real pipeline (Neo4j graph loaded from live CPIC,
PharmCAT 3.4.0 on 1000 Genomes 30× GRCh38). Raw output: [`benchmark_results.json`](benchmark_results.json).
Run on a laptop: RTX 3050 (4 GB VRAM), Ollama in Docker.

## 1. Action accuracy on textbook CPIC cases — 11/11

| Patient | Drug | Expected (CPIC) | Got |
|---|---|---|---|
| CYP2C19 Poor Metabolizer | clopidogrel, voriconazole | avoid | avoid |
| CYP2D6 Poor Metabolizer | codeine, tramadol | avoid | avoid |
| CYP2D6 Ultrarapid Metabolizer | codeine, tramadol | avoid | avoid |
| CYP2C19 PM + CYP2D6 UM | clopidogrel, codeine, amitriptyline | avoid | avoid |
| CYP2C19 NM + CYP2D6 NM | codeine, clopidogrel | standard | standard |

The first run scored 10/12. One miss was a classifier bug (clopidogrel "use at standard dose" → `adjust`), now fixed.
The other was a wrong expectation: CPIC has no recommendation rows for ondansetron, so we removed it from the expected set.

## 2. Patient-level vs per-gene retrieval

| Patient | Per-gene rows (old) | Patient-level rows (new) | Rows removed |
|---|---|---|---|
| CYP2C19 PM | 42 | 17 | 25 |
| CYP2D6 PM | 38 | 18 | 20 |
| CYP2D6 UM | 39 | 19 | 20 |
| CYP2C19 PM + CYP2D6 UM | 81 | 31 | 50 |
| CYP2C19 NM + CYP2D6 NM | 88 | 30 | 58 |

The removed rows are CPIC recommendations for a genotype the patient does not have: other partner-gene
phenotypes in multi-gene rules, other CYP2D6 activity scores, or the same row reached through two genes.

## 3. LLM explanations: faithfulness and latency (15 explanations per model, 3 actionable drugs × 5 cases)

| Model | Fits in 4 GB VRAM | Passed faithfulness gate | Median latency | Max |
|---|---|---|---|---|
| **qwen2.5:3b** (default) | yes (100 % GPU) | 14/15 | **1.9 s** | 2.4 s |
| qwen2.5:7b | no (12/29 layers on GPU) | 15/15 | 11.7 s | 17.4 s |

- The one 3B rejection was a real error: it called a CYP2D6 *Ultrarapid* patient a "Poor Metabolizer". The gate
  caught it after we added phenotype-claim checking. The graph-built explanation was shown instead.
- Before that gate existed, the same 3B output passed (15/15). The gate checks citations, CPIC levels, drug names
  and phenotype claims, but not every dosing nuance. For example, both models sometimes describe the standard
  atomoxetine starting dose as "lower". This is why the LLM text is optional and labelled as a paraphrase.
- **Choice: qwen2.5:3b.** It is 6× faster and fits fully on the GPU. Its errors are caught by the gate and replaced by
  graph text, so it cannot change a recommendation.

## 3b. Detailed explanations on real genomes (the UI's "Generate detailed explanation")

18 explanations: the 3 most cautious drugs for each of 6 genomes (NA12878, HG00096, HG01583, HG01879, NA20832,
HG00403), with each patient's real alleles in the evidence. qwen2.5:3b, RTX 3050 (4 GB).

| | Result |
|---|---|
| Passed the evidence check | **17/18** (14 first try, 3 after one corrective retry) |
| Fell back to graph-only sections | 1/18 (HG00403 trimipramine: called a CYP2C19 Intermediate Metabolizer "Normal" twice) |
| Median time | 3.5 s |
| Median model-written words | 121, plus the genotype, CPIC-text and evidence sections (~250 words in total) |

- **What gets generated.** The model writes three sections: *In short*, *Why it matters for this drug* and
  *Things to consider*. The genotype section is built from the PharmCAT call. *What CPIC recommends* and
  *Strength of evidence* are copied verbatim from the graph. The first version let the model write all six. On
  three test cases it misstated zygosity ("two copies of *3 and two copies of *4" for a *3/*4 patient), called *41
  a no-function allele, and added an ultrarapid-metabolizer risk to a poor-metabolizer patient.
- **Every rejection was the same error type.** In all 4 cases the checker caught, the model misnamed the CYP2C19
  phenotype in a two-gene (CYP2C19 + CYP2D6) tricyclic rule. The small model gets confused when two genes are
  involved; the deterministic phenotype check catches every instance.
- **Checked automatically:** PMIDs, CPIC levels, drug names, phenotype claims, star alleles, "two copies of *X"
  claims, doses and percentages. **Not checked:** the reasoning in each sentence. The UI says so under every
  explanation.

## 4. Real genomes: 11 samples from all 5 superpopulations (Layer 1 → Layer 3)

| Sample | Pop. | CYP2D6 | CYP2C19 | Avoid | Review | Adjust | Standard |
|---|---|---|---|---|---|---|---|
| NA12878 | EUR | *3/*4 PM | *1/*2 IM | 11 | 4 | 9 | 2 |
| HG00096 | EUR | *1/*4 IM | *1/*2 IM | 1 | 1 | 18 | 5 |
| NA20832 | EUR | *1/*2 NM | *1/*17 RM | 6 | 2 | 12 | 6 |
| HG01879 | AFR | *1/*1 NM | *17/*17 UM | 8 | 1 | 12 | 5 |
| NA20412 | AFR | *1/*2 NM | *1/*1 NM | 0 | 0 | 19 | 7 |
| HG00551 | AMR | *1/*1 NM | *1/*1 NM | 0 | 0 | 19 | 7 |
| NA19796 | AMR | *1/*2 NM | *1/*38 NM | 0 | 0 | 19 | 7 |
| HG00403 | EAS | *1/*10 NM | *1/*3 IM | 1 | 0 | 19 | 6 |
| NA19091 | EAS | *1/*2 NM | *1/*1 NM | 0 | 0 | 19 | 7 |
| HG01583 | SAS | *4/*41 IM | *2/*2 PM | 7 | 2 | 12 | 4 |
| NA21144 | SAS | *1/*2 NM | *1/*17 RM | 6 | 2 | 12 | 6 |

- **Resolved calls: CYP2C19 11/11, CYP2D6 11/11.** Without the missing-position fill, CYP2D6 resolved for only
  3/10. PharmCAT returned 4–25 candidate diplotypes, because 90 of the 157 CYP2D6 allele-defining positions are absent from
  the variant-only cohort VCF.
- **Truth check:** NA12878 is a GeT-RM reference sample with consensus CYP2D6 genotype *3/*4. We call *3/*4
  (rs35742686 + rs3892097).
- Typical runtime: ~10–16 s per new sample (bcftools + PharmCAT), and under 1 s once cached.
- Ancestry patterns are plausible: *17 (increased function) appears in AFR/EUR/SAS samples; *10 in EAS; *2/*2
  (CYP2C19 PM) in SAS. This is not a frequency study; see `docs/dataset_provenance.md` for cohort-level frequencies.

## 5. Tests

`pytest tests/`: **52 passed**. These include unit tests (classifier, faithfulness gate, plausibility rules, PharmCAT report
parsing) and integration tests against the loaded graph: multi-gene matching, activity-score selection, population
separation, end-to-end HG00096 genotyping. `knowledge_graph/validate_graph.py`: **23/23** checks against the live CPIC API.
