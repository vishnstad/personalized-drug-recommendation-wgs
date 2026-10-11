# Related work and what we absorb from each paper

Literature search run 2026-10-11 (web search + reading the arXiv/medRxiv pages where reachable).
Entries marked **read** were opened and checked; **snippet only** were seen only as a search-result
summary and must be opened before being cited; **from brief** are the five papers in the project
brief, whose details below are copied from the brief and not re-read this session.

## 1. Is anyone doing the same thing?

**Short answer: nobody we found does the whole chain** — patient WGS/VCF → pharmacogene phenotype →
*pharmacogenomic knowledge graph* → *graph-path-grounded* LLM → recommendation whose explanation
cites an evidence-graded path. Pieces exist separately:

| Capability | Closest existing work | What it lacks relative to us |
|---|---|---|
| LLM grounded in pharmacogenomic guidelines (RAG) | PGxRAG; Sherpa Rx; Applied Sciences 2026; JAMIA 2024 GPT-4+CPIC | retrieve **flat text chunks**, not graph paths; no patient genome in the pipeline; evidence grade not carried per claim |
| Knowledge-graph-grounded explainable drug recommendation | KEDRec-LM | **disease-level**, no genotype, no pharmacogenomic evidence grades |
| Large pharmacogenomic knowledge graph | Large-Scale PGx KG (medRxiv 2025) | link prediction / discovery, no LLM explanation layer |
| Graph-path retrieval for LLM reasoning in drug tasks | K-Paths (KDD '25) | repurposing and drug–drug interaction, not genotype-conditioned dosing |
| Evaluating LLMs on PGx questions | PGxQA (PSB 2025); JMIR 2025 | benchmarks, not systems |

Our claimed gap is therefore **(a)** structured graph-path retrieval instead of text chunks for PGx,
**(b)** a patient phenotype as the query entry point, **(c)** CPIC evidence level + citations
carried on every claim and rendered as the exact subgraph. Caveat: a literature search of this size is
not exhaustive; phrase the novelty as "to the best of our search", not "first".

## 2. Per-paper categorisation — what we absorb

Categories: **ARCH** overall architecture · **GENOMIC** variant→phenotype preprocessing ·
**KG** graph construction and normalisation · **RETR** retrieval/grounding · **EXPL** explanation
faithfulness · **EVAL** evaluation method.

| # | Paper | Status | Cat. | What it did | **What we absorb** | **What we do not take / gap** | Where in repo |
|---|---|---|---|---|---|---|---|
| 1 | Zhang et al., **KEDRec-LM**, arXiv:2502.20350 (2025) | from brief; abstract read via search | ARCH | Builds `expRxRec` from drug KGs (DRKG-based), clinical trials and PubMed; instruction-tunes a LLaMA-based LLM that distils a medical corpus to output a drug recommendation **and** a rationale | Dual output (recommendation + rationale); KG-grounded generation; instruction-tuning/distillation as the planned Layer 3 strategy | It works at disease/population level with no patient genome; we add the genotype→phenotype entry point. We have not implemented any fine-tuning | `docs/layer2_writeup.md`, `retrieval/` |
| 2 | Lauschke et al., *Translating pharmacogenomic sequencing data into drug response predictions*, Clin Pharmacol Ther 2023, PMID 37759374 | from brief | GENOMIC | Layered annotation of NGS data: genomic annotation → computational effect prediction → pharmacogenomic annotation (star-allele diplotypes) → functional validation; handling of variants of unknown significance | Layered VCF → diplotype → phenotype scheme; explicit treatment of uncertain genotypes (our `Indeterminate` / `Likely` phenotypes and the `No Result` placeholder) | Layer 1 is the genomic teammates' scope and PharmCAT is not run yet; VUS handling is only represented, not computed | `docs/genomic_setup.md`, Phenotype nodes |
| 3 | *A Large-Scale Pharmacogenomic Knowledge Graph for Drug-Gene-Variant-Disease Discovery*, medRxiv 2025.09.24.25336269 | from brief | KG | Integrates PharmGKB, ClinVar, SIDER, Reactome into a leakage-aware KG (3,744,727 nodes, 9,645,367 edges; HGNC/RxNorm/MeSH/ChEBI alignment); bilinear link-prediction baseline MRR 0.347, Hits@1/3/10 0.234/0.417/0.589, AUROC 0.823 | Source-integration recipe; ID-alignment standards (HGNC done, RxNorm via CPIC); the reported link-prediction metrics as a baseline for any retrieval experiment | Ours is far smaller (6,959 nodes / 47,459 edges) and CPIC-centred; **no MeSH/ChEBI alignment, no ClinVar/Reactome/PharmGKB-bulk/DrugBank**; no link prediction | `knowledge_graph/schema/schema.md`, `knowledge_graph/etl/` |
| 4 | **PGxRAG**, medRxiv 2025.09.24.25336524 | from brief; headline result seen in search | RETR, EVAL | Compares native vs RAG LLMs on 225 PGx multiple-choice questions over 2,617 chunks from PharmGKB, CPIC, DPWG/KNMP, FDA labels; best reported: GPT-4o + RAG ≈ 95% | Evidence-source list (CPIC, DPWG, FDA); evidence that grounding reduces PGx error; question-based evaluation design for Layer 3 | It retrieves **flat chunks** and takes no genome; we retrieve structured graph paths. It is a preprint | `retrieval/queries.py`, `tests/` |
| 5 | **RCG4MR**, *Refining Causal Graphs via LLMs for Medication Recommendation*, Springer 2025, doi:10.1007/978-981-92-1926-1_7 | from brief | EXPL | Distils causal diagnosis→medication links, then uses an LLM to remove implausible/pharmacologically invalid paths | The warning that graph paths are not automatically valid; a plausibility filter before explanation | Only the **structural** half is built (`evidence.py`: no drug / no evidence level / no citation → reject). The semantic LLM-as-validator is Layer 3 | `explainability/evidence.py` |
| 6 | Rector et al., **Sherpa Rx** — *Validating Pharmacogenomics Generative AI Query Prompts Using RAG*, arXiv:2507.21453 (2025) | **read** | RETR, EVAL | RAG over 26 CPIC guidelines, then PharmGKB added; 260 queries scored on a 5-point Likert scale (accuracy 4.9 in phase 1); 90% on a 20-question quiz; beat GPT-4o-mini on accuracy (3.9) and completeness (4.2) | Per-query accuracy / relevance / clarity / completeness rubric as a template for our faithfulness evaluation; CPIC-first sourcing | Text RAG, no stated genotype input, self-scored Likert (weak evidence) | planned Layer 3/4 eval |
| 7 | Abdullahi et al., **K-Paths**, arXiv:2502.13344, KDD '25 | **read** | RETR | Training-free retrieval of K short, loopless, **diverse** multi-hop paths (diversity-aware Yen's algorithm) between query entities in a biomedical KG, fed to LLMs; +19.8 F1 for Tx-Gemma 27B on interaction severity | Path selection: cap and diversify the paths returned per phenotype instead of dumping every neighbour (our subgraph queries currently return all recommendations for a phenotype) | Task is repurposing / DDI, not genotype-conditioned prescribing | future change to `retrieval/queries.py` |
| 8 | Evidence-Grounded Clinical Pharmacogenomics Decision Support: fine-tuned LLMs + hybrid RAG, *Applied Sciences* 2026, doi:10.3390/app16189148 | **snippet only** (publisher page returned 403) | RETR, ARCH | Fine-tuned LLMs with hybrid retrieval over PharmGKB, CPIC and PharmCAT content | Confirms the fine-tune + hybrid-retrieval direction and PharmCAT as the phenotype source | Not verified whether it uses a graph or takes VCF input — **open it before citing** | — |
| 9 | *Empowering personalized pharmacogenomics with generative AI solutions*, JAMIA 2024 (medRxiv 2024.02.21.24302946) | **snippet only** | RETR, EVAL | GPT-4 assistant over a CPIC knowledge base, better than ChatGPT-3.5 on provider queries needing citations | Citations in answers as a requirement; provider-vs-patient query framing | Text KB | — |
| 10 | Keat et al., **PGxQA** benchmark, PSB 2025 | **snippet only** | EVAL | Benchmark of chatbots on PGx questions for clinicians/patients/researchers; newer models better but not clinical-grade | A ready-made question set to test Layer 3; supports the "human-checkable explanation" argument | — | — |
| 11 | JMIR 2025;27:e73486 (GPT-4o / Gemini on 385 drug-gene recommendations) | **snippet only** | EVAL | LLMs classify guideline recommendations: GPT-4o 93.5% accuracy (κ=0.90), Gemini 92.7% | A scoring baseline for classifying recommendation text | No retrieval | — |
| 12 | **G-Refer**, arXiv:2502.12586, WWW '25 | **snippet only** | EXPL | Retrieves graph paths and **verbalises** them as text for an LLM that writes the explanation | Verbalising retrieved paths into natural language before prompting — the intended bridge between our Cypher output and the LLM | Product-recommendation domain | planned Layer 3 prompt step |

## 3. Summary by category

- **ARCH** — KEDRec-LM (dual output, KG grounding); Applied Sciences 2026 (fine-tune + hybrid retrieval).
- **GENOMIC** — Lauschke 2023 (layered annotation, uncertain genotypes).
- **KG** — Large-scale PGx KG (sources, ID alignment, baseline metrics).
- **RETR** — PGxRAG, Sherpa Rx, JAMIA 2024 (grounding helps); K-Paths (path selection); G-Refer (path verbalisation).
- **EXPL** — RCG4MR (plausibility filter); G-Refer (explanation from paths).
- **EVAL** — PGxRAG (MCQ design), Sherpa Rx (Likert rubric), PGxQA / JMIR 2025 (benchmarks, baselines).

## 4. Links

- KEDRec-LM <https://arxiv.org/abs/2502.20350> · Sherpa Rx <https://arxiv.org/abs/2507.21453> · K-Paths <https://arxiv.org/abs/2502.13344> · G-Refer <https://arxiv.org/abs/2502.12586>
- PGxRAG <https://www.medrxiv.org/content/10.1101/2025.09.24.25336524> · Large-scale PGx KG <https://www.medrxiv.org/content/10.1101/2025.09.24.25336269v1.full>
- Lauschke 2023 <https://pubmed.ncbi.nlm.nih.gov/37759374/> · RCG4MR <https://link.springer.com/chapter/10.1007/978-981-92-1926-1_7>
- Applied Sciences 2026 <https://doi.org/10.3390/app16189148> · PGxQA <https://psb.stanford.edu/psb-online/proceedings/psb25/keat.pdf> · JMIR 2025 <https://www.jmir.org/2025/1/e73486/PDF>
