"""
Layer 3: Knowledge-Graph-Grounded Drug Recommendation Engine.

Input:
- Either a 1000 Genomes sample ID (e.g. "HG00096") or resolved patient phenotypes
  (e.g. {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Ultrarapid Metabolizer"}).

Pipeline:
1. Patient Profile ingestion (Layer 1 output)
2. Hybrid Retrieval: Cypher graph path retrieval + ChromaDB guideline vector search (PGxRAG)
3. Evidence tagging & RCG4MR semantic plausibility filter (Springer 2025)
4. Deterministic Clinical Action Ranking (standard < adjust < review < avoid)
5. Grounded Natural-Language Rationale Generation (Qwen 2.5 / Llama 3.1)
6. Faithfulness Gate: Strict verification of PMIDs, CPIC levels, and drug names

Usage:
    python llm/recommend.py HG00096
    python llm/recommend.py CYP2C19="Poor Metabolizer" CYP2D6="Ultrarapid Metabolizer"
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from explainability.evidence import tag_and_filter
from llm import client
from llm.faithfulness import check_explanation
from llm.plausibility_validator import validate_claim_plausibility
from retrieval.hybrid_retriever import HybridRetriever
from retrieval.queries import get_driver, list_phenotypes_for_gene, recommendations_for_phenotype

LEVEL_RANK = {"A": 0, "A/B": 1, "B": 2, "B/C": 3, "C": 4, "C/D": 5, "D": 6}
SEVERITY = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3}
ORDER = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3, "none": 4}

SYSTEM_PROMPT = (
    "You are a clinical pharmacogenomics assistant. Explain, in 2-3 concise sentences, why the given drug "
    "recommendation follows from the patient's pharmacogene phenotype and CPIC guidelines. "
    "Use ONLY the facts in the EVIDENCE and GUIDELINE blocks. "
    "Cite sources as PMID:<number> using only PMIDs listed there. State the CPIC level exactly as given. "
    "Do not mention any other drug. Do not add dosing advice that is not in the evidence. "
    "Reply with plain text only."
)

AVOID = ("avoid", "not recommended", "alternative", "in lieu of", "do not use", "contraindicated")
ADJUST = ("dose", "dosage", "reduc", "increas", "titrat", "monitor", "lower", "higher", "start at")
STANDARD = (
    "standard dos",
    "label recommended",
    "per standard",
    "standard of care",
    "standard starting",
    "standard dosing",
    "usual dos",
)
INTERACTION = ("inhibitor", "inducer", "concomitant", "interact")
DOSE_CHANGE = ("reduc", "lower", "titrat", "increas", "starting dose")


def classify_action(text: str, classification: str = "") -> str:
    """Infer the clinical action from CPIC's free text. Conservative: unrecognized advice is 'review', never 'standard'."""
    t = text.lower().strip()
    if classification in ("No Recommendation", "n/a") or t.startswith("no recommendation"):
        return "none"
    sentences = [x for x in re.split(r"(?<=[.;])\s+", t) if not ("avoid" in x and any(w in x for w in INTERACTION))] or [t]
    first, rest = sentences[0], " ".join(sentences[1:])
    if any(w in first for w in AVOID):
        return "review" if any(w in first for w in DOSE_CHANGE) else "avoid"
    if any(w in rest for w in AVOID):
        return "review"
    body = " ".join(sentences)
    if any(w in body for w in ADJUST):
        return "adjust"
    if any(w in body for w in STANDARD):
        return "standard"
    return "review"


def build_candidates(rows_by_gene: dict[str, list[dict]]) -> dict[str, dict]:
    """Collapse retrieved rows to one candidate per drug; worst action across genes wins."""
    cands: dict[str, dict] = {}
    for gene, rows in rows_by_gene.items():
        for r in rows:
            c = cands.setdefault(
                r["drug"],
                {
                    "drug": r["drug"],
                    "drug_id": r["drug_rxnorm_id"],
                    "action": "none",
                    "sources": [],
                    "pmids": set(),
                    "levels": set(),
                    "guidelines": set(),
                },
            )
            action = classify_action(r["recommendation"], r["classification"])
            ev = r["evidence"]
            c["levels"].add(ev["cpic_level"])
            c["pmids"].update(p.removeprefix("PMID:") for p in ev["citations"])
            if r.get("guideline"):
                c["guidelines"].add(r["guideline"])
            if not any(s["gene"] == gene and s["recommendation"] == r["recommendation"] for s in c["sources"]):
                c["sources"].append({
                    "gene": gene,
                    "recommendation": r["recommendation"],
                    "action": action,
                    "classification": r["classification"],
                    "cpic_level": ev["cpic_level"],
                })
            if action != "none" and (c["action"] == "none" or SEVERITY[action] > SEVERITY[c["action"]]):
                c["action"] = action
    return cands


def rank(cands: dict[str, dict]) -> list[dict]:
    """Preferred first: standard < adjust < review < avoid < none, then strongest CPIC level, then drug name."""
    return sorted(cands.values(), key=lambda c: (ORDER[c["action"]], min(LEVEL_RANK.get(l, 9) for l in c["levels"]), c["drug"]))


def template_explanation(c: dict, phenotypes: dict[str, str]) -> str:
    """Deterministic fallback explanation built strictly from verified graph evidence."""
    parts = [
        f"{s['gene']} {phenotypes.get(s['gene'], 'Patient')}: {s['recommendation']} (CPIC level {s['cpic_level']}, {s['classification']} recommendation)"
        for s in c["sources"]
    ]
    cites = ", ".join(f"PMID:{p}" for p in sorted(c["pmids"])) or "no citation on file"
    return " ".join(parts) + f" Sources: {cites}."


def explain(
    c: dict,
    phenotypes: dict[str, str],
    all_drugs: set[str],
    use_llm: bool,
    guideline_context: Optional[str] = None,
) -> dict:
    """Generate natural language rationale with LLM or fallback, verified by faithfulness gate."""
    fallback = template_explanation(c, phenotypes)
    if not use_llm:
        return {"text": fallback, "source": "template", "rejected_llm_output": None}

    evidence_block = json.dumps(
        {
            "drug": c["drug"],
            "patient_phenotypes": phenotypes,
            "sources": c["sources"],
            "pmids": sorted(c["pmids"]),
            "guideline_excerpt": guideline_context or "",
        },
        indent=1,
    )

    try:
        text = client.chat(SYSTEM_PROMPT, f"EVIDENCE:\n{evidence_block}").strip()
    except Exception as exc:
        return {"text": fallback, "source": "template", "rejected_llm_output": f"LLM error: {exc}"}

    problems = check_explanation(text, c["drug"], {"pmids": c["pmids"], "levels": c["levels"]}, all_drugs)
    if problems:
        return {"text": fallback, "source": "template", "rejected_llm_output": {"text": text, "problems": problems}}
    return {"text": text, "source": "llm", "rejected_llm_output": None}


def recommend(
    driver: Any,
    phenotypes: dict[str, str],
    use_llm: Optional[bool] = None,
    use_rcg4mr: bool = True,
    sample_id: Optional[str] = None,
    demographics: Optional[dict[str, Any]] = None,
    diplotypes: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Top-level recommendation function combining Layer 1 profile, Hybrid Retrieval, RCG4MR, and Faithfulness."""
    use_llm = client.available() if use_llm is None else use_llm
    retriever = HybridRetriever()

    rows_by_gene: dict[str, list[dict]] = {}
    rejected: list[dict] = []

    for gene, phenotype in phenotypes.items():
        valid = {p["name"] for p in list_phenotypes_for_gene(driver, gene)}
        if phenotype not in valid:
            raise ValueError(f"{gene}: unknown phenotype '{phenotype}'. Valid: {sorted(valid)}")

        raw_recs = recommendations_for_phenotype(driver, gene, phenotype)

        # Semantic plausibility validator hook (RCG4MR)
        semantic_val = (
            (lambda claim, p=phenotype: validate_claim_plausibility(claim, phenotype=p, use_llm=use_llm))
            if use_rcg4mr
            else None
        )

        result = tag_and_filter(raw_recs, semantic_validator=semantic_val)
        rows_by_gene[gene] = result["accepted"]
        rejected += [{"gene": gene, "drug": r.get("drug"), "reasons": r.get("rejection_reasons")} for r in result["rejected"]]

    cands = build_candidates(rows_by_gene)
    ranked = rank(cands)
    all_drugs = set(cands)

    out = []
    for i, c in enumerate(ranked, 1):
        # Retrieve vector guideline context for this drug
        drug_docs = retriever.retrieve_guideline_text(f"{c['drug']} prescribing recommendation", top_k=1)
        g_excerpt = drug_docs[0]["text"] if drug_docs else ""

        out.append({
            "rank": i,
            "drug": c["drug"],
            "drug_id": c["drug_id"],
            "action": c["action"],
            "cpic_levels": sorted(c["levels"]),
            "guidelines": sorted(c["guidelines"]),
            "citations": [f"PMID:{p}" for p in sorted(c["pmids"])],
            "evidence": c["sources"],
            "explanation": explain(c, phenotypes, all_drugs, use_llm, guideline_context=g_excerpt),
        })

    res = {
        "sample_id": sample_id,
        "demographics": demographics,
        "patient_diplotypes": diplotypes,
        "patient_phenotypes": phenotypes,
        "llm_used": use_llm,
        "rcg4mr_applied": use_rcg4mr,
        "n_drugs": len(out),
        "recommendations": out,
        "filtered_out": rejected,
    }
    return res


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: recommend.py <sample_id>  OR  recommend.py GENE="Phenotype" [GENE="Phenotype" ...]')

    driver = get_driver()
    try:
        # Check if first argument is a sample ID
        first_arg = sys.argv[1]
        if "=" not in first_arg:
            sample_id = first_arg
            from genomic.patient_profile import generate_patient_profile
            profile = generate_patient_profile(sample_id)
            out = recommend(
                driver,
                phenotypes=profile["phenotypes"],
                sample_id=profile["sample_id"],
                demographics=profile["demographics"],
                diplotypes=profile["diplotypes"],
            )
        else:
            phenotypes = dict(a.split("=", 1) for a in sys.argv[1:])
            out = recommend(driver, phenotypes)

        print(json.dumps(out, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
