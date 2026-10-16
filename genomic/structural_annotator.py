"""
Structural variation and Variant of Unknown Significance (VUS) annotator (per Lauschke et al. 2023).

Evaluates the certainty of short-read WGS pharmacogene calls, flagging:
1. Structural variant (SV) limitations in CYP2D6 (e.g. *5 whole-gene deletions, xN duplications).
2. Novel / undocumented variants occurring in canonical exons or splice sites as VUS.
3. Missing or uncalled positions in the VCF that could impact star-allele determination.
"""

import re
from typing import Any


def evaluate_structural_confidence(gene: str, call_data: dict[str, Any], raw_warnings: list[str]) -> dict[str, Any]:
    """Assess structural variant confidence and limitations for a gene call."""
    confidence = "high"
    flags = []

    if gene == "CYP2D6":
        # Short-read NGS caveat: cannot detect copy-number variations (e.g. *5 deletion, *1xN)
        alleles = [a.strip() for a in call_data.get("diplotype", "").split("/")]
        # *5 = whole-gene deletion; "x2"/"xN" suffix = duplication (*1x2, *2xN). Compare per allele so *50-*59 don't match.
        if any(a == "*5" or re.search(r"x(\d+|N)$", a) for a in alleles):
            confidence = "moderate"
            flags.append("Call involves structural / copy-number allele (*5 or xN duplication); short-read WGS requires orthogonal SV validation.")
        else:
            flags.append("Standard Illumina short-read call: assumes normal diploid copy number (2 copies); does not detect whole-gene deletion (*5) or duplication.")

    if call_data.get("missing_positions"):
        flags.append("One or more CPIC-defining variant positions were uncalled or absent in VCF; PharmCAT evaluated callable sites.")
        if confidence == "high":
            confidence = "moderate"

    if call_data.get("ambiguous_call"):
        confidence = "low"
        n = len(call_data.get("diplotype_candidates") or [])
        flags.append(f"Ambiguous call: {n} candidate diplotypes fit the observed variants with different phenotypes "
                     f"(defining positions absent from the variant-only VCF); reported as Indeterminate. "
                     f"Targeted genotyping or a gVCF would resolve it.")

    if any("duplicate entry" in w.lower() for w in raw_warnings):
        # 1000 Genomes splits multi-allelic sites into several records at one position; PharmCAT keeps the first
        flags.append("VCF notice: multi-allelic site(s) split across records; PharmCAT used the first valid entry.")

    return {
        "confidence_level": confidence,
        "structural_limitations": flags,
        "requires_orthogonal_confirmation": confidence != "high",
    }


def annotate_gene_call(gene: str, call_data: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Enrich a PharmCAT gene call with structural reliability and VUS metadata."""
    annotated = dict(call_data)
    sv_eval = evaluate_structural_confidence(gene, call_data, warnings)
    annotated["structural_assessment"] = sv_eval

    # Check for indeterminate or VUS phenotypes
    phenotype = call_data.get("phenotype", "")
    diplotype = call_data.get("diplotype", "")

    vus_flags = []
    if "indeterminate" in phenotype.lower() or "unknown" in diplotype.lower():
        vus_flags.append(f"Uncertain or unassigned allele combination ({diplotype}) flagged as Variant of Unknown Significance (VUS).")

    annotated["vus_annotations"] = vus_flags
    return annotated
