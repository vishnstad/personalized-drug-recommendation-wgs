#!/bin/bash
set -eu
cd "$(dirname "$0")/.."

BCFTOOLS=./.tools/bin/bcftools

for GENE_FILE in "CYP2C19:data/raw/1kGP_chr10_CYP2C19_region.vcf.gz" "CYP2D6:data/raw/1kGP_chr22_CYP2D6_region.vcf.gz"; do
  GENE="${GENE_FILE%%:*}"
  FILE="${GENE_FILE#*:}"
  echo "################################################################"
  echo "### $GENE  ($FILE)"
  echo "################################################################"

  echo; echo "--- Header (last 15 lines, incl. #CHROM line) ---"
  "$BCFTOOLS" view -h "$FILE" | tail -15

  echo; echo "--- Contig / chromosome info in header ---"
  "$BCFTOOLS" view -h "$FILE" | grep "^##contig" | head -5

  echo; echo "--- Number of samples ---"
  "$BCFTOOLS" query -l "$FILE" | wc -l

  echo; echo "--- First 5 sample names ---"
  "$BCFTOOLS" query -l "$FILE" | head -5

  echo; echo "--- Number of variants ---"
  "$BCFTOOLS" view -H "$FILE" | wc -l

  echo; echo "--- First 5 variant records (CHROM POS ID REF ALT) ---"
  "$BCFTOOLS" query -f '%CHROM\t%POS\t%ID\t%REF\t%ALT\n' "$FILE" | head -5

  echo
done
