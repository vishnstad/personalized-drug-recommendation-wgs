#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

BCFTOOLS=./.tools/bin/bcftools
URL='https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina.chr10.filtered.SNV_INDEL_SV_phased_panel.vcf.gz'
OUT=data/raw/1kGP_chr10_CYP2C19_region.vcf.gz

echo "Querying region chr10:94757681-94860547 (CYP2C19 + 5kb padding) remotely..."
time "$BCFTOOLS" view -r chr10:94757681-94860547 -Oz -o "$OUT" "$URL"
"$BCFTOOLS" index -t "$OUT"
ls -lh "$OUT" "$OUT.tbi"
