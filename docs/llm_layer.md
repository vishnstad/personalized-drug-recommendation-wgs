# Layer 3 — graph-grounded recommendation (`llm/`)

```
patient phenotypes ──► Cypher retrieval ──► CPIC evidence tag + plausibility filter
 {gene: phenotype}      (retrieval/)            (explainability/evidence.py)
                                                        │
        ranked drugs ◄── deterministic ranking ◄────────┘
              │
              └─► rationale: LLM (if reachable) ─► faithfulness check ─► accept, else graph template
```

Run (Neo4j up, graph loaded):

```bash
python3 llm/recommend.py CYP2C19="Poor Metabolizer" CYP2D6="Ultrarapid Metabolizer"
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
3. **Provider-agnostic.** `llm/client.py` talks to any OpenAI-compatible endpoint (`LLM_BASE_URL`, default LM Studio
   `localhost:1234/v1`; Ollama `http://localhost:11434/v1`; model via `LLM_MODEL`, default `qwen2.5-7b-instruct`).
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
   Audited against all 275 distinct (text, classification) pairs in the graph: all 17 `standard` texts are genuine
   standard dosing; errors fall on the conservative side (a standard recommendation may show as `adjust`/`review`).
5. **Multi-gene patients:** one candidate per drug, worst action across genes wins (e.g. amitriptyline: CYP2C19 + CYP2D6).
6. **Ranking order:** `standard` → `adjust` → `review` → `avoid` → `none`, then strongest CPIC level (A first), then name.
   This is "preferred first", not a prescription.

## Example (real output)

CYP2C19 Poor Metabolizer + CYP2D6 Ultrarapid Metabolizer → 26 drugs: 1 standard (tamoxifen), 7 adjust
(atomoxetine, citalopram, escitalopram, lansoprazole, omeprazole, pantoprazole, dexlansoprazole), 14 avoid
(clopidogrel, codeine, tramadol, voriconazole, paroxetine, sertraline, nortriptyline, amitriptyline and the other TCAs, vortioxetine),
4 with no CPIC recommendation (fluvoxamine, hydrocodone, metoprolol, venlafaxine).

## Tests

`pytest tests/test_llm.py` — 12 tests: classifier cases (including the two real failures above), worst-action
merging, faithfulness rejection, end-to-end CYP2C19 PM through Neo4j, unknown-phenotype rejection, and both
LLM-gate paths with a stubbed model.

## Limitations — say these in the report

- **The LLM path has not been run against a real model.** No local LLM runtime is installed here. It is exercised
  only with stubbed model outputs; the endpoint contract is standard but untested end to end. Run it with LM Studio/Ollama
  before reporting LLM-quality numbers. The faithfulness check is rule-based (PMIDs, levels, drug names), not a
  semantic judge — a fluent but subtly wrong sentence that uses only allowed tokens would pass.
- **Phenotypes are an input**, supplied by hand (or Layer 1). PharmCAT is not integrated, so there is no VCF →
  phenotype step yet; the 1000 Genomes samples have not been phenotyped.
- **Text-derived actions:** a heuristic over CPIC prose; it can mis-bucket phrasing it has not seen. It errs toward `review`.
- **Recommendation context is flattened:** CPIC rows can differ by population (e.g. paediatric) or concomitant
  condition; all retrieved rows for a drug are merged and the most restrictive action wins.
- **Genetic phenotype only:** no medication list, so no phenoconversion (e.g. paroxetine inhibiting CYP2D6).
- **Not a clinical tool.** Research prototype; recommendations must be reviewed by a clinician.
