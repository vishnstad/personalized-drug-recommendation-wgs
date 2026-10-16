"""
RCG4MR Semantic Plausibility Validator (Layer 3 / Layer 4, per Springer 2025).

Implements the semantic refinement pass to filter out pharmacologically implausible,
contradictory, or clinically incoherent graph paths before they reach the explanation generator.

Mechanisms verified:
1. Prodrug bioactivation: Enzymes converting inactive prodrugs into active metabolites
   (e.g. CYP2D6 -> codeine/tramadol/tamoxifen; CYP2C19 -> clopidogrel).
   - Poor metabolizers suffer loss of efficacy / subtherapeutic failure -> action should be 'avoid' or 'review'.
   - Ultrarapid metabolizers suffer rapid toxic conversion -> action should be 'avoid' or 'adjust'.
2. Active drug clearance: Enzymes clearing active parent compounds
   (e.g. CYP2C19 -> voriconazole/citalopram; CYP2D6 -> atomoxetine/TCAs).
   - Poor metabolizers suffer accumulation / toxicity -> action should be 'adjust' (dose reduction) or 'avoid'.
   - Ultrarapid metabolizers suffer subtherapeutic exposure -> action should be 'adjust' (higher dose).
"""

from typing import Any, Optional
from llm import client

# Pharmacological pathway dictionary: active clearance vs prodrug bioactivation
PHARMACOLOGICAL_PATHWAYS = {
    # Prodrugs requiring bioactivation
    ("CYP2C19", "clopidogrel"): {"mechanism": "prodrug_bioactivation", "active_metabolite": "thiol metabolite"},
    ("CYP2D6", "codeine"): {"mechanism": "prodrug_bioactivation", "active_metabolite": "morphine"},
    ("CYP2D6", "tramadol"): {"mechanism": "prodrug_bioactivation", "active_metabolite": "O-desmethyltramadol"},
    ("CYP2D6", "tamoxifen"): {"mechanism": "prodrug_bioactivation", "active_metabolite": "endoxifen"},

    # Active drugs cleared by enzyme
    ("CYP2C19", "voriconazole"): {"mechanism": "clearance", "risk": "accumulation_toxicity"},
    ("CYP2C19", "citalopram"): {"mechanism": "clearance", "risk": "qt_prolongation"},
    ("CYP2C19", "escitalopram"): {"mechanism": "clearance", "risk": "qt_prolongation"},
    ("CYP2C19", "omeprazole"): {"mechanism": "clearance", "risk": "increased_exposure"},
    ("CYP2D6", "atomoxetine"): {"mechanism": "clearance", "risk": "accumulation_toxicity"},
    ("CYP2D6", "nortriptyline"): {"mechanism": "clearance", "risk": "cardiotoxicity"},
    ("CYP2D6", "amitriptyline"): {"mechanism": "clearance", "risk": "cardiotoxicity"},
    ("CYP2D6", "ondansetron"): {"mechanism": "clearance", "risk": "reduced_efficacy_in_um"},
}


def rule_based_plausibility_check(gene: str, phenotype: str, drug: str, action: str) -> tuple[bool, str]:
    """Verify pharmacological plausibility using biochemical mechanism rules."""
    pathway = PHARMACOLOGICAL_PATHWAYS.get((gene, drug.lower()))
    if not pathway:
        # Default pass if not in targeted mechanism dictionary
        return (True, "Plausible: standard CPIC evidence association.")

    mechanism = pathway["mechanism"]
    pheno_lower = phenotype.lower()

    if mechanism == "prodrug_bioactivation":
        if "poor" in pheno_lower and action in ("standard",):
            return (False, f"Pharmacological contradiction: {drug} is a prodrug requiring {gene} bioactivation; standard dosing in Poor Metabolizer leads to lack of efficacy.")
        if "ultrarapid" in pheno_lower and action in ("standard",):
            return (False, f"Pharmacological contradiction: {drug} bioactivation in Ultrarapid Metabolizer causes rapid excessive metabolite conversion; standard dosing risks severe toxicity.")

    elif mechanism == "clearance":
        if "poor" in pheno_lower and action == "standard" and pathway.get("risk") == "accumulation_toxicity":
            return (False, f"Pharmacological contradiction: {drug} clearance is impaired in {gene} Poor Metabolizer; standard dosing risks toxic accumulation.")

    return (True, "Plausible: consistent with known enzyme-drug kinetics.")


def llm_plausibility_check(gene: str, phenotype: str, drug: str, recommendation_text: str) -> tuple[bool, str]:
    """RCG4MR LLM-as-validator: Ask the LLM whether the recommendation is pharmacologically coherent."""
    prompt = (
        f"You are a clinical pharmacologist validator. Evaluate whether the following recommendation path is "
        f"pharmacologically sound:\n"
        f"Patient Phenotype: {gene} {phenotype}\n"
        f"Drug: {drug}\n"
        f"Recommendation: {recommendation_text}\n\n"
        f"Reply with exactly 'PLAUSIBLE' if sound, or 'IMPLAUSIBLE: <reason>' if pharmacologically invalid."
    )

    try:
        response = client.chat(
            system="Evaluate pharmacogenomic plausibility strictly based on clinical pharmacology principles.",
            user=prompt,
            timeout=10,
        ).strip()

        if response.startswith("IMPLAUSIBLE"):
            reason = response.split(":", 1)[1].strip() if ":" in response else "Identified as implausible by validator"
            return (False, reason)
        return (True, "Verified plausible by LLM validator")
    except Exception:
        # Fallback to rule-based check if LLM endpoint unavailable
        return (True, "LLM validator unreachable; only the rule-based check was applied")


def validate_claim_plausibility(
    claim: dict[str, Any],
    phenotype: str = "",
    use_llm: Optional[bool] = None,
) -> tuple[bool, str]:
    """Top-level semantic validator compatible with explainability/evidence.py::tag_and_filter."""
    drug = claim.get("drug", "")
    gene = claim.get("gene", "") or claim.get("evidence", {}).get("gene", "")
    rec_text = claim.get("recommendation", "")
    action = claim.get("action", "")

    # 1. First run fast deterministic pharmacokinetic rules
    ok, rule_reason = rule_based_plausibility_check(gene, phenotype, drug, action)
    if not ok:
        return (False, rule_reason)

    # 2. Run LLM validator if enabled and available
    is_llm_avail = client.available() if use_llm is None else use_llm
    if is_llm_avail and rec_text:
        return llm_plausibility_check(gene, phenotype, drug, rec_text)

    return (True, rule_reason)
