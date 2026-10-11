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
    ("Reduce starting dose by 50% followed by titration", "Strong", "adjust"),
    ("No recommendation", "No Recommendation", "none"),
    ("Something CPIC phrased in an unforeseen way", "Optional", "review"),  # never defaults to standard
])
def test_classify_action(text, cls, expected):
    assert rec.classify_action(text, cls) == expected


def test_worst_action_wins_and_none_does_not_mask():
    def row(action_text, cls):
        return {"drug": "x", "drug_rxnorm_id": "RxNorm:1", "recommendation": action_text, "classification": cls,
                "guideline": "g", "evidence": {"cpic_level": "A", "citations": ["PMID:1"]}}
    c = rec.build_candidates({"G1": [row("No recommendation", "No Recommendation")],
                              "G2": [row("Avoid x", "Strong")]})
    assert c["x"]["action"] == "avoid"
    only_none = rec.build_candidates({"G1": [row("No recommendation", "No Recommendation")]})
    assert only_none["x"]["action"] == "none"


def test_faithfulness_rejects_invented_facts():
    ev = {"pmids": {"111"}, "levels": {"A"}}
    assert check_explanation("Avoid it (CPIC level A, PMID:111).", "codeine", ev, {"codeine", "tramadol"}) == []
    bad = check_explanation("CPIC level B, see PMID:999; tramadol is safer.", "codeine", ev, {"codeine", "tramadol"})
    assert len(bad) == 3


@pytest.fixture(scope="module")
def driver():
    d = get_driver()
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


def test_llm_output_that_invents_a_citation_is_replaced(driver, monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda s, u: "Avoid it. PMID:99999999 proves this.")
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer"}, use_llm=True)
    ex = out["recommendations"][0]["explanation"]
    assert ex["source"] == "template" and ex["rejected_llm_output"]["problems"]


def test_faithful_llm_output_is_kept(driver, monkeypatch):
    monkeypatch.setattr(rec.client, "chat", lambda s, u: "The graph recommends caution for this phenotype.")
    out = rec.recommend(driver, {"CYP2C19": "Poor Metabolizer"}, use_llm=True)
    assert out["recommendations"][0]["explanation"]["source"] == "llm"
