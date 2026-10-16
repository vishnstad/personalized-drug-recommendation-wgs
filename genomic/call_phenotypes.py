"""
Run PharmCAT on a patient's PGx VCF to call star-allele diplotypes and CPIC phenotypes
for CYP2C19 and CYP2D6.

Parses PharmCAT's output files (.report.tsv and .phenotype.json) into structured Python data.

Usage:
    python genomic/call_phenotypes.py <path_to_sample_pgx.vcf.gz> [--sample-id HG00096] [--output-dir data/processed/samples]
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
PHARMCAT_JAR = ROOT / "tools" / "pharmcat" / "pharmcat-3.4.0-all.jar"
DEFAULT_JAVA = "/home/arulyashwanth/miniforge3/envs/bio/bin/java"


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
        raise RuntimeError(f"PharmCAT command failed (code {result.returncode}):\n{clean_cmd}\n\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}")


def parse_report_tsv(tsv_path: Path) -> dict[str, dict[str, Any]]:
    """Parse PharmCAT's .report.tsv file into structured per-gene calls."""
    if not tsv_path.exists():
        raise FileNotFoundError(f"PharmCAT report TSV not found at {tsv_path}")

    genes_data: dict[str, dict[str, Any]] = {}
    with open(tsv_path, "r", encoding="utf-8") as f:
        # PharmCAT headers start after tool title
        lines = [line.strip() for line in f if line.strip()]

    header_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("Gene\t"):
            header_idx = i
            break

    if header_idx == -1:
        raise ValueError(f"Could not find TSV header row in {tsv_path}")

    reader = csv.DictReader(lines[header_idx:], delimiter="\t")
    for row in reader:
        gene = row["Gene"]
        act_score = None
        raw_score = row.get("Activity Score", "").strip()
        if raw_score and raw_score.lower() not in ("n/a", "no result", ""):
            try:
                act_score = float(raw_score)
            except ValueError:
                act_score = raw_score

        genes_data[gene] = {
            "gene": gene,
            "diplotype": row.get("Source Diplotype", "").strip(),
            "phenotype": row.get("Phenotype", "").strip(),
            "activity_score": act_score,
            "haplotype_1": {
                "name": row.get("Haplotype 1", "").strip(),
                "function": row.get("Haplotype 1 Function", "").strip(),
                "activity": row.get("Haplotype 1 Activity Value", "").strip() or None,
            },
            "haplotype_2": {
                "name": row.get("Haplotype 2", "").strip(),
                "function": row.get("Haplotype 2 Function", "").strip(),
                "activity": row.get("Haplotype 2 Activity Value", "").strip() or None,
            },
            "match_score": int(row.get("Match Score", 0)) if row.get("Match Score", "").isdigit() else None,
            "missing_positions": row.get("Missing positions", "").strip().lower() == "yes",
            "lookup_phenotype": row.get("Recommendation Lookup Phenotype", "").strip() or row.get("Phenotype", "").strip(),
        }

    return genes_data


def parse_match_warnings(warnings_path: Path) -> list[str]:
    """Parse PharmCAT match warnings if present."""
    if not warnings_path.exists():
        return []
    lines = warnings_path.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip()]


def call_pharmcat(
    vcf_path: Path,
    sample_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    genes: tuple[str, ...] = ("CYP2C19", "CYP2D6"),
    java_bin: str = DEFAULT_JAVA,
) -> dict[str, Any]:
    """Execute PharmCAT jar on a sample VCF and return parsed calls."""
    vcf_path = vcf_path.resolve()
    if not vcf_path.exists():
        raise FileNotFoundError(f"Input VCF not found: {vcf_path}")

    sid = sample_id or vcf_path.stem.replace("_pgx", "").replace(".vcf", "")
    out_dir = (output_dir or vcf_path.parent) / f"{sid}_pharmcat_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    wsl_vcf = to_wsl_path(vcf_path)
    wsl_out = to_wsl_path(out_dir)
    wsl_jar = to_wsl_path(PHARMCAT_JAR)
    genes_arg = ",".join(genes)

    bash_cmd = f"""
    set -euo pipefail
    "{java_bin}" -jar "{wsl_jar}" \
        -vcf "{wsl_vcf}" \
        -g "{genes_arg}" \
        -research cyp2d6 \
        -o "{wsl_out}" \
        -reporterJson \
        -bf "{sid}"
    """

    run_cmd(bash_cmd)

    tsv_file = out_dir / f"{sid}.report.tsv"
    warnings_file = out_dir / f"{sid}.match_warnings.txt"

    gene_calls = parse_report_tsv(tsv_file)
    warnings = parse_match_warnings(warnings_file)

    return {
        "sample_id": sid,
        "input_vcf": str(vcf_path),
        "genes": gene_calls,
        "warnings": warnings,
        "output_dir": str(out_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vcf_path", type=Path, help="Path to sample PGx VCF (.vcf.gz)")
    parser.add_argument("--sample-id", help="Sample ID (defaults to VCF stem)")
    parser.add_argument("--output-dir", type=Path, help="Output directory for PharmCAT results")
    args = parser.parse_args()

    print(f"Running PharmCAT on {args.vcf_path}...")
    result = call_pharmcat(args.vcf_path, sample_id=args.sample_id, output_dir=args.output_dir)
    print("\nPharmCAT Results:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
