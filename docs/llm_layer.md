# Layer 3 — graph-grounded recommendation (`llm/`)

```
patient phenotypes ──► patient-level Cypher retrieval ──► CPIC evidence tag + structural filter
 + activity scores      (full multi-gene condition match)      (explainability/evidence.py)
                                                                       │
 ranked drugs ◄── deterministic ranking ◄── action classifier + RCG4MR rule cross-check
      │
      └─► rationale: graph template (instant)  ─ or on demand ─►  LLM ─► faithfulness gate ─► accept, else template
```

Run (Neo4j up, graph loaded):

```bash
python3 llm/recommend.py CYP2C19="Poor Metabolizer" CYP2D6="Ultrarapid Metabolizer"   # template rationales
python3 llm/recommend.py HG00096 --llm                                               # Layer 1 -> 3, LLM rationales
```

Output is JSON: per drug — rank, action, CPIC level(s), guideline(s), PMIDs, the per-gene evidence rows,
and an explanation tagged `source: "llm"` or `"template"` (plus the rejected LLM text and why, if any).
Render the subgraph behind any recommendation with `explainability/render_path.py <recommendation_id>`.

## Design decisions

1. **The LLM does not decide.** Ranking is computed from the graph. The LLM only paraphrases the retrieved
   evidence into 2–3 sentences. This is the grounding guarantee: a wrong clinical decision cannot come from the model.
2. **Faithfulness gate** (`llm/faithfulness.py`). An LLM explanation is rejected if it cites a PMID that was
   not retrieved for that drug, states a CPIC level the graph doesn't hold, or mentions a different drug. A
   rejected output is replaced by a template built only from graph facts. No model is needed for the pipeline to work.
3. **Provider-agnostic.** `llm/client.py` talks to any OpenAI-compatible endpoint (`LLM_BASE_URL`; this project runs
   Ollama at `http://localhost:11434/v1` with `LLM_MODEL=qwen2.5:3b`; LM Studio `localhost:1234/v1` also works).
   If no endpoint answers, the template path is used automatically.
4. **Action classifier is conservative** (`classify_action`). CPIC has no structured "avoid/adjust/standard"
   field — its `alternate_drug_available` / `dosing_information` flags are unpopulated even for "choose an
   alternative agent". So the action is inferred from CPIC's text, with these rules, each added after a real failure:
   - unrecognised or mixed advice → `review`, **never** `standard`;
   - "choose an alternative … in lieu of X" → `avoid`, even if the text later mentions "standard dosage"
     (voriconazole, CYP2C19 PM — the first version got this wrong);
   - "Avoid … inhibitors" is an interaction warning, not "avoid the drug" (tamoxifen, CYP2D6 UM — first version got this wrong);
   - "lower the dose *or* select an alternative" in one sentence → `review`;
   - `No Recommendation` rows → `none`, listed last, and never mask a real action from another gene.
   - "use at standard dose (75 mg/day)" names a dose but changes nothing → `standard` (clopidogrel, CYP2C19 NM — found
     by the evaluation benchmark; the fix changed exactly this one of the 275 distinct CPIC texts).
   Audited against all 275 distinct (text, classification) pairs in the graph; remaining errors fall on the conservative
   side (a standard recommendation may show as `adjust`/`review`).
5. **Patient-level retrieval** (`retrieval/queries.py::recommendations_for_patient`). CPIC recommendations are
   conditioned on a *combination* of phenotypes — 1,030 of the 1,316 CYP2D6 rows are joint CYP2C19 + CYP2D6 rules
   (tricyclics, SSRIs) — and CYP2D6 rows are further split by activity score (`lookupkey`). The first version retrieved
   per gene, so a CYP2C19 PM patient received amitriptyline advice for *every* CYP2D6 phenotype (23 rows) and "worst
   action wins" merged them. Now each Recommendation node stores its full condition, and a row is returned only if
   **every** gene in it matches the patient (an untested gene counts as CPIC's `No Result`); a known activity score
   selects the matching CYP2D6 row. On the benchmark cases this removes 20–58 non-applicable rows per patient.
6. **Populations are kept apart.** CPIC gives separate advice per population (clopidogrel: ACS-PCI / non-ACS /
   neurovascular; atomoxetine: adults / pediatrics). Each is shown as its own source; the drug's headline action is the
   most cautious one.
7. **Ranking order:** `standard` → `adjust` → `review` → `avoid` → `none`, then strongest CPIC level (A first), then name.
8. **RCG4MR plausibility rules cross-check the classifier, they do not delete evidence.** `llm/plausibility_validator.py`
   encodes prodrug-activation vs. clearance rules (e.g. codeine in a CYP2D6 PM can never be `standard`). A contradiction
   means the text classifier misread CPIC, so the drug is downgraded to `review` with the reason shown. (The first
   version passed rows without gene/action, so the rules never fired; and an LLM opinion could silently drop real
   CPIC guidance. The LLM validator remains available but is not part of the default pipeline.)
9. **LLM explanations are on demand and cached** (`explain_drug`). A 3B–7B model on a 4 GB laptop GPU takes seconds
   per explanation, so the ranked list is returned instantly with graph templates and the UI asks for an LLM rationale
   per drug. The LLM receives CPIC's own `implications` text plus, if one exists for *exactly* that drug, a curated
   guideline summary (`retrieval/hybrid_retriever.py`; previously a nearest-neighbour search could hand it a
   different drug's text). Drugs named inside the evidence (e.g. "use prasugrel or ticagrelor") may be repeated;
   any other drug name is still a faithfulness violation.
10. **Layer 1 direct ingestion:** `recommend.py HG00096` runs bcftools + PharmCAT, passes phenotypes *and* activity
    scores, and maps an unmatched PharmCAT call (e.g. `n/a`) to `No Result` with a note instead of aborting.

11. **Detailed explanations (`explain(..., detail="detailed")`, UI button "Generate detailed explanation").**
    Six sections, each tagged with its source. The LLM writes *In short*, *Why it matters for this drug* and
    *Things to consider* from the patient's CPIC evidence, CPIC's `implications` text and the curated
    prodrug/clearance mechanism. The genotype section is generated from the PharmCAT call. *What CPIC recommends*
    (one line per patient group) and *Strength of evidence* are verbatim graph text. The answer is requested as JSON
    (`response_format`), and the gate additionally checks star alleles, "two copies of *X" claims (against the
    diplotype) and doses or percentages (against the evidence). A rejected answer gets **one retry** with the
    problems fed back. If that also fails, the same sections are filled from graph facts only. The backend log
    records model, source, word count and time for every explanation.

## Tests & Evaluation

- `pytest tests/` — unit tests (classifier, faithfulness gate, plausibility) plus integration tests against the loaded
  graph, including regression tests for multi-gene matching, activity-score selection and population separation.
- `python llm/evaluate.py --models qwen2.5:3b,qwen2.5:latest --samples HG00096,...` — runs the real pipeline: expected
  CPIC actions on textbook cases, per-gene vs patient-level retrieval, LLM faithfulness pass rate and latency per
  model, and end-to-end 1000 Genomes samples. Results: `docs/benchmark_results.json`, summarised in `docs/evaluation.md`.

## Limitations — say these in the report

- **The LLM path is provider-agnostic but requires a live endpoint for LLM generation:** When an endpoint (LM Studio, Ollama, or OpenAI-compatible API) is offline, the deterministic graph-backed template is used automatically as a robust fail-safe.
- **Short-read WGS limitations:** Short-read sequencing data cannot directly resolve complex structural copy-number variants for CYP2D6 (such as whole gene deletion *5 or xN duplications) without orthogonal SV callers or long reads; this is explicitly flagged in the patient profile.
- **Variant-only VCF:** the 1000 Genomes VCF lists variant sites only, so PharmCAT reports some CPIC-defining positions
  as missing and every call is marked moderate confidence.
- **Curated summaries are hand-written:** the 10 guideline summaries in `retrieval/hybrid_retriever.py` add context to
  explanations but are not CPIC API data; the recommendation itself always comes from the graph.
- **Genetic phenotype only:** no medication list is currently provided as input, so drug-induced phenoconversion (e.g. fluoxetine inhibiting CYP2D6) is not modeled.
- **Not a clinical tool:** Research prototype; recommendations must be reviewed by a qualified healthcare professional.
