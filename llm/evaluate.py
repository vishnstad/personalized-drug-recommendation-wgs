"""
Layer 3 evaluation: measures the real pipeline (Neo4j graph + recommend()), not stand-ins.

1. Action accuracy   -- expected CPIC actions for textbook phenotype/drug cases (deterministic path).
2. Retrieval scope   -- per-gene (legacy) vs patient-level retrieval: how many rows each returns, and how
                        many legacy rows belong to a genotype the patient does not have.
3. LLM grounding     -- per model: share of LLM rationales that pass the faithfulness gate, rejection
                        reasons, and latency. Rejected outputs fall back to the graph template.
4. Real samples      -- optional: Layer 1 (bcftools + PharmCAT) -> Layer 3 on 1000 Genomes samples.

Usage (Neo4j up, graph loaded; LLM endpoint optional):
    python llm/evaluate.py [--models qwen2.5:3b,qwen2.5:latest] [--llm-drugs 3] [--samples HG00096,NA12878]
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import client
from llm import recommend as rec
from retrieval.queries import get_driver, recommendations_for_patient, recommendations_for_phenotype

# Expected actions are taken from the CPIC guideline text for each pair (see docs/phenotypes_and_drugs.md).
BENCHMARK_CASES = [
    {"id": "cyp2c19_pm", "phenotypes": {"CYP2C19": "Poor Metabolizer"},
     "expected": {"clopidogrel": "avoid", "voriconazole": "avoid"}},
    {"id": "cyp2d6_pm", "phenotypes": {"CYP2D6": "Poor Metabolizer"},
     "expected": {"codeine": "avoid", "tramadol": "avoid"}},
    {"id": "cyp2d6_um", "phenotypes": {"CYP2D6": "Ultrarapid Metabolizer"},
     # (ondansetron has a CPIC level-A pair but no recommendation rows in the CPIC database, so it is not expected)
     "expected": {"codeine": "avoid", "tramadol": "avoid"}},
    {"id": "cyp2c19_pm_cyp2d6_um", "phenotypes": {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Ultrarapid Metabolizer"},
     "expected": {"clopidogrel": "avoid", "codeine": "avoid", "amitriptyline": "avoid"}},
    {"id": "both_nm", "phenotypes": {"CYP2C19": "Normal Metabolizer", "CYP2D6": "Normal Metabolizer"},
     "expected": {"codeine": "standard", "clopidogrel": "standard"}},
]


def action_accuracy(driver) -> dict[str, Any]:
    checks = []
    for case in BENCHMARK_CASES:
        out = rec.recommend(driver, case["phenotypes"])
        by_drug = {r["drug"]: r["action"] for r in out["recommendations"]}
        for drug, expected in case["expected"].items():
            got = by_drug.get(drug)
            checks.append({"case": case["id"], "drug": drug, "expected": expected, "got": got, "ok": got == expected})
    n_ok = sum(c["ok"] for c in checks)
    return {"accuracy": f"{n_ok}/{len(checks)}", "checks": checks}


def retrieval_scope(driver) -> list[dict]:
    rows = []
    for case in BENCHMARK_CASES:
        legacy = [r for g, p in case["phenotypes"].items() for r in recommendations_for_phenotype(driver, g, p)]
        patient = recommendations_for_patient(driver, case["phenotypes"])
        drugs = {r["drug"] for r in patient}
        rows.append({
            "case": case["id"],
            "legacy_per_gene_rows": len(legacy),
            "patient_level_rows": len(patient),
            # rows the per-gene query returned that do not apply to this patient's full genotype
            # (other partner-gene phenotypes / activity scores, or the same row reached via two genes)
            "excess_rows_removed": len(legacy) - len(patient),
            "drugs": len(drugs),
        })
    return rows


def llm_grounding(driver, models: list[str], drugs_per_case: int) -> dict[str, Any]:
    if not client.available():
        return {"status": f"LLM endpoint {client.BASE_URL} unreachable -- skipped"}
    results = {}
    for model in models:
        client.MODEL = model
        client.chat("Reply OK.", "OK?", timeout=600)  # warm-up: load the model before timing
        samples = []
        for case in BENCHMARK_CASES:
            ranked, _ = rec.rank_for_patient(driver, case["phenotypes"])
            actionable = [c for c in ranked if c["action"] != "none"][:drugs_per_case]
            all_drugs = {c["drug"] for c in ranked}
            for c in actionable:
                t0 = time.perf_counter()
                ex = rec.explain(c, case["phenotypes"], all_drugs, use_llm=True)
                samples.append({
                    "case": case["id"], "drug": c["drug"], "seconds": round(time.perf_counter() - t0, 1),
                    "accepted": ex["source"] == "llm", "text": ex["text"] if ex["source"] == "llm" else None,
                    "rejected": ex["rejected_llm_output"],
                })
        secs = [s["seconds"] for s in samples]
        results[model] = {
            "explanations": len(samples),
            "faithful_accepted": sum(s["accepted"] for s in samples),
            "faithfulness_pass_rate": f"{100 * sum(s['accepted'] for s in samples) / len(samples):.0f}%" if samples else "n/a",
            "median_seconds": statistics.median(secs) if secs else None,
            "max_seconds": max(secs) if secs else None,
            "samples": samples,
        }
    return results


def detailed_on_real_samples(driver, sample_ids: list[str], drugs_per_sample: int) -> dict[str, Any]:
    """Detailed (sectioned) explanations for real genomes: how many pass the faithfulness gate, how many needed
    the corrective retry, what the gate rejected, and how long / long they are."""
    from genomic.patient_profile import load_or_generate_profile
    if not client.available():
        return {"status": f"LLM endpoint {client.BASE_URL} unreachable -- skipped"}
    client.chat("Reply OK.", "OK?", timeout=600)  # warm-up
    rows = []
    for sid in sample_ids:
        p = load_or_generate_profile(sid)
        phen, scores, geno = p["phenotypes"], rec.activity_scores_from_profile(p), rec.genotypes_from_profile(p)
        ranked, _ = rec.rank_for_patient(driver, phen, scores)
        all_drugs = {c["drug"] for c in ranked}
        for c in [c for c in ranked if c["action"] != "none"][-drugs_per_sample:]:  # most cautious first
            ex = rec.explain(c, phen, all_drugs, use_llm=True, detail="detailed", genotypes=geno)
            rej = ex.get("rejected_llm_output")
            rows.append({"sample": sid, "drug": c["drug"], "action": c["action"], "accepted": ex["source"] == "llm",
                         "attempts": ex.get("attempts"), "seconds": ex.get("seconds"),
                         "llm_words": len(ex["text"].split()) if ex["source"] == "llm" else 0,
                         "first_try_problems": (ex.get("corrected") or [{}])[0].get("problems") if ex.get("corrected") else None,
                         "final_problems": rej.get("problems") if isinstance(rej, dict) else rej,
                         "sections": ex.get("sections")})
    ok = [r for r in rows if r["accepted"]]
    return {
        "model": client.MODEL, "explanations": len(rows), "accepted": len(ok),
        "accepted_first_try": sum(1 for r in ok if r["attempts"] == 1),
        "accepted_after_retry": sum(1 for r in ok if r["attempts"] > 1),
        "median_seconds": statistics.median(r["seconds"] for r in rows if r["seconds"]) if rows else None,
        "median_llm_words": statistics.median(r["llm_words"] for r in ok) if ok else None,
        "rows": rows,
    }


def real_samples(driver, sample_ids: list[str]) -> list[dict]:
    from genomic.patient_profile import generate_patient_profile
    out = []
    for sid in sample_ids:
        t0 = time.perf_counter()
        profile = generate_patient_profile(sid)
        res = rec.recommend(driver, profile["phenotypes"], sample_id=sid, diplotypes=profile["diplotypes"],
                            activity_scores=rec.activity_scores_from_profile(profile), strict=False)
        counts = {}
        for r in res["recommendations"]:
            counts[r["action"]] = counts.get(r["action"], 0) + 1
        out.append({"sample": sid, "population": profile["demographics"].get("superpopulation"),
                    "diplotypes": profile["diplotypes"], "phenotypes": res["patient_phenotypes"],
                    "actions": counts, "seconds": round(time.perf_counter() - t0, 1)})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=client.MODEL, help="comma-separated LLM model names")
    parser.add_argument("--llm-drugs", type=int, default=3, help="actionable drugs explained per case")
    parser.add_argument("--samples", default="", help="comma-separated 1000 Genomes sample IDs")
    parser.add_argument("--detailed-samples", default="", help="sample IDs for the detailed-explanation benchmark")
    parser.add_argument("--detailed-drugs", type=int, default=3, help="most cautious drugs explained per sample")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "benchmark_results.json")
    args = parser.parse_args()

    driver = get_driver()
    try:
        report = {"action_accuracy": action_accuracy(driver), "retrieval_scope": retrieval_scope(driver)}
        print("Action accuracy:", report["action_accuracy"]["accuracy"])
        for r in report["retrieval_scope"]:
            print(f"  {r['case']}: per-gene rows {r['legacy_per_gene_rows']} -> patient-level {r['patient_level_rows']}")
        report["llm_grounding"] = llm_grounding(driver, [m for m in args.models.split(",") if m], args.llm_drugs)
        for m, r in report["llm_grounding"].items():
            if isinstance(r, dict):
                print(f"  {m}: {r['faithful_accepted']}/{r['explanations']} faithful, median {r['median_seconds']}s")
        if args.samples:
            report["real_samples"] = real_samples(driver, args.samples.split(","))
        if args.detailed_samples:
            report["detailed_explanations"] = d = detailed_on_real_samples(driver, args.detailed_samples.split(","), args.detailed_drugs)
            if "accepted" in d:
                print(f"  detailed ({d['model']}): {d['accepted']}/{d['explanations']} accepted "
                      f"({d['accepted_first_try']} first try, {d['accepted_after_retry']} after retry), "
                      f"median {d['median_seconds']}s, {d['median_llm_words']} generated words")
    finally:
        driver.close()

    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
