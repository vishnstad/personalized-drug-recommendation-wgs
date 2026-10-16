"""
Sanity checks for the retrieval layer against known, textbook CPIC gene-drug pairs.
Run with the Neo4j container up and the graph loaded: `pytest tests/test_retrieval.py -v`
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.queries import get_driver, recommendations_for_phenotype, evidence_for_gene_drug


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
