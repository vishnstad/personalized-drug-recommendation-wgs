# Challenges faced and how we overcame them

A running log of the real problems hit while building and hardening the pipeline, written so each
can become a presentation slide: **problem → how we found it → impact → fix → evidence**.

---

## A. Correctness problems (the most important for the report)

### 1. Multi-gene CPIC rules were treated as single-gene rules
- **Problem:** CPIC recommendations are conditioned on a *combination* of phenotypes. 1,030 of the 1,316
  CYP2D6 recommendations are joint CYP2C19 + CYP2D6 rules (tricyclic antidepressants, SSRIs). The graph
  linked each such rule to each gene separately and retrieval ran per gene.
- **How we found it:** code review of `retrieval/queries.py`, then confirmed against the live CPIC API:
  for a CYP2C19 Poor Metabolizer the old query returned **23 amitriptyline rows covering every CYP2D6
  phenotype**, not just the patient's.
- **Impact:** a patient's explanation and evidence could contain advice meant for a genotype they do not
  have; "worst action wins" then merged these into one verdict.
- **Fix:** each `Recommendation` node now stores its full condition (`phenotypes_json`); new
  `recommendations_for_patient()` returns a row only if **every** gene in it matches the patient (an
  untested gene = CPIC's own `No Result`).
- **Evidence:** on the 5 benchmark patients, per-gene retrieval returned 38–88 rows; patient-level
  retrieval returns 17–31 — **20–58 non-applicable rows removed per patient**. Regression test:
  `test_multi_gene_rows_match_the_full_patient_condition`.

### 2. CYP2D6 advice depends on the activity score, not only the phenotype
- **Problem:** CPIC splits some CYP2D6 phenotypes by activity score (`lookupkey`), e.g. tamoxifen for an
  Intermediate Metabolizer is *Optional* at score 1.0 but *Moderate* at 0.25–0.75.
- **Fix:** PharmCAT's activity score flows from Layer 1 into retrieval and selects the matching row.
- **Evidence:** HG00096 (CYP2D6 `*1/*4`, score 1.0) now gets exactly the score-1.0 tamoxifen row.
  Test: `test_activity_score_selects_the_matching_row`.

### 3. Different patient populations were merged
- **Problem:** CPIC gives separate advice per population — clopidogrel has 3 (ACS-PCI, non-ACS, neurovascular),
  atomoxetine has adults vs. pediatrics. These were collapsed into one action.
- **Fix:** each population is kept as its own source and shown separately in the UI; the headline action is the
  most cautious one.

### 4. The pharmacological plausibility filter (RCG4MR) never actually ran
- **Problem:** the rule-based filter received rows without `gene` or `action`, so its rules could never fire.
  When an LLM was available, a 7B model's opinion could **silently delete** real CPIC recommendations, which
  contradicted the project's core principle "the LLM never decides". On the laptop GPU the 10 s timeout made it
  pass everything while logging that the rules had validated it.
- **Fix:** rules now receive the real gene + classified action; a contradiction downgrades the drug to `review`
  with a visible warning instead of deleting evidence. The LLM validator is no longer in the default path.
- **Evidence:** `test_plausibility_contradiction_downgrades_instead_of_dropping`.

### 5. The LLM was given guideline text about the wrong drug
- **Problem:** the explanation context came from a nearest-neighbour vector search with no drug filter, so a
  drug without a curated summary received another drug's text — the LLM then named that drug and the
  faithfulness gate rejected it.
- **Fix:** exact-drug lookup only; the LLM also now receives CPIC's own `implications` text from the graph.
  Drugs named inside the evidence (e.g. "use prasugrel or ticagrelor") may be repeated.

### 6. The faithfulness gate missed wrong phenotype claims
- **Problem:** the gate checked PMIDs, CPIC levels and drug names only. In the benchmark, qwen2.5:3b wrote
  *"the patient is a Poor Metabolizer of CYP2D6"* for a CYP2D6 **Ultrarapid** Metabolizer — and it passed.
- **How we found it:** by reading every generated explanation instead of trusting the 100% pass rate.
- **Fix:** the gate now extracts every "GENE … X Metabolizer" / "X Metabolizer of GENE" claim and rejects the
  text if it contradicts the patient's actual phenotype (falls back to the graph-built explanation).
- **Evidence:** tests built from the real hallucinated sentence (`test_faithfulness_rejects_wrong_phenotype_claim`).

### 7. Action classifier mislabelled "use at standard dose" as a dose change
- **Problem:** "If considering clopidogrel, use at standard dose (75 mg/day)" contains the word *dose*, which
  was checked before the "standard" phrases → `adjust` for Normal Metabolizers.
- **How we found it:** the new evaluation benchmark (expected-action check failed 1 case).
- **Fix:** standard phrasing with no dose-change verb → `standard`. Audited against all **275** distinct CPIC
  texts: exactly **1** classification changed — the intended one.

### 8. The evaluation script did not evaluate anything
- **Problem:** the old `llm/evaluate.py` never called the recommender; every case reported 0 recommendations
  evaluated, and its "64.3% plausibility pass rate" came from made-up claims.
- **Fix:** rewrote it to run the real pipeline: expected-action accuracy, per-gene vs patient-level retrieval,
  LLM faithfulness pass rate + latency per model, and end-to-end 1000 Genomes samples.
- **Lesson:** a benchmark number is only meaningful if you can trace it to the code path it claims to measure.

### 9. A benchmark expectation was wrong, not the code
- **Problem:** we expected `ondansetron → avoid` for CYP2D6 Ultrarapid Metabolizers (it is in the CPIC 5-HT3
  guideline). The system returned nothing.
- **Finding:** CPIC lists the CYP2D6–ondansetron pair (level A) but its database has **no recommendation rows**
  for ondansetron; the graph mirrors CPIC exactly (23/23 validation checks). We corrected the benchmark, not the code.

### 10. Most CYP2D6 calls were ambiguous on real genomes
- **Problem:** running 10 real samples (2 per superpopulation) gave CYP2C19 calls for 10/10 but CYP2D6 for only
  **3/10**. PharmCAT returned 4–25 equally likely diplotypes ("*1/*2 OR *1/*11 OR …") and left its own
  recommendation-lookup phenotype empty.
- **Root cause:** the 1000 Genomes VCF only lists sites where at least one of 3,202 people carries a variant. **90 of the
  157** CYP2D6 allele-defining positions were absent, the same set for every sample, and the VCF has 0 no-call genotypes. PharmCAT
  reads an absent position as "unknown", so it cannot rule alleles out.
- **Fix (two parts):**
  1. **Never guess:** ambiguous calls are parsed into their candidates and reported as CPIC `Indeterminate` with
     low confidence. The old parser had crashed on them.
  2. **Correct the input:** inside the downloaded regions, absent positions are filled as homozygous reference (0/0)
     before PharmCAT runs. That is the meaning of absence in a joint-called 30× cohort. PharmCAT's own preprocessor offers
     the same option (`--missing-to-ref`).
- **Evidence:** CYP2D6 resolved for **11/11** samples. **NA12878**, a GeT-RM reference sample, is called **\*3/\*4**,
  matching its consensus genotype. Calls that were already resolved (HG00096 \*1/\*4) did not change.
- **Caveat we state:** a variant removed by the release's QC filters would be read as reference.

### 11. The PharmCAT report parser dropped empty columns
- **Problem:** `line.strip()` removed trailing *tabs*, so rows ending in empty columns lost fields and the parser crashed.
- **Fix:** strip only the line ending. A regression test uses the exact row shapes from real PharmCAT output.

### 12. The UI redrew the wrong graph
- **Problem:** opening an evidence path switched to the graph tab, which then redrew the patient graph over it.
- **How we found it:** rendering every UI step headlessly (Edge `--screenshot`) and looking at the images, not just
  checking for errors.
- **Fix:** the graph view records which patient result it shows and only redraws for a new patient.

---

## B. Engineering / environment challenges

### 13. Project only ran on one teammate's machine
- **Problem:** bcftools/Java paths were hard-coded to `/home/arulyashwanth/...`; the PharmCAT jar is gitignored.
- **Fix:** all tool paths come from `.env` (`BCFTOOLS_BIN`, `JAVA_BIN`, `PHARMCAT_JAR`) via `genomic/toolchain.py`,
  which also removed duplicated WSL code. Layer 1 now runs on any machine with WSL/Linux (HG00096 in 12 s).

### 14. Windows text encoding broke the ETL
- **Problem:** `normalize.py` wrote JSON without an explicit encoding; on Windows (cp1252) a publication title
  containing `∗` crashed it.
- **Fix:** explicit `encoding="utf-8"` on all ETL file I/O.

### 15. Running a local LLM on a 4 GB laptop GPU
- **Problem:** qwen2.5 7B does not fit in 4 GB VRAM (only 12/29 layers on GPU) → ~6 tokens/s; generating
  explanations for every drug would take 5–10 minutes per patient. Loading two models alternately made Ollama
  evict and reload them (~2–3 min per swap).
- **Fix:** (a) switched default to **qwen2.5:3b**, which fits entirely on the GPU (2.2 GB, 100% GPU): ~0.4 s per
  short reply, ~2 s per explanation (7B: 11.7 s, see `docs/evaluation.md`); (b) explanations are generated
  **on demand per drug and cached**, so the ranked list appears instantly; (c) only one model is loaded at a time,
  since the 2–3 min reload on every switch first looked like a hang; (d) reused the existing Ollama Docker container
  instead of installing another runtime.

### 16. Slow network (~80–400 KB/s)
- **Problem:** Neo4j image, Python packages and the model competed for bandwidth; `chromadb` alone pulls ~200 MB
  of dependencies and downloads an embedding model on first use.
- **Fix:** prioritised downloads; made `chromadb` optional (after fix #5 the explanation path only needs an exact
  lookup, a plain dictionary).

### 17. Port conflict
- **Problem:** another local app already used port 8000.
- **Fix:** backend moved to port 8010 (configurable via `API_URL`).

---

### 18. Shell pitfalls between Windows and WSL
- `wsl -- bash -lc '... $VAR ...'` expanded variables on the Windows side, so `$B view` turned into vim's `view` command,
  and `pkill -f pattern` killed the very shell whose command line contained the pattern.
- **Fix:** scripts are piped to WSL on stdin (as `genomic/toolchain.py::run_bash` does). Later the backend moved into a
  Docker container with its own bcftools/Java/PharmCAT, which removed the WSL dependency.

### 19. Making it observable and portable
- **Problem:** the pipeline ran as loose scripts across Windows + WSL + Docker; failures were hard to see.
- **Fix:** one `docker compose up` brings up Neo4j and the backend (bcftools 1.16, Java 17, PharmCAT 3.4.0 inside
  the image). Every pipeline step logs one line, e.g.
  `layer1 | NA12878 bcftools+PharmCAT in 16.4s | CYP2D6 *3/*4 -> Poor Metabolizer` and
  `llm | clopidogrel | source=llm | 4.5s`. View them with `docker compose logs -f backend`.
  Container results were identical to the WSL run.

### 20. The first UI was hard to follow
- **Problem (user feedback):** picking a patient took two clicks in a cramped list, the steps were plain tabs with no
  "next", the graph was small and flat, and the genome/genotype steps were tables that did not show *how* a variant
  becomes a phenotype.
- **Fix:** one-step search and example genomes; a persistent patient strip; a stepper with Next/Back and ← → keys;
  a gene track of the carried variants; a two-allele → activity score → phenotype-scale view; a lane-based patient
  graph sized to the screen; hover tracing; and a captioned **walkthrough** of each evidence path, generated from the
  graph data. Colours follow a validated palette (node types) and the reserved status palette (actions, always with
  icon + label). Animations respect the OS "reduce motion" setting.
- **How we checked it:** every view rendered with headless Edge (`--screenshot`, `--force-prefers-reduced-motion`)
  and inspected, plus a zero-console-error check. This caught a real bug: node data from the API has a `text`
  field that the renderer overwrote with a colour, so the inspector showed `#0b0b0b` instead of the CPIC text.

### 21. Longer explanations meant more ways to be wrong
- **Request:** a longer, more detailed explanation from the model instead of a 2-3 sentence paraphrase.
- **What happened:** with all six sections written by qwen2.5:3b, the text read well but contained errors the gate
  could not see: "two copies of *3 and two copies of *4" for a *3/*4 patient, *41 called a no-function allele, a
  CYP2D6 discussion for clopidogrel (a CYP2C19-only drug), "monitor respiratory function" for a codeine *poor*
  metabolizer (that is the ultrarapid risk), and "CPIC notes ..." for a sentence CPIC never wrote.
- **How we found it:** by reading every generated sentence, not trusting the pass rate.
- **Fixes:**
  1. **Split the work.** The model writes the explanatory prose; the genotype section comes from the PharmCAT call
     and the CPIC recommendation and evidence are verbatim graph text, each tagged in the UI.
  2. **Give it only the relevant genes**, plus a pre-built "copy 1 carries ...; copy 2 carries ..." fact line.
  3. **Extend the gate** to star alleles, zygosity claims and doses/percentages.
  4. **One corrective retry:** the gate's problem list is sent back to the model once.
  5. **Tighter prompt** for *Things to consider* (only what CPIC names; its own caveat in its own voice).
- **Evidence:** on 6 real genomes, 17/18 detailed explanations pass (14 first try, 3 after the retry). The one
  failure falls back to graph-only sections. Median 3.5 s. Misattributions to CPIC: 0/17. Tests:
  `test_gate_rejects_wrong_zygosity_alleles_and_doses`, `test_detailed_explanation_retries_once_with_the_problems`.

---

## C. Known limitations we could not remove (state them honestly)

- Short-read WGS cannot resolve CYP2D6 structural variants (*5 deletion, duplications); calls assume 2 copies.
- The 1000 Genomes VCF contains variant sites only; absent allele-defining positions are filled as reference
  (challenge 10), which would miss a variant removed by the release's QC filters.
- Phenoconversion (co-medications), age, organ function and indication are not modelled.
- The faithfulness gate is rule-based: it catches wrong citations, levels, drug names and phenotype claims,
  but not every possible paraphrasing error — a human reviewer is still required.
