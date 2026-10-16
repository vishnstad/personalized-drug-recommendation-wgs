"""
Tests for Layer 1: Genomic Processing and PharmCAT star-allele / phenotype calling.
"""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from genomic.preprocess_sample import extract_sample_vcf
from genomic.call_phenotypes import call_pharmcat
from genomic.structural_annotator import evaluate_structural_confidence
from genomic.patient_profile import (
    generate_patient_profile,
    get_patient_phenotypes,
    load_pedigree_metadata,
)

VALID_PHENOTYPES = {
    "Poor Metabolizer",
    "Intermediate Metabolizer",
    "Normal Metabolizer",
    "Rapid Metabolizer",
    "Ultrarapid Metabolizer",
    "Likely Intermediate Metabolizer",
    "Likely Poor Metabolizer",
    "Indeterminate",
}


def test_pedigree_metadata_parsing():
    meta = load_pedigree_metadata()
    assert "HG00096" in meta
    hg96 = meta["HG00096"]
    assert hg96["population"] == "GBR"
    assert hg96["superpopulation"] == "EUR"
    assert hg96["sex"] == "Male"


def test_invalid_sample_extraction_raises_error(tmp_path):
    with pytest.raises(RuntimeError):
        extract_sample_vcf("INVALID_SAMPLE_99999", output_dir=tmp_path)


def test_sample_extraction_produces_indexed_vcf(tmp_path):
    vcf = extract_sample_vcf("HG00096", output_dir=tmp_path)
    assert vcf.exists()
    assert Path(f"{vcf}.tbi").exists()
    assert vcf.stat().st_size > 0


def test_pharmcat_calling_on_sample(tmp_path):
    sample_vcf = ROOT / "data" / "processed" / "samples" / "HG00096" / "HG00096_pgx.vcf.gz"
    if not sample_vcf.exists():
        sample_vcf = extract_sample_vcf("HG00096", output_dir=tmp_path)

    res = call_pharmcat(sample_vcf, sample_id="HG00096", output_dir=tmp_path)
    assert "CYP2C19" in res["genes"]
    assert "CYP2D6" in res["genes"]

    c19 = res["genes"]["CYP2C19"]
    assert c19["phenotype"] in VALID_PHENOTYPES
    assert c19["diplotype"] == "*1/*2"

    c2d6 = res["genes"]["CYP2D6"]
    assert c2d6["phenotype"] in VALID_PHENOTYPES
    assert c2d6["diplotype"] == "*1/*4"
    assert c2d6["activity_score"] == 1.0


def test_structural_confidence_evaluation():
    call_mock = {
        "gene": "CYP2D6",
        "diplotype": "*1/*4",
        "phenotype": "Intermediate Metabolizer",
        "missing_positions": True,
    }
    eval_res = evaluate_structural_confidence("CYP2D6", call_mock, ["Duplicate entry found"])
    assert "confidence_level" in eval_res
    assert eval_res["requires_orthogonal_confirmation"] is True
    assert any("short-read" in s.lower() for s in eval_res["structural_limitations"])


def test_patient_profile_generation(tmp_path):
    profile = generate_patient_profile("HG00096", output_dir=tmp_path)
    assert profile["sample_id"] == "HG00096"
    assert profile["demographics"]["superpopulation"] == "EUR"
    assert "CYP2C19" in profile["phenotypes"]
    assert "CYP2D6" in profile["phenotypes"]

    # Check bridge function
    phenos = get_patient_phenotypes("HG00096", output_dir=tmp_path)
    assert phenos["CYP2C19"] == "Intermediate Metabolizer"
    assert phenos["CYP2D6"] == "Intermediate Metabolizer"
