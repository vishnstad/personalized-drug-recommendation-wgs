#!/bin/bash
set -eu
cd "$(dirname "$0")/.."

BCFTOOLS=./.tools/bin/bcftools

echo "--- CYP2C19: exact gene boundary chr10:94762681-94855547 ---"
"$BCFTOOLS" view -r chr10:94762681-94855547 -Oz -o data/processed/cyp2c19.vcf.gz data/raw/1kGP_chr10_CYP2C19_region.vcf.gz
"$BCFTOOLS" index -t data/processed/cyp2c19.vcf.gz

echo "--- CYP2D6: exact gene boundary chr22:42126499-42130810 ---"
"$BCFTOOLS" view -r chr22:42126499-42130810 -Oz -o data/processed/cyp2d6.vcf.gz data/raw/1kGP_chr22_CYP2D6_region.vcf.gz
"$BCFTOOLS" index -t data/processed/cyp2d6.vcf.gz

echo
echo "--- Resulting files ---"
ls -lh data/processed/

echo
echo "--- Variant counts ---"
echo -n "CYP2C19: "; "$BCFTOOLS" view -H data/processed/cyp2c19.vcf.gz | wc -l
echo -n "CYP2D6:  "; "$BCFTOOLS" view -H data/processed/cyp2d6.vcf.gz | wc -l
