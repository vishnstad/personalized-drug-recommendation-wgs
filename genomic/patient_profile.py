"""
Layer 1 Orchestrator: Generate a complete, standardized patient pharmacogenomic profile from WGS.

Combines:
1. VCF sample extraction & normalization (genomic/preprocess_sample.py)
2. PharmCAT star-allele & metabolizer phenotype calling (genomic/call_phenotypes.py)
3. Structural variant & VUS annotations per Lauschke et al. 2023 (genomic/structural_annotator.py)
4. Sample demographic metadata from 1000 Genomes (pedigree / population / ancestry)

Usage:
    python genomic/patient_profile.py <sample_id> [--output-dir data/processed/samples]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from genomic.call_phenotypes import call_pharmcat
from genomic.preprocess_sample import DEFAULT_OUT_DIR, FILL_MISSING_AS_REF, extract_sample_vcf
from genomic.structural_annotator import annotate_gene_call

PEDIGREE_FILE = ROOT / "data" / "raw" / "20130606_g1k_3202_samples_ped_population.txt"


def load_pedigree_metadata(ped_path: Path = PEDIGREE_FILE) -> dict[str, dict[str, str]]:
    """Load sample metadata (ancestry, sex, population) from 1000 Genomes pedigree file."""
    if not ped_path.exists():
        return {}

    metadata = {}
    with open(ped_path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    header = lines[0].split()
    for line in lines[1:]:
        cols = line.split()
        if len(cols) >= 7:
            sid = cols[1]
            metadata[sid] = {
                "family_id": cols[0],
                "sample_id": sid,
                "father_id": cols[2] if cols[2] != "0" else None,
                "mother_id": cols[3] if cols[3] != "0" else None,
                "sex": "Male" if cols[4] == "1" else ("Female" if cols[4] == "2" else "Unknown"),
                "population": cols[5],
                "superpopulation": cols[6],
            }
    return metadata


def generate_patient_profile(
    sample_id: str,
    output_dir: Path = DEFAULT_OUT_DIR,
    force_reextract: bool = False,
) -> dict[str, Any]:
    """Generate the full patient profile from WGS data, running extraction and PharmCAT if needed."""
    sample_dir = output_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    vcf_path = sample_dir / f"{sample_id}_pgx.vcf.gz"

    # Step 1: VCF extraction if not already present
    if not vcf_path.exists() or force_reextract:
        print(f"[{sample_id}] Extracting genomic variants from 1000 Genomes panel...")
        vcf_path = extract_sample_vcf(sample_id, output_dir=output_dir)
    else:
        print(f"[{sample_id}] Using existing sample VCF at {vcf_path}")

    # Step 2: Run PharmCAT phenotype calling
    print(f"[{sample_id}] Calling star alleles and metabolizer phenotypes with PharmCAT...")
    pharmcat_res = call_pharmcat(vcf_path, sample_id=sample_id, output_dir=sample_dir)

    # Step 3: Annotate structural variants and VUS
    raw_warnings = pharmcat_res.get("warnings", [])
    annotated_genes = {}
    phenotypes_summary = {}
    diplotypes_summary = {}

    for gene, data in pharmcat_res["genes"].items():
        ann = annotate_gene_call(gene, data, raw_warnings)
        annotated_genes[gene] = ann
        phenotypes_summary[gene] = ann["phenotype"]
        diplotypes_summary[gene] = ann["diplotype"]

    # Step 4: Metadata enrichment
    ped_meta = load_pedigree_metadata().get(sample_id, {
        "sample_id": sample_id,
        "population": "Unknown",
        "superpopulation": "Unknown",
        "sex": "Unknown",
    })

    profile = {
        "sample_id": sample_id,
        "demographics": ped_meta,
        "phenotypes": phenotypes_summary,
        "diplotypes": diplotypes_summary,
        "genes": annotated_genes,
        "raw_vcf": str(vcf_path),
        "vcf_preprocessing": {
            "missing_positions_filled_as_reference": FILL_MISSING_AS_REF,
            "note": "PharmCAT positions absent from the 1000 Genomes cohort VCF (inside the extracted regions) "
                    "were treated as homozygous reference" if FILL_MISSING_AS_REF else
                    "absent PharmCAT positions left as missing (calls may be ambiguous)",
        },
        "source": "PharmCAT 3.4.0 (CPIC-compliant)",
    }

    # Save patient profile JSON
    profile_path = sample_dir / f"{sample_id}_patient_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"[{sample_id}] Patient profile saved to {profile_path}")

    return profile


def load_or_generate_profile(sample_id: str, output_dir: Path = DEFAULT_OUT_DIR, force: bool = False) -> dict[str, Any]:
    """Return the saved profile JSON if this sample was already processed, else run Layer 1."""
    profile_path = output_dir / sample_id / f"{sample_id}_patient_profile.json"
    if profile_path.exists() and not force:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    return generate_patient_profile(sample_id, output_dir=output_dir, force_reextract=force)


def get_patient_phenotypes(sample_id: str, output_dir: Path = DEFAULT_OUT_DIR) -> dict[str, str]:
    """Convenience bridge function returning the exact {gene: phenotype} dictionary needed by Layer 2/3."""
    profile_path = output_dir / sample_id / f"{sample_id}_patient_profile.json"
    if profile_path.exists():
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return data.get("phenotypes", {})
    profile = generate_patient_profile(sample_id, output_dir=output_dir)
    return profile.get("phenotypes", {})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_id", help="Sample ID (e.g. HG00096, HG00097, NA12878)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR, help="Base output directory")
    parser.add_argument("--force", action="store_true", help="Force re-extraction of VCF")
    args = parser.parse_args()

    profile = generate_patient_profile(args.sample_id, output_dir=args.output_dir, force_reextract=args.force)
    print("\n--- Summary Patient Profile ---")
    print(f"Sample: {profile['sample_id']} ({profile['demographics']['superpopulation']} - {profile['demographics']['population']})")
    print("Phenotypes:")
    for gene, pheno in profile["phenotypes"].items():
        dip = profile["diplotypes"].get(gene, "")
        print(f"  {gene}: {pheno} (diplotype {dip})")


if __name__ == "__main__":
    main()
