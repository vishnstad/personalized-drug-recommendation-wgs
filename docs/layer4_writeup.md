# Layer 4 (partial) — Explainability: Implementation Writeup

Scope taken: **path rendering** and **evidence tagging**, the two graph-adjacent pieces
of Layer 4 (plausibility filtering beyond the structural pre-filter, and
LLM-as-judge faithfulness eval, depend on Layer 3's LLM being wired up and are out of
this piece's scope by design, per the team split).

## Evidence tagging (`explainability/evidence.py`)

Every recommendation pulled from the graph gets an `evidence` block: CPIC level (A–D),
ClinPGx level, a plain-language description of what that grade means, and the resolved
PMID citations pulled from both the guideline and the underlying gene-drug pair edge.
This is a direct implementation of the brief's Layer 4 spec item *"attach CPIC evidence
level (A/B/C/D) to every output claim."*

A **structural plausibility filter** runs before tagging: it rejects any recommendation
whose graph path is incomplete — no drug bound, no CPIC level on the gene-drug edge, or
zero supporting PMIDs. On the loaded graph this rejected 0/38 recommendations for the
CYP2D6 Poor Metabolizer test case (i.e. CPIC's own curated data is structurally complete
by construction — expected, since it's a reviewed guideline database, not a scraped or
inferred graph).

## Path rendering (`explainability/render_path.py`)

Given a `recommendation_id`, `subgraph_for_recommendation()` (in
`retrieval/queries.py`) pulls the full traceable path — gene → diplotype(s) → phenotype
→ recommendation → drug → guideline → publication(s), plus any known ADRs for the drug —
and PyVis renders it as a standalone, colour-coded, interactive HTML page. This is the
literal "show the exact subgraph behind each recommendation" requirement: a clinician (or
grader) can open the HTML and see precisely which evidence produced a given
recommendation, not just take the LLM's word for it.

Verified end-to-end on `CYP2D6 Poor Metabolizer → codeine` (see
`data/processed/demo_cyp2d6_codeine.html`): the rendered graph correctly shows five
sampled `*_/*_` diplotypes converging on the `Poor Metabolizer` phenotype node, which
feeds a `HAS_RECOMMENDATION` edge into the "avoid codeine" recommendation, which in turn
traces to the CPIC "CYP2D6, OPRM1, COMT, and Opioids" guideline and its cited PMID.

## What full Layer 4 (semantic plausibility + faithfulness eval) still needs

`explainability/evidence.py::tag_and_filter()` accepts an optional
`semantic_validator` callable — that's the hook point for Layer 3's LLM-as-validator pass
(RCG4MR-style semantic refinement) and for the eventual LLM-as-judge faithfulness rubric.
Neither is implemented here since both require the local LLM (Qwen2.5/Llama 3.1 via
Ollama or LM Studio) that Layer 3 owns; wiring a validator in is a single function
argument, not a redesign.
