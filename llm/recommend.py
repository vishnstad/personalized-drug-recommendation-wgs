"""
Layer 3: graph-grounded drug recommendation for one patient.

Input: the patient's resolved phenotype per pharmacogene (Layer 1's output), e.g.
    {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Ultrarapid Metabolizer"}

Pipeline: Cypher retrieval -> CPIC evidence tagging + structural plausibility filter ->
deterministic ranking from the graph -> natural-language rationale -> faithfulness check.

The ranking is NOT done by the LLM. The LLM (if an endpoint is reachable) only writes the
rationale from the retrieved evidence; any rationale that cites a PMID / CPIC level / drug that
was not retrieved is rejected and replaced by a deterministic template built from the graph.

CLI:  python3 llm/recommend.py CYP2C19="Poor Metabolizer" CYP2D6="Ultrarapid Metabolizer"
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from explainability.evidence import tag_and_filter  # noqa: E402
from llm import client  # noqa: E402
from llm.faithfulness import check_explanation  # noqa: E402
from retrieval.queries import get_driver, list_phenotypes_for_gene, recommendations_for_phenotype  # noqa: E402

LEVEL_RANK = {"A": 0, "A/B": 1, "B": 2, "B/C": 3, "C": 4, "C/D": 5, "D": 6}
SEVERITY = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3}   # worst action across genes wins
ORDER = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3, "none": 4}  # output order; "none" = CPIC gives no recommendation

SYSTEM_PROMPT = (
    "You are a clinical pharmacogenomics assistant. Explain, in 2-3 sentences, why the given drug "
    "recommendation follows from the patient's phenotype. Use ONLY the facts in the EVIDENCE block. "
    "Cite sources as PMID:<number> using only PMIDs listed there. State the CPIC level exactly as given. "
    "Do not mention any other drug. Do not add dosing advice that is not in the evidence. "
    "Reply with plain text only."
)


AVOID = ("avoid", "not recommended", "alternative", "in lieu of", "do not use", "contraindicated")
ADJUST = ("dose", "dosage", "reduc", "increas", "titrat", "monitor", "lower", "higher", "start at")
STANDARD = ("standard dos", "label recommended", "per standard", "standard of care", "standard starting",
            "standard dosing", "usual dos")


INTERACTION = ("inhibitor", "inducer", "concomitant", "interact")
DOSE_CHANGE = ("reduc", "lower", "titrat", "increas", "starting dose")


def classify_action(text: str, classification: str = "") -> str:
    """Infer the clinical action from CPIC's free text (CPIC has no structured action field; its
    alternate_drug_available / dosing flags are unpopulated for e.g. voriconazole 'choose an
    alternative'). Deliberately conservative: unrecognised or mixed advice is 'review', never 'standard'.

    - 'Avoid ... inhibitors' is a drug-interaction warning, not 'avoid the drug', so it is dropped.
    - 'Switch' advice in the FIRST sentence is 'avoid'; 'lower the dose OR switch' in one sentence, or
      switch advice only after the first sentence, is 'review' (a clinician must choose).
    """
    t = text.lower().strip()
    if classification in ("No Recommendation", "n/a") or t.startswith("no recommendation"):
        return "none"
    sentences = [x for x in re.split(r"(?<=[.;])\s+", t)
                 if not ("avoid" in x and any(w in x for w in INTERACTION))] or [t]
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
    """Collapse retrieved rows to one candidate per drug; the worst action across genes wins."""
    cands: dict[str, dict] = {}
    for gene, rows in rows_by_gene.items():
        for r in rows:
            c = cands.setdefault(r["drug"], {"drug": r["drug"], "drug_id": r["drug_rxnorm_id"], "action": "none",
                                             "sources": [], "pmids": set(), "levels": set(), "guidelines": set()})
            action = classify_action(r["recommendation"], r["classification"])
            ev = r["evidence"]
            c["levels"].add(ev["cpic_level"])
            c["pmids"].update(p.removeprefix("PMID:") for p in ev["citations"])
            if r.get("guideline"):
                c["guidelines"].add(r["guideline"])
            if not any(s["gene"] == gene and s["recommendation"] == r["recommendation"] for s in c["sources"]):
                c["sources"].append({"gene": gene, "recommendation": r["recommendation"], "action": action,
                                     "classification": r["classification"], "cpic_level": ev["cpic_level"]})
            if action != "none" and (c["action"] == "none" or SEVERITY[action] > SEVERITY[c["action"]]):
                c["action"] = action
    return cands


def rank(cands: dict[str, dict]) -> list[dict]:
    """Preferred first: standard < adjust < avoid, then strongest CPIC evidence, then name."""
    return sorted(cands.values(), key=lambda c: (ORDER[c["action"]],
                                                  min(LEVEL_RANK.get(l, 9) for l in c["levels"]), c["drug"]))


def template_explanation(c: dict, phenotypes: dict[str, str]) -> str:
    parts = [f"{s['gene']} {phenotypes[s['gene']]}: {s['recommendation']} (CPIC level {s['cpic_level']}, "
             f"{s['classification']} recommendation)" for s in c["sources"]]
    cites = ", ".join(f"PMID:{p}" for p in sorted(c["pmids"])) or "no citation on file"
    return " ".join(parts) + f" Sources: {cites}."


def explain(c: dict, phenotypes: dict[str, str], all_drugs: set[str], use_llm: bool) -> dict:
    fallback = template_explanation(c, phenotypes)
    if not use_llm:
        return {"text": fallback, "source": "template", "rejected_llm_output": None}
    evidence_block = json.dumps({"drug": c["drug"], "patient_phenotypes": phenotypes, "sources": c["sources"],
                                 "pmids": sorted(c["pmids"])}, indent=1)
    try:
        text = client.chat(SYSTEM_PROMPT, f"EVIDENCE:\n{evidence_block}").strip()
    except Exception as exc:  # endpoint died mid-run
        return {"text": fallback, "source": "template", "rejected_llm_output": f"LLM error: {exc}"}
    problems = check_explanation(text, c["drug"], {"pmids": c["pmids"], "levels": c["levels"]}, all_drugs)
    if problems:
        return {"text": fallback, "source": "template", "rejected_llm_output": {"text": text, "problems": problems}}
    return {"text": text, "source": "llm", "rejected_llm_output": None}


def recommend(driver, phenotypes: dict[str, str], use_llm: bool | None = None) -> dict:
    use_llm = client.available() if use_llm is None else use_llm
    rows_by_gene, rejected = {}, []
    for gene, phenotype in phenotypes.items():
        valid = {p["name"] for p in list_phenotypes_for_gene(driver, gene)}
        if phenotype not in valid:
            raise ValueError(f"{gene}: unknown phenotype '{phenotype}'. Valid: {sorted(valid)}")
        result = tag_and_filter(recommendations_for_phenotype(driver, gene, phenotype))
        rows_by_gene[gene] = result["accepted"]
        rejected += [{"gene": gene, "drug": r["drug"], "reasons": r["rejection_reasons"]} for r in result["rejected"]]
    cands = build_candidates(rows_by_gene)
    ranked = rank(cands)
    all_drugs = set(cands)
    out = []
    for i, c in enumerate(ranked, 1):
        out.append({"rank": i, "drug": c["drug"], "drug_id": c["drug_id"], "action": c["action"],
                    "cpic_levels": sorted(c["levels"]), "guidelines": sorted(c["guidelines"]),
                    "citations": [f"PMID:{p}" for p in sorted(c["pmids"])],
                    "evidence": c["sources"], "explanation": explain(c, phenotypes, all_drugs, use_llm)})
    return {"patient_phenotypes": phenotypes, "llm_used": use_llm, "n_drugs": len(out),
            "recommendations": out, "filtered_out": rejected}


def main():
    phenotypes = dict(a.split("=", 1) for a in sys.argv[1:])
    if not phenotypes:
        sys.exit('usage: recommend.py GENE="Phenotype" [GENE="Phenotype" ...]')
    driver = get_driver()
    try:
        print(json.dumps(recommend(driver, phenotypes), indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
