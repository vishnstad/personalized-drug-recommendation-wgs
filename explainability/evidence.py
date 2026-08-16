"""
Evidence tagging (Layer 4) -- attaches a CPIC evidence grade to every drug-recommendation
claim pulled from the graph, and applies a structural plausibility pre-filter before a
claim is allowed into an LLM-facing explanation.

CPIC evidence levels (assigned by CPIC's own review process, carried on the
Gene-[:ASSOCIATED_WITH]->Drug edge as `cpic_level`):
  A - gene-drug interaction and clinical actions are well-established; a CPIC guideline
      exists with a clear prescribing recommendation.
  B - interaction is supported and CPIC has published guidance, but evidence is more
      limited than level A (e.g. fewer independent studies, narrower population data).
  C - literature suggests an effect but evidence is preliminary/mixed; testing may still
      be actionable in specific contexts, treat with more caution.
  D - little or conflicting evidence for a prescribing action; informational only.

Plausibility filtering here is the *structural* half of RCG4MR's warning that
graph-derived paths are not automatically valid -- it rejects claims where the path is
incomplete or uncited before they ever reach an LLM. The *semantic* half (does the
reasoning make pharmacological sense) is Layer 3's job once the local LLM is wired up;
`semantic_validator` below is the hook Layer 3 plugs into, not a reimplementation of it.
"""
from typing import Callable, Optional

LEVEL_DESCRIPTIONS = {
    "A": "High confidence: well-established gene-drug interaction with a clear CPIC prescribing recommendation.",
    "B": "Moderate confidence: supported interaction, but with more limited evidence than level A.",
    "C": "Preliminary confidence: literature suggests an effect; evidence is mixed or limited in scope.",
    "D": "Low confidence: little or conflicting evidence; recommendation is informational, not prescriptive.",
}


def tag_claim(recommendation_row: dict) -> dict:
    """Attach an evidence tag to one recommendation row (as returned by
    retrieval.queries.recommendations_for_phenotype). Non-destructive -- returns a new
    dict with an `evidence` block added."""
    level = recommendation_row.get("cpic_level")
    pmids = sorted(set(
        (recommendation_row.get("guideline_pmids") or [])
        + (recommendation_row.get("pair_pmids") or [])
    ))
    tagged = dict(recommendation_row)
    tagged["evidence"] = {
        "cpic_level": level,
        "clinpgx_level": recommendation_row.get("clinpgx_level"),
        "level_description": LEVEL_DESCRIPTIONS.get(level, "No CPIC evidence level on file for this gene-drug pair."),
        "citations": [f"PMID:{pmid}" for pmid in pmids],
        "n_citations": len(pmids),
    }
    return tagged


def structural_plausibility_check(recommendation_row: dict) -> tuple[bool, list[str]]:
    """Rule-based pre-filter: reject claims whose graph path is incomplete before they
    ever reach the LLM. Returns (passes, reasons_if_failed)."""
    reasons = []
    if not recommendation_row.get("drug"):
        reasons.append("no drug bound to this recommendation")
    if not recommendation_row.get("recommendation"):
        reasons.append("recommendation text is empty")
    if not recommendation_row.get("cpic_level"):
        reasons.append("gene-drug pair has no CPIC evidence level (ungraded association)")
    pmids = (recommendation_row.get("guideline_pmids") or []) + (recommendation_row.get("pair_pmids") or [])
    if not any(pmids):
        reasons.append("no supporting citation (PMID) found on the guideline or pair edge")
    return (len(reasons) == 0, reasons)


def tag_and_filter(
    recommendation_rows: list[dict],
    semantic_validator: Optional[Callable[[dict], tuple[bool, str]]] = None,
) -> dict:
    """Tag every recommendation row with its evidence grade, run the structural
    plausibility filter, and optionally an injected semantic validator (Layer 3's
    LLM-as-validator pass, per RCG4MR). Returns {"accepted": [...], "rejected": [...]}."""
    accepted, rejected = [], []
    for row in recommendation_rows:
        passes, reasons = structural_plausibility_check(row)
        tagged = tag_claim(row)
        if not passes:
            tagged["rejection_reasons"] = reasons
            rejected.append(tagged)
            continue
        if semantic_validator is not None:
            ok, reason = semantic_validator(tagged)
            if not ok:
                tagged["rejection_reasons"] = [f"semantic validator: {reason}"]
                rejected.append(tagged)
                continue
        accepted.append(tagged)
    return {"accepted": accepted, "rejected": rejected}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from retrieval.queries import get_driver, recommendations_for_phenotype

    driver = get_driver()
    try:
        rows = recommendations_for_phenotype(driver, "CYP2D6", "Poor Metabolizer")
        result = tag_and_filter(rows)
        print(f"accepted: {len(result['accepted'])}, rejected: {len(result['rejected'])}")
        print(json.dumps(result["accepted"][0], indent=2, default=str))
    finally:
        driver.close()
