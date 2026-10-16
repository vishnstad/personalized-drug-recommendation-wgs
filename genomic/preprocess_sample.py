"""
Extract and normalize a single sample's genotypes across the target pharmacogenes (CYP2C19, CYP2D6)
from the 1000 Genomes raw regional VCFs.

Produces a combined, bgzipped, and tabix-indexed sample PGx VCF ready for PharmCAT.

Usage:
    python genomic/preprocess_sample.py <sample_id> [--output-dir data/processed/samples]
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CYP2C19_VCF = ROOT / "data" / "raw" / "1kGP_chr10_CYP2C19_region.vcf.gz"
DEFAULT_CYP2D6_VCF = ROOT / "data" / "raw" / "1kGP_chr22_CYP2D6_region.vcf.gz"
DEFAULT_OUT_DIR = ROOT / "data" / "processed" / "samples"


DEFAULT_BCFTOOLS = "/home/arulyashwanth/miniforge3/envs/bio/bin/bcftools"


def to_wsl_path(path: Path) -> str:
    """Convert a Windows or Linux Path to WSL2 POSIX path."""
    resolved = path.resolve()
    p = str(resolved).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        drive = p[0].lower()
        return f"/mnt/{drive}{p[2:]}"
    return p


def run_cmd(cmd: str) -> None:
    """Run bash command either natively (if on Linux/WSL) or inside WSL2 Ubuntu (if on Windows) via stdin."""
    clean_cmd = cmd.replace("\r\n", "\n").replace("\r", "\n")
    if sys.platform == "win32":
        full_cmd = ["wsl", "-d", "Ubuntu", "--", "bash"]
    else:
        full_cmd = ["bash"]

    result = subprocess.run(full_cmd, input=clean_cmd.encode("utf-8"), capture_output=True)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (code {result.returncode}):\n{clean_cmd}\n\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}")


def extract_sample_vcf(
    sample_id: str,
    cyp2c19_raw_vcf: Path = DEFAULT_CYP2C19_VCF,
    cyp2d6_raw_vcf: Path = DEFAULT_CYP2D6_VCF,
    output_dir: Path = DEFAULT_OUT_DIR,
    bcftools_bin: str = DEFAULT_BCFTOOLS,
) -> Path:
    """Extract sample genotypes from both raw gene regions and produce a combined indexed VCF."""
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
    "$BCF" concat -a "{tmp_c19}" "{tmp_c2d6}" -Oz -o "{wsl_final}"
    "$BCF" index -t "{wsl_final}"

    # 4. Clean temporary slices
    rm -f "{tmp_c19}"* "{tmp_c2d6}"*
    """

    run_cmd(bash_script)

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
