#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

BCFTOOLS=./.tools/bin/bcftools
URL='https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina.chr22.filtered.SNV_INDEL_SV_phased_panel.vcf.gz'
OUT=data/raw/1kGP_chr22_CYP2D6_region.vcf.gz

echo "Querying region chr22:42121499-42135810 (CYP2D6 + 5kb padding) remotely..."
time "$BCFTOOLS" view -r chr22:42121499-42135810 -Oz -o "$OUT" "$URL"
"$BCFTOOLS" index -t "$OUT"
ls -lh "$OUT" "$OUT.tbi"
