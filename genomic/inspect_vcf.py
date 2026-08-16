"""
Read a (possibly bgzipped, tabix-indexed) VCF/BCF file with cyvcf2 and print,
for a limited number of variants, the chromosome, position, REF/ALT alleles,
and each sample's genotype.

Usage:
    python inspect_vcf.py <path_to_vcf.gz> [--max-variants N] [--max-samples N]
"""

import argparse

from cyvcf2 import VCF


def inspect(vcf_path: str, max_variants: int, max_samples: int) -> None:
    vcf = VCF(vcf_path)

    samples = vcf.samples
    print(f"File: {vcf_path}")
    print(f"Total samples in file: {len(samples)}")
    shown_samples = samples[:max_samples]
    print(f"Showing genotypes for first {len(shown_samples)} samples: {shown_samples}")
    print("-" * 80)

    for i, variant in enumerate(vcf):
        if i >= max_variants:
            print(f"... stopped after {max_variants} variants ...")
            break

        print(f"CHROM={variant.CHROM}  POS={variant.POS}  REF={variant.REF}  ALT={variant.ALT}")

        genotypes = variant.genotypes  # list of [allele1, allele2, phased] per sample
        for sample_name, gt in zip(shown_samples, genotypes[: len(shown_samples)]):
            allele1, allele2, phased = gt
            sep = "|" if phased else "/"
            print(f"    {sample_name}: {allele1}{sep}{allele2}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vcf_path", help="Path to .vcf.gz / .bcf file")
    parser.add_argument("--max-variants", type=int, default=5, help="Number of variants to print")
    parser.add_argument("--max-samples", type=int, default=3, help="Number of sample genotypes to print per variant")
    args = parser.parse_args()

    inspect(args.vcf_path, args.max_variants, args.max_samples)
