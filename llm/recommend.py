"""
Layer 3: Knowledge-Graph-Grounded Drug Recommendation Engine.

Input:
- Either a 1000 Genomes sample ID (e.g. "HG00096") or resolved patient phenotypes
  (e.g. {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Ultrarapid Metabolizer"}).

Pipeline:
1. Patient Profile ingestion (Layer 1 output: phenotypes, diplotypes, activity scores)
2. Patient-level Cypher retrieval: only CPIC recommendations whose *full* gene condition
   (multi-gene + activity score) matches this patient
3. Evidence tagging + structural plausibility filter (explainability/evidence.py)
4. Deterministic action classification; RCG4MR pharmacological rules cross-check it
   (a contradiction downgrades the drug to 'review' with a warning, never deletes CPIC guidance)
5. Deterministic ranking (standard < adjust < review < avoid < none)
6. Rationale: graph-built template, or -- on demand, via explain_drug() -- a local LLM paraphrase
   that must pass the faithfulness gate (PMIDs, CPIC levels, drug names) or is replaced by the template

Usage:
    python llm/recommend.py HG00096 [--llm]
    python llm/recommend.py CYP2C19="Poor Metabolizer" CYP2D6="Ultrarapid Metabolizer" [--llm]
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from explainability.evidence import tag_and_filter
from llm import client
from llm.faithfulness import check_explanation
from llm.plausibility_validator import validate_claim_plausibility
from retrieval.hybrid_retriever import guideline_text_for_drug
from retrieval.queries import NO_RESULT, get_driver, list_phenotypes_for_gene, recommendations_for_patient

LEVEL_RANK = {"A": 0, "A/B": 1, "B": 2, "B/C": 3, "C": 4, "C/D": 5, "D": 6}
SEVERITY = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3}
ORDER = {"standard": 0, "adjust": 1, "review": 2, "avoid": 3, "none": 4}

SYSTEM_PROMPT = (
    "You are a clinical pharmacogenomics assistant. Explain, in 2-3 concise sentences, why the given drug "
    "recommendation follows from the patient's pharmacogene phenotype and CPIC guidelines. "
    "Use ONLY the facts in the EVIDENCE block. "
    "Cite sources as PMID:<number> using only PMIDs listed there. State the CPIC level exactly as given. "
    "Only mention other drugs if they appear in the recommendation text. "
    "Do not add dosing advice that is not in the evidence. "
    "Reply with plain text only."
)

# Detailed explanation = LLM prose where explanation helps + verbatim facts where precision matters.
# Sources: "llm" (generated, faithfulness-checked), "pharmcat" (genotype call), "cpic" (graph text, verbatim).
DETAILED_SECTIONS = [  # (key, title, source)
    ("summary", "In short", "llm"),
    ("genotype", "This patient's genotype", "pharmcat"),
    ("mechanism", "Why it matters for this drug", "llm"),
    ("recommendation", "What CPIC recommends", "cpic"),
    ("evidence", "Strength of evidence", "cpic"),
    ("considerations", "Things to consider", "llm"),
]
LLM_KEYS = [k for k, _, src in DETAILED_SECTIONS if src == "llm"]
DETAILED_PROMPT = (
    "You are a clinical pharmacogenomics assistant explaining a CPIC recommendation to a clinician. Use ONLY the "
    "facts in the EVIDENCE block. Return a JSON object with exactly these keys: " + ", ".join(LLM_KEYS) + ". "
    "Each value is plain text (no markdown, no lists), 2 to 4 full sentences. "
    "summary: the bottom line for this patient and this drug in plain words: their phenotype (exactly as given in "
    "patient_phenotypes) and what CPIC advises. Do not restate the alleles. "
    "mechanism: explain why that phenotype changes this drug's effect or safety, using only 'mechanism' and "
    "'implications'; if neither is given, say that CPIC does not describe the mechanism here. "
    "considerations: only restate alternatives or monitoring that the CPIC recommendation text itself names (if none, "
    "say so), then add one sentence in your own voice (do not attribute it to CPIC) that this result reflects genetics "
    "only, and that other medicines, age and organ function also matter. Do not add risks or monitoring that the "
    "evidence does not mention, and never attribute to CPIC anything that is not in its recommendation text. "
    "Do not mention any drug, allele, dose, percentage or study that is not in the evidence. "
    "When contrasting with other phenotypes, refer to them in the plural (e.g. 'normal metabolizers')."
)
MAX_ATTEMPTS = 2  # one retry: the gate's problems are fed back so the model can correct itself

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
    # "use at standard dose (75 mg/day)" names a dose but changes nothing -> standard, unless a change is also asked for
    if any(w in body for w in STANDARD) and not any(w in body for w in DOSE_CHANGE + ("monitor",)):
        return "standard"
    if any(w in body for w in ADJUST):
        return "adjust"
    if any(w in body for w in STANDARD):
        return "standard"
    return "review"


def describe_condition(condition: dict[str, str]) -> str:
    """{'CYP2C19': 'Poor Metabolizer', 'CYP2D6': 'Normal Metabolizer'} -> 'CYP2C19 Poor Metabolizer + CYP2D6 Normal Metabolizer'."""
    return " + ".join(f"{g} {p}" for g, p in sorted(condition.items()))


def check_plausibility(row: dict, phenotypes: dict[str, str]) -> tuple[str, list[str]]:
    """Run the RCG4MR pharmacological rules on a classified row, once per gene in its condition.
    A contradiction means our text classifier probably misread CPIC, so 'standard' is downgraded
    to 'review' and the reason is surfaced -- CPIC guidance itself is never dropped."""
    action, warnings = row["action"], []
    for gene in row.get("genes") or []:
        claim = {"drug": row["drug"], "gene": gene, "recommendation": row["recommendation"], "action": action}
        ok, reason = validate_claim_plausibility(claim, phenotype=phenotypes.get(gene, ""), use_llm=False)
        if not ok:
            warnings.append(reason)
    if warnings and action == "standard":
        action = "review"
    return action, warnings


def build_candidates(rows: list[dict]) -> dict[str, dict]:
    """Collapse matched rows to one candidate per drug. A drug can have several rows -- one per
    population (adults/pediatrics, ACS-PCI/non-ACS...) -- each kept as its own source; the drug's
    headline action is the most cautious one across them."""
    cands: dict[str, dict] = {}
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
        action = r.get("action") or classify_action(r["recommendation"], r["classification"])
        ev = r["evidence"]
        c["levels"].add(ev["cpic_level"])
        c["pmids"].update(p.removeprefix("PMID:") for p in ev["citations"])
        if r.get("guideline"):
            c["guidelines"].add(r["guideline"])
        c["sources"].append({
            "recommendation_id": r.get("recommendation_id"),
            "condition": r.get("condition") or {},
            "genes": r.get("genes") or [],
            "population": r.get("population") or "general",
            "recommendation": r["recommendation"],
            "implications": r.get("implications"),
            "action": action,
            "classification": r["classification"],
            "cpic_level": ev["cpic_level"],
            "warnings": r.get("warnings") or [],
        })
        if action != "none" and (c["action"] == "none" or SEVERITY[action] > SEVERITY[c["action"]]):
            c["action"] = action
    return cands


def rank(cands: dict[str, dict]) -> list[dict]:
    """Preferred first: standard < adjust < review < avoid < none, then strongest CPIC level, then drug name."""
    return sorted(cands.values(), key=lambda c: (ORDER[c["action"]], min(LEVEL_RANK.get(l, 9) for l in c["levels"]), c["drug"]))


def template_explanation(c: dict) -> str:
    """Deterministic fallback explanation built strictly from verified graph evidence."""
    parts = []
    for s in c["sources"]:
        context = describe_condition(s["condition"])
        if s["population"] not in ("general", ""):
            context += f" ({s['population'].strip()})"
        parts.append(f"{context}: {s['recommendation']} (CPIC level {s['cpic_level']}, {s['classification']} recommendation).")
    cites = ", ".join(f"PMID:{p}" for p in sorted(c["pmids"])) or "no citation on file"
    return " ".join(parts) + f" Sources: {cites}."


def _implications(source: dict) -> dict[str, str]:
    try:
        return json.loads(source.get("implications") or "{}")
    except (TypeError, ValueError):
        return {}


def _graph_sections(c: dict) -> dict[str, str]:
    """The sections taken verbatim from the knowledge graph (never generated)."""
    recs = []
    for s in c["sources"]:
        pop = s["population"].strip()
        label = describe_condition(s["condition"]) + (f", {pop}" if pop not in ("general", "") else "")
        strength = "" if s["classification"] in ("No Recommendation", "n/a", "") else f" ({s['classification']} recommendation)"
        recs.append(f"{label}: {s['recommendation']}{strength}")
    levels = ", ".join(sorted(l for l in c["levels"] if l)) or "not graded"
    cites = ", ".join(f"PMID:{p}" for p in sorted(c["pmids"])) or "no citation on file"
    return {
        "recommendation": "\n".join(recs),  # one line per patient group (population)
        "evidence": f"CPIC evidence level {levels} for this gene-drug pair. Guideline: "
                    f"{'; '.join(sorted(c['guidelines'])) or 'n/a'}. Sources: {cites}.",
    }


def _genotype_facts(c: dict, phenotypes: dict[str, str], genotypes: Optional[dict[str, dict]]) -> list[str]:
    """One verified line per relevant gene, spelling out each chromosome copy so it cannot be misread, e.g.
    'CYP2D6 (activity score 0.0 -> Poor Metabolizer): copy 1 carries *3 (No function, activity 0.0); copy 2
    carries *4 (No function, activity 0.0)'."""
    def allele(a: dict) -> str:
        act = f", activity {a['activity_value']}" if a.get("activity_value") not in (None, "") else ""
        return f"{a['allele']} ({a['function'] or 'function unknown'}{act})"

    lines = []
    for gene in sorted({g for s in c["sources"] for g in s["genes"]}):
        ph = phenotypes.get(gene, "No Result")
        g = (genotypes or {}).get(gene)
        if not g or len(g.get("alleles") or []) != 2:
            lines.append(f"{gene}: {ph} (no allele detail available)")
            continue
        a1, a2 = g["alleles"]
        head = f"{gene} (" + (f"activity score {g['activity_score']} -> " if g.get("activity_score") is not None else "") + f"{ph})"
        if a1["allele"] == a2["allele"]:
            lines.append(f"{head}: both copies carry {allele(a1)}")
        else:
            lines.append(f"{head}: copy 1 carries {allele(a1)}; copy 2 carries {allele(a2)}")
    return lines


def _genotype_prose(c: dict, phenotypes: dict[str, str], genotypes: Optional[dict[str, dict]]) -> str:
    """Plain-English genotype explanation from the PharmCAT call (deterministic, so it cannot misstate copies)."""
    out = []
    for gene in sorted({g for s in c["sources"] for g in s["genes"]}):
        ph = phenotypes.get(gene, "No Result")
        article = "an" if ph[:1].lower() in "aeiou" else "a"
        g = (genotypes or {}).get(gene)
        if not g or len(g.get("alleles") or []) != 2:
            out.append(f"{gene}: {ph} (phenotype given without allele detail).")
            continue
        a1, a2 = g["alleles"]
        fn = lambda a: (a["function"] or "function unknown").lower()  # noqa: E731
        if a1["allele"] == a2["allele"]:
            sentence = f"Both copies of {gene} carry the {a1['allele']} allele ({fn(a1)})."
        else:
            sentence = f"One copy of {gene} carries {a1['allele']} ({fn(a1)}) and the other carries {a2['allele']} ({fn(a2)})."
        vals = [a.get("activity_value") for a in (a1, a2)]
        if g.get("activity_score") is not None and all(v not in (None, "") for v in vals):
            sentence += f" Their activity values ({vals[0]} + {vals[1]}) give an activity score of {g['activity_score']},"
            sentence += f" which CPIC classifies as {article} {ph}."
        else:
            sentence += f" CPIC classifies this combination as {article} {ph}."
        out.append(sentence)
    return " ".join(out)


def template_sections(c: dict, phenotypes: dict[str, str], genotypes: Optional[dict[str, dict]] = None) -> list[dict]:
    """The detailed fallback: same section layout, filled only with genotype and graph facts."""
    why = sorted({f"{g}: {t}" for s in c["sources"] for g, t in _implications(s).items() if t})
    body = {"genotype": _genotype_prose(c, phenotypes, genotypes), "mechanism": " ".join(_mechanism_facts(c) + why),
            **_graph_sections(c)}
    return [{"key": k, "title": t, "text": body[k], "source": "cpic" if k == "mechanism" else src}
            for k, t, src in DETAILED_SECTIONS if body.get(k)]


def _mechanism_facts(c: dict) -> list[str]:
    """Curated prodrug-activation vs clearance facts (llm/plausibility_validator.py) for this drug's genes."""
    from llm.plausibility_validator import PHARMACOLOGICAL_PATHWAYS

    facts = []
    for gene in sorted({g for s in c["sources"] for g in s["genes"]}):
        p = PHARMACOLOGICAL_PATHWAYS.get((gene, c["drug"].lower()))
        if not p:
            continue
        if p["mechanism"] == "prodrug_bioactivation":
            facts.append(f"{c['drug']} is a prodrug: {gene} converts it into its active form ({p['active_metabolite']}).")
        else:
            facts.append(f"{gene} clears active {c['drug']} from the body (main risk when clearance changes: "
                         f"{p['risk'].replace('_', ' ')}).")
    return facts


def _parse_sections(raw: str) -> dict[str, str] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for key in LLM_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            val = " ".join(str(v) for v in val)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out or None


def explain(
    c: dict,
    phenotypes: dict[str, str],
    all_drugs: set[str],
    use_llm: bool,
    detail: str = "brief",
    genotypes: Optional[dict[str, dict]] = None,
) -> dict:
    """Natural-language rationale.
    brief:    2-3 LLM sentences.
    detailed: six sections. The LLM writes "In short", "Why it matters" and "Things to consider" from the
              retrieved evidence; the genotype section is generated from the PharmCAT call, and "What CPIC
              recommends" / "Strength of evidence" are copied verbatim from the graph.
    The LLM text must pass the faithfulness gate (PMIDs, CPIC levels, drug names, phenotype claims, star alleles,
    zygosity, doses). A rejected detailed answer gets one retry with the problems fed back; if it still fails,
    the graph-built explanation is returned instead."""
    detailed = detail == "detailed"
    fallback = {"text": template_explanation(c), "source": "template", "rejected_llm_output": None, "detail": detail,
                "sections": template_sections(c, phenotypes, genotypes) if detailed else None}
    if not use_llm:
        return fallback

    genes = sorted({g for s in c["sources"] for g in s["genes"]})
    evidence = {
        "drug": c["drug"],
        "patient_phenotypes": {g: phenotypes.get(g, "No Result") for g in genes} if detailed else phenotypes,
        "cpic_recommendations": [
            {**{k: s[k] for k in ("condition", "population", "recommendation", "classification", "cpic_level")},
             "implications": _implications(s)}
            for s in c["sources"]
        ],
        "pmids": sorted(c["pmids"]),
        "guideline_summary": guideline_text_for_drug(c["drug"]),
    }
    if detailed:
        evidence["genotype_facts"] = _genotype_facts(c, phenotypes, genotypes)
        evidence["mechanism"] = _mechanism_facts(c)
    evidence_block = json.dumps(evidence, indent=1)

    # drugs named in the evidence itself (e.g. "use prasugrel or ticagrelor") are legitimate to repeat
    forbidden = {d for d in all_drugs if d.lower() not in evidence_block.lower()}
    diplotypes = {g: d["diplotype"] for g, d in (genotypes or {}).items() if d.get("diplotype")}
    user = f"EVIDENCE:\n{evidence_block}"
    t0, attempts, history = time.perf_counter(), 0, []
    while True:
        attempts += 1
        try:
            if detailed:
                raw = client.chat(DETAILED_PROMPT, user, json_mode=True, timeout=240).strip()
                parsed = _parse_sections(raw)
                text = " ".join(parsed.values()) if parsed else raw
            else:
                text = client.chat(SYSTEM_PROMPT, user).strip()
                parsed = None
        except Exception as exc:
            return {**fallback, "rejected_llm_output": f"LLM error: {exc}"}
        problems = check_explanation(text, c["drug"], {"pmids": c["pmids"], "levels": c["levels"]}, forbidden, phenotypes,
                                     evidence_text=evidence_block if detailed else None, diplotypes=diplotypes or None)
        if detailed and not parsed:
            problems.append("reply was not the requested JSON sections")
        if not problems or not detailed or attempts >= MAX_ATTEMPTS:
            break
        history.append({"text": text, "problems": problems})
        user = (f"EVIDENCE:\n{evidence_block}\n\nYour previous answer was rejected by the fact checker:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nWrite all sections again, fixing these problems and using only the evidence.")
    meta = {"seconds": round(time.perf_counter() - t0, 1), "model": client.MODEL, "attempts": attempts,
            "corrected": history if not problems else None}
    if problems:
        return {**fallback, **meta, "rejected_llm_output": {"text": text, "problems": problems}}
    sections = None
    if detailed:
        fixed = {"genotype": _genotype_prose(c, phenotypes, genotypes), **_graph_sections(c)}
        sections = [{"key": k, "title": t, "text": parsed.get(k) if src == "llm" else fixed.get(k), "source": src}
                    for k, t, src in DETAILED_SECTIONS if (parsed.get(k) if src == "llm" else fixed.get(k))]
    return {"text": text, "source": "llm", "rejected_llm_output": None, "detail": detail, "sections": sections, **meta}


def resolve_phenotypes(driver: Any, phenotypes: dict[str, str], strict: bool = True) -> tuple[dict[str, str], list[str]]:
    """Check each phenotype against the graph. strict: unknown -> ValueError (manual input).
    Non-strict (Layer 1 output): an unmatched call (e.g. PharmCAT 'n/a') becomes CPIC's 'No Result'
    for that gene, with a warning, instead of aborting the whole patient."""
    resolved, notes = {}, []
    for gene, phenotype in phenotypes.items():
        valid = {p["name"] for p in list_phenotypes_for_gene(driver, gene)}
        if phenotype in valid:
            resolved[gene] = phenotype
        elif strict:
            raise ValueError(f"{gene}: unknown phenotype '{phenotype}'. Valid: {sorted(valid)}")
        else:
            resolved[gene] = NO_RESULT
            notes.append(f"{gene}: phenotype '{phenotype}' has no CPIC category; treated as '{NO_RESULT}'.")
    return resolved, notes


def rank_for_patient(
    driver: Any,
    phenotypes: dict[str, str],
    activity_scores: Optional[dict[str, float]] = None,
    use_rcg4mr: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Retrieve, filter, classify and rank. Returns (ranked candidates, rejected rows)."""
    rows = recommendations_for_patient(driver, phenotypes, activity_scores)
    result = tag_and_filter(rows)
    rejected = [{"drug": r.get("drug"), "genes": r.get("genes"), "reasons": r.get("rejection_reasons")} for r in result["rejected"]]
    accepted = []
    for row in result["accepted"]:
        row["action"] = classify_action(row["recommendation"], row["classification"])
        if use_rcg4mr:
            row["action"], row["warnings"] = check_plausibility(row, phenotypes)
        accepted.append(row)
    return rank(build_candidates(accepted)), rejected


def _format(i: int, c: dict, explanation: dict) -> dict:
    return {
        "rank": i,
        "drug": c["drug"],
        "drug_id": c["drug_id"],
        "action": c["action"],
        "cpic_levels": sorted(c["levels"]),
        "guidelines": sorted(c["guidelines"]),
        "citations": [f"PMID:{p}" for p in sorted(c["pmids"])],
        "evidence": c["sources"],
        "explanation": explanation,
    }


def recommend(
    driver: Any,
    phenotypes: dict[str, str],
    use_llm: bool = False,
    use_rcg4mr: bool = True,
    sample_id: Optional[str] = None,
    demographics: Optional[dict[str, Any]] = None,
    diplotypes: Optional[dict[str, str]] = None,
    activity_scores: Optional[dict[str, float]] = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Full ranked recommendation list for one patient. Explanations are graph templates unless
    use_llm=True (one LLM call per drug -- slow on a laptop GPU; prefer explain_drug() on demand)."""
    resolved, notes = resolve_phenotypes(driver, phenotypes, strict=strict)
    ranked, rejected = rank_for_patient(driver, resolved, activity_scores, use_rcg4mr)
    all_drugs = {c["drug"] for c in ranked}
    out = [_format(i, c, explain(c, resolved, all_drugs, use_llm)) for i, c in enumerate(ranked, 1)]
    return {
        "sample_id": sample_id,
        "demographics": demographics,
        "patient_diplotypes": diplotypes,
        "patient_phenotypes": resolved,
        "activity_scores": activity_scores,
        "notes": notes,
        "llm_used": use_llm,
        "rcg4mr_applied": use_rcg4mr,
        "n_drugs": len(out),
        "recommendations": out,
        "filtered_out": rejected,
    }


_EXPLANATION_CACHE: dict[tuple, dict] = {}


def explain_drug(
    driver: Any,
    phenotypes: dict[str, str],
    drug: str,
    activity_scores: Optional[dict[str, float]] = None,
    use_llm: bool = True,
    detail: str = "brief",
    genotypes: Optional[dict[str, dict]] = None,
) -> dict:
    """On-demand rationale for one drug (what the UI calls when a user asks for an explanation).
    Cached per (patient, drug, detail) since local generation takes seconds."""
    key = (drug, tuple(sorted(phenotypes.items())), tuple(sorted((activity_scores or {}).items())), use_llm, detail,
           json.dumps(genotypes, sort_keys=True))
    if key not in _EXPLANATION_CACHE:
        ranked, _ = rank_for_patient(driver, phenotypes, activity_scores)
        by_drug = {c["drug"]: c for c in ranked}
        if drug not in by_drug:
            raise KeyError(f"No CPIC recommendation for '{drug}' matches this patient.")
        _EXPLANATION_CACHE[key] = explain(by_drug[drug], phenotypes, set(by_drug), use_llm, detail, genotypes)
    return _EXPLANATION_CACHE[key]


def genotypes_from_profile(profile: dict) -> dict[str, dict]:
    """Per-gene genotype facts from a Layer 1 profile, for the detailed explanation."""
    out = {}
    for gene, d in (profile or {}).get("genes", {}).items():
        out[gene] = {
            "diplotype": d.get("diplotype"),
            "phenotype": d.get("phenotype"),
            "activity_score": d.get("activity_score"),
            "alleles": [{"allele": h.get("name"), "function": h.get("function"), "activity_value": h.get("activity")}
                        for h in (d.get("haplotype_1") or {}, d.get("haplotype_2") or {}) if h.get("name")],
        }
    return out


def activity_scores_from_profile(profile: dict) -> dict[str, float]:
    return {g: d["activity_score"] for g, d in profile.get("genes", {}).items() if isinstance(d.get("activity_score"), (int, float))}


def main():
    args = [a for a in sys.argv[1:] if a != "--llm"]
    use_llm = "--llm" in sys.argv
    if not args:
        sys.exit('usage: recommend.py <sample_id> [--llm]  OR  recommend.py GENE="Phenotype" [...] [--llm]')

    driver = get_driver()
    try:
        if "=" not in args[0]:
            from genomic.patient_profile import generate_patient_profile
            profile = generate_patient_profile(args[0])
            out = recommend(
                driver,
                phenotypes=profile["phenotypes"],
                use_llm=use_llm,
                sample_id=profile["sample_id"],
                demographics=profile["demographics"],
                diplotypes=profile["diplotypes"],
                activity_scores=activity_scores_from_profile(profile),
                strict=False,
            )
        else:
            out = recommend(driver, dict(a.split("=", 1) for a in args), use_llm=use_llm)

        print(json.dumps(out, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
