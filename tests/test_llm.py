"""Tests for the grounded recommender. Unit tests need no services; the integration test needs
Neo4j with the graph loaded. The LLM is always stubbed (no model is required to run the tests)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llm import recommend as rec  # noqa: E402
from llm.faithfulness import check_explanation  # noqa: E402
from retrieval.queries import get_driver  # noqa: E402


def test_avoid_inhibitors_is_not_avoid_the_drug():
    # real CPIC tamoxifen text: the 'avoid' is a drug-interaction warning, dosing is standard
    t = "Avoid moderate and strong CYP2D6 inhibitors. Initiate therapy with recommended standard of care dosing (tamoxifen 20 mg/day)."
    assert rec.classify_action(t, "Strong") == "standard"


def test_dose_or_switch_is_review_not_avoid():
    t = ("Consider a lower starting dose, slower titration schedule and 50% reduction of standard maintenance dose "
         "or select a clinically appropriate alternative antidepressant not predominantly metabolized by CYP2C19.")
    assert rec.classify_action(t, "Moderate") == "review"


def test_alternative_agent_is_avoid_not_standard():
    # real CPIC voriconazole text for CYP2C19 PM: mentions "standard dosage" but means avoid
    t = ("Choose an alternative agent that is not dependent on CYP2C19 metabolism as primary therapy in lieu of "
         "voriconazole. ... administered at a preferably lower than standard dosage with careful monitoring.")
    assert rec.classify_action(t, "Moderate") == "avoid"


@pytest.mark.parametrize("text,cls,expected", [
    ("Abacavir is not recommended", "Strong", "avoid"),
    ("Use abacavir per standard dosing guidelines", "Strong", "standard"),
    ("If considering clopidogrel, use at standard dose (75 mg/day)", "Strong", "standard"),  # names a dose, changes nothing
    ("Use standard starting dose and monitor for toxicity", "Moderate", "adjust"),
    ("Reduce starting dose by 50% followed by titration", "Strong", "adjust"),
    ("No recommendation", "No Recommendation", "none"),
    ("Something CPIC phrased in an unforeseen way", "Optional", "review"),  # never defaults to standard
])
def test_classify_action(text, cls, expected):
    assert rec.classify_action(text, cls) == expected


def test_most_cautious_population_wins_and_none_does_not_mask():
    def row(action_text, cls, population):
        return {"drug": "x", "drug_rxnorm_id": "RxNorm:1", "recommendation": action_text, "classification": cls,
                "guideline": "g", "population": population, "condition": {"G1": "PM"}, "genes": ["G1"],
                "evidence": {"cpic_level": "A", "citations": ["PMID:1"]}}
    c = rec.build_candidates([row("No recommendation", "No Recommendation", "adults"),
                              row("Avoid x", "Strong", "pediatrics")])
    assert c["x"]["action"] == "avoid"
    assert [s["population"] for s in c["x"]["sources"]] == ["adults", "pediatrics"]  # both contexts kept
    only_none = rec.build_candidates([row("No recommendation", "No Recommendation", "adults")])
    assert only_none["x"]["action"] == "none"


def test_plausibility_contradiction_downgrades_instead_of_dropping():
    r = {"drug": "codeine", "genes": ["CYP2D6"], "recommendation": "Use label recommended dosing", "action": "standard"}
    action, warnings = rec.check_plausibility(r, {"CYP2D6": "Poor Metabolizer"})
    assert action == "review" and warnings


def test_faithfulness_rejects_invented_facts():
    ev = {"pmids": {"111"}, "levels": {"A"}}
    assert check_explanation("Avoid it (CPIC level A, PMID:111).", "codeine", ev, {"codeine", "tramadol"}) == []
    bad = check_explanation("CPIC level B, see PMID:999; tramadol is safer.", "codeine", ev, {"codeine", "tramadol"})
    assert len(bad) == 3


PATIENT = {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Ultrarapid Metabolizer"}


def test_faithfulness_rejects_wrong_phenotype_claim():
    # real qwen2.5:3b output from the benchmark: the patient is a CYP2D6 *Ultrarapid* Metabolizer
    bad = "The recommendation follows as the patient is a Poor Metabolizer of CYP2D6 and Ultrarapid Metabolizer of CYP2D6."
    problems = check_explanation(bad, "atomoxetine", {"pmids": set(), "levels": {"A"}}, set(), PATIENT)
    assert problems == ["calls the patient a CYP2D6 Poor Metabolizer but they are CYP2D6 Ultrarapid Metabolizer"]


@pytest.mark.parametrize("text", [
    "The patient's CYP2C19 Poor Metabolizer phenotype increases exposure.",
    "As an Ultrarapid Metabolizer for CYP2D6 and a CYP2C19 poor metabolizer, the patient ...",
    "The patient's CYP2D6 phenotype as an Ultrarapid Metabolizer lowers exposure.",
])
def test_faithfulness_accepts_correct_phenotype_claims(text):
    assert check_explanation(text, "x", {"pmids": set(), "levels": {"A"}}, set(), PATIENT) == []


@pytest.fixture(scope="module")
def driver():
    d = get_driver()
    try:
        d.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j database is not reachable at localhost:7687: {e}")
    yield d
    d.close()


def test_end_to_end_cyp2c19_poor_metabolizer(driver):
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer"}, use_llm=False)
    by = {r["drug"]: r for r in out["recommendations"]}
    assert by["clopidogrel"]["action"] == "avoid" and "A" in by["clopidogrel"]["cpic_levels"]
    assert by["voriconazole"]["action"] == "avoid"
    assert all(r["citations"] for r in out["recommendations"])  # plausibility filter guarantees a citation
    order = [r["action"] for r in out["recommendations"]]
    assert order == sorted(order, key=rec.ORDER.get)  # preferred first, avoid later, none last


def test_unknown_phenotype_is_rejected(driver):
    with pytest.raises(ValueError, match="unknown phenotype"):
        rec.recommend(driver, {"CYP2C19": "Super Metabolizer"}, use_llm=False)


def test_unknown_layer1_phenotype_becomes_no_result(driver):
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer", "CYP2D6": "n/a"}, strict=False)
    assert out["patient_phenotypes"]["CYP2D6"] == "No Result" and out["notes"]


def test_llm_may_repeat_alternatives_named_in_the_evidence(driver, monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda s, u: "CPIC advises an alternative such as prasugrel or ticagrelor.")
    ex = rec.explain_drug(driver, {"CYP2C19": "Poor Metabolizer"}, "clopidogrel")
    assert ex["source"] == "llm", ex


def test_llm_output_that_invents_a_citation_is_replaced(driver, monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda s, u: "Avoid it. PMID:99999999 proves this.")
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer"}, use_llm=True)
    ex = out["recommendations"][0]["explanation"]
    assert ex["source"] == "template" and ex["rejected_llm_output"]["problems"]


def test_faithful_llm_output_is_kept(driver, monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda s, u: "The graph recommends caution for this phenotype.")
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer"}, use_llm=True)
    assert out["recommendations"][0]["explanation"]["source"] == "llm"


# ---- detailed explanations
def test_gate_rejects_wrong_zygosity_alleles_and_doses():
    ev = {"pmids": {"1"}, "levels": {"A"}}
    evidence_text = "copy 1 carries *3 (No function); copy 2 carries *4 (No function). Consider a 50% reduction."
    dips = {"CYP2D6": "*3/*4"}
    bad = "The patient has two copies of the *3 allele and is homozygous for *4. Use 25% of the dose; *10 is absent."
    problems = check_explanation(bad, "codeine", ev, set(), None, evidence_text=evidence_text, diplotypes=dips)
    assert any("two copies of *3" in p for p in problems) and any("two copies of *4" in p for p in problems)
    assert any("*10" in p for p in problems) and any("25%" in p for p in problems)
    good = "One copy carries *3 and the other *4; CPIC suggests a 50 % reduction."
    assert check_explanation(good, "codeine", ev, set(), None, evidence_text=evidence_text, diplotypes=dips) == []
    assert check_explanation("Both copies carry *2.", "x", ev, set(), None, diplotypes={"CYP2C19": "*2/*2"}) == []


def test_plural_phenotype_is_a_comparison_not_a_claim():
    assert check_explanation("Unlike CYP2D6 normal metabolizers, exposure is higher.", "x",
                             {"pmids": set(), "levels": {"A"}}, set(), PATIENT) == []


CAND = {"drug": "codeine", "drug_id": "RxNorm:1", "action": "avoid", "levels": {"A"}, "pmids": {"22205192"},
        "guidelines": {"CYP2D6, OPRM1, COMT, and Opioids"},
        "sources": [{"recommendation_id": 1, "condition": {"CYP2D6": "Poor Metabolizer"}, "genes": ["CYP2D6"],
                     "population": "general", "recommendation": "Avoid codeine use because of possibility of diminished analgesia.",
                     "implications": '{"CYP2D6": "Greatly reduced morphine formation"}', "action": "avoid",
                     "classification": "Strong", "cpic_level": "A", "warnings": []}]}
GENO = {"CYP2D6": {"diplotype": "*3/*4", "phenotype": "Poor Metabolizer", "activity_score": 0.0,
                   "alleles": [{"allele": "*3", "function": "No function", "activity_value": "0.0"},
                               {"allele": "*4", "function": "No function", "activity_value": "0.0"}]}}
PM = {"CYP2D6": "Poor Metabolizer"}


def test_genotype_section_is_built_from_the_call():
    text = rec._genotype_prose(CAND, PM, GENO)
    assert "One copy of CYP2D6 carries *3 (no function) and the other carries *4 (no function)" in text
    assert "activity score of 0.0" in text and "a Poor Metabolizer" in text


def test_detailed_explanation_sections_and_sources(monkeypatch):
    import json as _json
    reply = {"summary": "As a CYP2D6 Poor Metabolizer, this patient should avoid codeine (PMID:22205192).",
             "mechanism": "CYP2D6 converts codeine into morphine, so little morphine is formed.",
             "considerations": "The CPIC text names no specific alternative here. This reflects genetics only."}
    monkeypatch.setattr(rec.client, "chat", lambda *a, **k: _json.dumps(reply))
    ex = rec.explain(CAND, PM, {"codeine"}, use_llm=True, detail="detailed", genotypes=GENO)
    assert ex["source"] == "llm" and ex["attempts"] == 1
    by = {s["key"]: s for s in ex["sections"]}
    assert [s["key"] for s in ex["sections"]] == ["summary", "genotype", "mechanism", "recommendation", "evidence", "considerations"]
    assert by["genotype"]["source"] == "pharmcat" and by["recommendation"]["source"] == "cpic" and by["summary"]["source"] == "llm"
    assert "Avoid codeine use" in by["recommendation"]["text"] and "CPIC evidence level A" in by["evidence"]["text"]


def test_detailed_explanation_retries_once_with_the_problems(monkeypatch):
    import json as _json
    replies = iter([
        _json.dumps({"summary": "This CYP2D6 Normal Metabolizer should avoid codeine.", "mechanism": "m", "considerations": "c"}),
        _json.dumps({"summary": "This CYP2D6 Poor Metabolizer should avoid codeine.", "mechanism": "m", "considerations": "c"}),
    ])
    prompts = []
    monkeypatch.setattr(rec.client, "chat", lambda s, u, **k: (prompts.append(u), next(replies))[1])
    ex = rec.explain(CAND, PM, {"codeine"}, use_llm=True, detail="detailed", genotypes=GENO)
    assert ex["source"] == "llm" and ex["attempts"] == 2 and ex["corrected"][0]["problems"]
    assert "rejected by the fact checker" in prompts[1]


def test_detailed_explanation_falls_back_to_graph_sections(monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda *a, **k: "not json at all")
    ex = rec.explain(CAND, PM, {"codeine"}, use_llm=True, detail="detailed", genotypes=GENO)
    assert ex["source"] == "template" and ex["attempts"] == 2
    assert {s["key"] for s in ex["sections"]} >= {"genotype", "recommendation", "evidence"}
