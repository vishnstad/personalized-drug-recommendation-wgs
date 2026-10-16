"""
Unit tests for Layer 3: Hybrid Retrieval, RCG4MR Plausibility Filter, and End-to-End Grounded Recommender.
"""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import client
from llm.plausibility_validator import rule_based_plausibility_check, validate_claim_plausibility
from retrieval.hybrid_retriever import HybridRetriever
from llm.recommend import build_candidates, classify_action, rank, template_explanation


def test_guideline_lookup_is_exact_drug_only():
    from retrieval.hybrid_retriever import guideline_text_for_drug
    assert "codeine" in guideline_text_for_drug("Codeine").lower()
    assert guideline_text_for_drug("abacavir") == ""  # no curated summary -> nothing, not a neighbour's text


def test_hybrid_retriever_initialization_and_query(tmp_path):
    pytest.importorskip("chromadb")
    retriever = HybridRetriever(chroma_path=tmp_path / "chroma_test")
    assert retriever.collection.count() > 0

    results = retriever.retrieve_guideline_text("CYP2D6 codeine", top_k=2)
    assert len(results) > 0
    top_doc = results[0]
    assert "codeine" in top_doc["text"].lower()
    assert top_doc["gene"] == "CYP2D6"
    assert "PMID:22378137" in top_doc["citations"] or len(top_doc["citations"]) > 0


def test_rcg4mr_prodrug_bioactivation_filter():
    # Prodrug: codeine in CYP2D6 Poor Metabolizer cannot be standard
    ok, reason = rule_based_plausibility_check("CYP2D6", "Poor Metabolizer", "codeine", "standard")
    assert ok is False
    assert "prodrug" in reason.lower()

    # Prodrug: codeine in CYP2D6 Poor Metabolizer with 'avoid' is plausible
    ok, reason = rule_based_plausibility_check("CYP2D6", "Poor Metabolizer", "codeine", "avoid")
    assert ok is True

    # Prodrug: clopidogrel in CYP2C19 Poor Metabolizer cannot be standard
    ok, reason = rule_based_plausibility_check("CYP2C19", "Poor Metabolizer", "clopidogrel", "standard")
    assert ok is False


def test_rcg4mr_active_drug_clearance_filter():
    # Active drug: voriconazole in CYP2C19 Poor Metabolizer cannot be standard
    ok, reason = rule_based_plausibility_check("CYP2C19", "Poor Metabolizer", "voriconazole", "standard")
    assert ok is False
    assert "accumulation" in reason.lower()

    # Dose adjustment or alternative is plausible
    ok, reason = rule_based_plausibility_check("CYP2C19", "Poor Metabolizer", "voriconazole", "adjust")
    assert ok is True


def test_client_headers_configuration(monkeypatch):
    monkeypatch.setattr(client, "API_KEY", "test-key-123")
    headers = client.get_headers()
    assert headers.get("Authorization") == "Bearer test-key-123"

    monkeypatch.setattr(client, "API_KEY", "")
    headers = client.get_headers()
    assert "Authorization" not in headers


def test_layer1_to_layer3_data_flow():
    # Simulate patient profile produced by Layer 1 for HG00096
    mock_patient_profile = {
        "sample_id": "HG00096",
        "phenotypes": {
            "CYP2C19": "Intermediate Metabolizer",
            "CYP2D6": "Intermediate Metabolizer",
        },
    }

    # Mock retrieved recommendations
    mock_cyp2c19_rows = [
        {
            "drug": "clopidogrel",
            "drug_rxnorm_id": "RxNorm:32968",
            "recommendation": "Consider alternative antiplatelet agent (e.g. prasugrel, ticagrelor)",
            "classification": "Moderate",
            "evidence": {"cpic_level": "A", "citations": ["PMID:23698643"]},
            "guideline": "CYP2C19 and Clopidogrel",
        }
    ]
    mock_cyp2d6_rows = [
        {
            "drug": "codeine",
            "drug_rxnorm_id": "RxNorm:2670",
            "recommendation": "Use recommended starting dose or monitor closely for reduced efficacy",
            "classification": "Moderate",
            "evidence": {"cpic_level": "A", "citations": ["PMID:22378137"]},
            "guideline": "CYP2D6 and Opioids",
        }
    ]

    for r, gene in ((mock_cyp2c19_rows[0], "CYP2C19"), (mock_cyp2d6_rows[0], "CYP2D6")):
        r["condition"] = {gene: mock_patient_profile["phenotypes"][gene]}
        r["genes"] = [gene]
    cands = build_candidates(mock_cyp2c19_rows + mock_cyp2d6_rows)
    ranked = rank(cands)
    assert len(ranked) == 2

    # Check template explanation formatting
    clop_cand = cands["clopidogrel"]
    expl = template_explanation(clop_cand)
    assert "CYP2C19 Intermediate Metabolizer" in expl
    assert "PMID:23698643" in expl
