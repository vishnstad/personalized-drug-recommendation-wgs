"""
Extract and normalize a single sample's genotypes across the target pharmacogenes (CYP2C19, CYP2D6)
from the 1000 Genomes raw regional VCFs.

Produces a combined, bgzipped, and tabix-indexed sample PGx VCF ready for PharmCAT.

Usage:
    python genomic/preprocess_sample.py <sample_id> [--output-dir data/processed/samples]
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from genomic.toolchain import BCFTOOLS_BIN, PHARMCAT_JAR, run_bash, to_posix_path as to_wsl_path

DEFAULT_CYP2C19_VCF = ROOT / "data" / "raw" / "1kGP_chr10_CYP2C19_region.vcf.gz"
DEFAULT_CYP2D6_VCF = ROOT / "data" / "raw" / "1kGP_chr22_CYP2D6_region.vcf.gz"
DEFAULT_OUT_DIR = ROOT / "data" / "processed" / "samples"


POSITIONS_VCF = PHARMCAT_JAR.parent / "pharmcat_positions_3.4.0.vcf.bgz"
GENE_COORDS = json.loads((ROOT / "genomic" / "gene_coordinates.json").read_text(encoding="utf-8"))
EXTRACTION_REGIONS = ",".join(g["extraction_region"] for g in GENE_COORDS["genes"].values())
# The 1000 Genomes VCF is joint-called over 3,202 samples and lists only sites where someone carries a variant;
# PharmCAT reads every absent CPIC-defining position as "unknown" (90/157 CYP2D6 positions here), which leaves
# most CYP2D6 calls ambiguous. Inside the downloaded regions an absent site means no carrier in the cohort, so it
# is filled as homozygous reference -- PharmCAT's own preprocessor offers the same option (--missing-to-ref).
FILL_MISSING_AS_REF = os.environ.get("FILL_MISSING_AS_REF", "1") != "0"


def extract_sample_vcf(
    sample_id: str,
    cyp2c19_raw_vcf: Path = DEFAULT_CYP2C19_VCF,
    cyp2d6_raw_vcf: Path = DEFAULT_CYP2D6_VCF,
    output_dir: Path = DEFAULT_OUT_DIR,
    bcftools_bin: str = BCFTOOLS_BIN,
    fill_missing_as_ref: bool = FILL_MISSING_AS_REF,
) -> Path:
    """Extract sample genotypes from both raw gene regions and produce a combined indexed VCF.
    With fill_missing_as_ref, PharmCAT positions inside the extracted regions that are absent from the
    cohort VCF are added as 0/0 (see FILL_MISSING_AS_REF above)."""
    sample_out_dir = output_dir / sample_id
    sample_out_dir.mkdir(parents=True, exist_ok=True)

    final_vcf = sample_out_dir / f"{sample_id}_pgx.vcf.gz"
    final_tbi = sample_out_dir / f"{sample_id}_pgx.vcf.gz.tbi"

    # Convert paths for WSL execution
    wsl_c19 = to_wsl_path(cyp2c19_raw_vcf)
    wsl_c2d6 = to_wsl_path(cyp2d6_raw_vcf)
    wsl_out = to_wsl_path(sample_out_dir)
    tmp_c19 = f"{wsl_out}/{sample_id}_c19_temp.vcf.gz"
    tmp_c2d6 = f"{wsl_out}/{sample_id}_c2d6_temp.vcf.gz"
    wsl_final = f"{wsl_out}/{sample_id}_pgx.vcf.gz"
    wsl_positions = to_wsl_path(POSITIONS_VCF)
    tmp_cat = f"{wsl_out}/{sample_id}_cat_temp.vcf.gz"
    tmp_pos = f"{wsl_out}/{sample_id}_pos_temp.vcf.gz"
    tmp_missing = f"{wsl_out}/{sample_id}_missing_temp.vcf.gz"
    tmp_missing_named = f"{wsl_out}/{sample_id}_missing_named_temp.vcf.gz"
    tmp_names = f"{wsl_out}/{sample_id}_names_temp.txt"
    if fill_missing_as_ref and not POSITIONS_VCF.exists():
        raise FileNotFoundError(f"{POSITIONS_VCF} not found (download it from the PharmCAT release) or set FILL_MISSING_AS_REF=0")

    bash_script = f"""
    set -euo pipefail
    BCF={bcftools_bin}

    # 1. Extract CYP2C19 (chr10)
    "$BCF" view -s "{sample_id}" -Oz -o "{tmp_c19}" "{wsl_c19}"
    "$BCF" index -t "{tmp_c19}"

    # 2. Extract CYP2D6 (chr22)
    "$BCF" view -s "{sample_id}" -Oz -o "{tmp_c2d6}" "{wsl_c2d6}"
    "$BCF" index -t "{tmp_c2d6}"

    # 3. Concatenate into single PGx VCF sorted by coordinates
    "$BCF" concat -a "{tmp_c19}" "{tmp_c2d6}" -Oz -o "{tmp_cat}"
    "$BCF" index -t "{tmp_cat}"

    # 4. Optionally add absent PharmCAT positions (inside the extracted regions only) as 0/0
    if [ "{int(fill_missing_as_ref)}" = "1" ]; then
        "$BCF" view -r "{EXTRACTION_REGIONS}" "{wsl_positions}" -Oz -o "{tmp_pos}"
        "$BCF" index -t "{tmp_pos}"
        "$BCF" isec -C -c all -w1 "{tmp_pos}" "{tmp_cat}" -Oz -o "{tmp_missing}"
        echo "{sample_id}" > "{tmp_names}"
        "$BCF" reheader -s "{tmp_names}" "{tmp_missing}" -o "{tmp_missing_named}"
        "$BCF" index -t "{tmp_missing_named}"
        "$BCF" concat -a "{tmp_cat}" "{tmp_missing_named}" -Ou | "$BCF" sort -Oz -o "{wsl_final}"
    else
        cp "{tmp_cat}" "{wsl_final}"
    fi
    "$BCF" index -f -t "{wsl_final}"

    # 5. Clean temporary files
    rm -f "{tmp_c19}"* "{tmp_c2d6}"* "{tmp_cat}"* "{tmp_pos}"* "{tmp_missing}"* "{tmp_missing_named}"* "{tmp_names}"
    """

    run_bash(bash_script, label="bcftools extraction")

    if not final_vcf.exists():
        raise FileNotFoundError(f"Failed to generate output VCF at {final_vcf}")

    return final_vcf


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_id", help="1000 Genomes Sample ID (e.g. HG00096, NA12878)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory")
    args = parser.parse_args()

    print(f"Extracting sample {args.sample_id}...")
    out_vcf = extract_sample_vcf(args.sample_id, output_dir=args.output_dir)
    print(f"Sample PGx VCF created successfully:\n  {out_vcf}\n  {out_vcf}.tbi")


if __name__ == "__main__":
    main()
