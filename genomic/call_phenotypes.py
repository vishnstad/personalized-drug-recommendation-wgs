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
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from genomic.toolchain import JAVA_BIN, PHARMCAT_JAR, run_bash, to_posix_path as to_wsl_path


def parse_report_tsv(tsv_path: Path) -> dict[str, dict[str, Any]]:
    """Parse PharmCAT's .report.tsv file into structured per-gene calls."""
    if not tsv_path.exists():
        raise FileNotFoundError(f"PharmCAT report TSV not found at {tsv_path}")

    genes_data: dict[str, dict[str, Any]] = {}
    with open(tsv_path, "r", encoding="utf-8") as f:
        # Strip only the line ending: trailing empty columns are tab-separated and must be kept.
        lines = [line.rstrip("\r\n") for line in f if line.strip()]

    header_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("Gene\t"):
            header_idx = i
            break

    if header_idx == -1:
        raise ValueError(f"Could not find TSV header row in {tsv_path}")

    reader = csv.DictReader(lines[header_idx:], delimiter="\t", restval="")
    for raw in reader:
        row = {k: (v or "").strip() for k, v in raw.items() if k}
        gene = row["Gene"]
        diplotypes = [d.strip() for d in row.get("Source Diplotype", "").split(" OR ") if d.strip()]
        phenotypes = [p.strip() for p in row.get("Phenotype", "").split(" / ")]
        scores = [s.strip() for s in row.get("Activity Score", "").split(" / ")]

        # PharmCAT reports an ambiguous call (several equally-scored diplotypes, e.g. when the VCF lacks
        # defining positions) as "A OR B OR ..." with one phenotype/score per candidate, and then leaves
        # "Recommendation Lookup Phenotype" empty. If every candidate implies the same phenotype we can still
        # use it; otherwise the call is CPIC "Indeterminate" -- never a guess.
        candidates = sorted({p for p in phenotypes if p})
        ambiguous = len(diplotypes) > 1
        phenotype = candidates[0] if len(candidates) == 1 else ("Indeterminate" if candidates else "")
        numeric = {s for s in scores if s and s.lower() not in ("n/a", "no result")}
        act_score = None
        if len(numeric) == 1 and (not ambiguous or len(scores) == len(diplotypes)) and "" not in scores:
            try:
                act_score = float(numeric.pop())
            except ValueError:
                pass

        genes_data[gene] = {
            "gene": gene,
            "diplotype": diplotypes[0] if len(diplotypes) == 1 else (f"ambiguous ({len(diplotypes)} candidates)" if diplotypes else ""),
            "phenotype": phenotype,
            "ambiguous_call": ambiguous and len(candidates) > 1,
            "diplotype_candidates": diplotypes if ambiguous else [],
            "phenotype_candidates": {p: phenotypes.count(p) for p in candidates} if ambiguous else {},
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


def reference_alleles(positions_vcf: Path) -> dict[tuple[str, int], str]:
    """(chrom, pos) -> REF from PharmCAT's positions VCF (bgzip is gzip-compatible)."""
    import gzip

    refs = {}
    if positions_vcf.exists():
        with gzip.open(positions_vcf, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    chrom, pos, _id, ref = line.split("	", 4)[:4]
                    refs[(chrom, int(pos))] = ref
    return refs


def parse_match_json(match_path: Path, refs: Optional[dict] = None) -> dict[str, dict[str, Any]]:
    """What PharmCAT's allele matcher actually looked at, per gene: the CPIC-defining positions examined,
    which of them were missing, and the non-reference genotypes the sample carries there."""
    if not match_path.exists():
        return {}
    refs = refs if refs is not None else reference_alleles(PHARMCAT_JAR.parent / "pharmcat_positions_3.4.0.vcf.bgz")
    out = {}
    for g in json.loads(match_path.read_text(encoding="utf-8")).get("results", []):
        variants = g.get("variants") or []
        carried = []
        for v in variants:
            alleles = (v.get("vcfCall") or "").replace("|", "/").split("/")
            ref = refs.get((g.get("chromosome"), v.get("position")))
            if len(alleles) != 2 or "." in alleles or ref is None:
                continue
            n_alt = sum(a != ref for a in alleles)
            if n_alt:
                carried.append({"rsid": v.get("rsid"), "position": v.get("position"), "ref": ref,
                                "genotype": v["vcfCall"], "zygosity": "homozygous" if n_alt == 2 else "heterozygous"})
        out[g["gene"]] = {
            "chromosome": g.get("chromosome"),
            "positions_examined": len(variants),
            "missing_positions": len((g.get("matchData") or {}).get("missingPositions") or []),
            "variants_carried": carried,
        }
    return out


def call_pharmcat(
    vcf_path: Path,
    sample_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    genes: tuple[str, ...] = ("CYP2C19", "CYP2D6"),
    java_bin: str = JAVA_BIN,
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

    run_bash(bash_cmd, label="PharmCAT")

    tsv_file = out_dir / f"{sid}.report.tsv"
    warnings_file = out_dir / f"{sid}.match_warnings.txt"

    gene_calls = parse_report_tsv(tsv_file)
    warnings = parse_match_warnings(warnings_file)
    for gene, evidence in parse_match_json(out_dir / f"{sid}.match.json").items():
        if gene in gene_calls:
            gene_calls[gene]["matcher_evidence"] = evidence

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
