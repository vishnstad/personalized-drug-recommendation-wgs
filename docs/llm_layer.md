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
7. **Hybrid Retrieval (PGxRAG):** `retrieval/hybrid_retriever.py` queries structured Cypher paths and searches a persistent ChromaDB vector store of CPIC guideline excerpts, providing clinical dosing context to the LLM.
8. **RCG4MR Semantic Plausibility Pass:** `llm/plausibility_validator.py` applies pharmacokinetic causal rules (prodrug bioactivation vs active drug clearance kinetics) and optional LLM validator passes to prune contradictory candidate paths.
9. **Layer 1 Direct Ingestion:** `recommend.py` accepts sample IDs directly (e.g. `python llm/recommend.py HG00096`), ingesting demographics and PharmCAT-derived phenotypes automatically.

## Tests & Evaluation

- `pytest tests/test_layer3.py`: Validates hybrid vector retrieval in ChromaDB, RCG4MR prodrug/clearance filters, and Layer 1 -> Layer 3 integration flow.
- `python llm/evaluate.py`: Benchmark suite evaluating grounding faithfulness, hallucination rates, and RCG4MR plausibility across PGx clinical test cases, saving reports to `docs/benchmark_results.json`.

## Limitations — say these in the report

- **The LLM path is provider-agnostic but requires a live endpoint for LLM generation:** When an endpoint (LM Studio, Ollama, or OpenAI-compatible API) is offline, the deterministic graph-backed template is used automatically as a robust fail-safe.
- **Short-read WGS limitations:** Short-read sequencing data cannot directly resolve complex structural copy-number variants for CYP2D6 (such as whole gene deletion *5 or xN duplications) without orthogonal SV callers or long reads; this is explicitly flagged in the patient profile.
- **Genetic phenotype only:** no medication list is currently provided as input, so drug-induced phenoconversion (e.g. fluoxetine inhibiting CYP2D6) is not modeled.
- **Not a clinical tool:** Research prototype; recommendations must be reviewed by a qualified healthcare professional.
