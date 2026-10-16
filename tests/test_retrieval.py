"""
Sanity checks for the retrieval layer against known, textbook CPIC gene-drug pairs.
Run with the Neo4j container up and the graph loaded: `pytest tests/test_retrieval.py -v`
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.queries import (
    _lookup_matches, evidence_for_gene_drug, get_driver, recommendations_for_patient, recommendations_for_phenotype,
)


@pytest.fixture(scope="module")
def driver():
    d = get_driver()
    try:
        d.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j database is not reachable at localhost:7687: {e}")
    yield d
    d.close()


def test_cyp2d6_poor_metabolizer_avoids_codeine(driver):
    rows = recommendations_for_phenotype(driver, "CYP2D6", "Poor Metabolizer")
    codeine = [r for r in rows if r["drug"] == "codeine"]
    assert codeine, "expected a codeine recommendation for CYP2D6 Poor Metabolizer"
    assert "avoid" in codeine[0]["recommendation"].lower()
    assert codeine[0]["cpic_level"] == "A"


def test_cyp2c19_poor_metabolizer_flags_clopidogrel(driver):
    rows = recommendations_for_phenotype(driver, "CYP2C19", "Poor Metabolizer")
    clopidogrel = [r for r in rows if r["drug"] == "clopidogrel"]
    assert clopidogrel, "expected a clopidogrel recommendation for CYP2C19 Poor Metabolizer"
    assert clopidogrel[0]["cpic_level"] == "A"


def test_hla_b_5701_positive_flags_abacavir(driver):
    rows = recommendations_for_phenotype(driver, "HLA-B", "HLA-B*57:01 positive")
    abacavir = [r for r in rows if r["drug"] == "abacavir"]
    assert abacavir, "expected an abacavir recommendation for HLA-B*57:01 positive"
    assert "abacavir" in abacavir[0]["recommendation"].lower()


def test_evidence_level_present_for_graded_pair(driver):
    evidence = evidence_for_gene_drug(driver, "TPMT", "azathioprine")
    assert evidence is not None
    assert evidence["cpic_level"] in {"A", "B", "C", "D"}


def test_lookup_key_matching():
    assert _lookup_matches("1.0", 1.0) and not _lookup_matches("0.25", 1.0)
    assert _lookup_matches("≥3.75", 4.0) and not _lookup_matches("≥3.75", 3.0)
    assert _lookup_matches("Poor Metabolizer", 1.0)  # non-numeric key adds no constraint


def test_multi_gene_rows_match_the_full_patient_condition(driver):
    # Regression: amitriptyline is keyed on CYP2C19 AND CYP2D6. Per-gene retrieval returned rows for
    # every CYP2D6 phenotype; patient-level retrieval must only return the patient's actual pair.
    patient = {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Normal Metabolizer"}
    rows = [r for r in recommendations_for_patient(driver, patient) if r["drug"] == "amitriptyline"]
    assert rows, "expected an amitriptyline recommendation"
    assert all(r["condition"] == patient for r in rows)
    assert len({r["recommendation"] for r in rows}) == 1


def test_untested_gene_counts_as_no_result(driver):
    rows = recommendations_for_patient(driver, {"CYP2C19": "Poor Metabolizer"})
    for r in rows:
        assert all(r["condition"].get(g, "No Result") in ("Poor Metabolizer", "No Result") for g in r["genes"])
        assert r["condition"]["CYP2C19"] == "Poor Metabolizer"


def test_activity_score_selects_the_matching_row(driver):
    # CPIC splits CYP2D6 Intermediate Metabolizer tamoxifen advice by activity score (1.0 -> Optional)
    rows = recommendations_for_patient(driver, {"CYP2D6": "Intermediate Metabolizer"}, {"CYP2D6": 1.0})
    tam = [r for r in rows if r["drug"] == "tamoxifen"]
    assert tam and {r["classification"] for r in tam} == {"Optional"}
    assert all(r["lookupkey"].get("CYP2D6") == "1.0" for r in tam)


def test_populations_are_kept_apart(driver):
    rows = recommendations_for_patient(driver, {"CYP2C19": "Poor Metabolizer", "CYP2D6": "Normal Metabolizer"})
    clop = [r for r in rows if r["drug"] == "clopidogrel"]
    assert len({r["population"] for r in clop}) == len(clop) > 1
