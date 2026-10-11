#!/usr/bin/env bash
# Download the 1000 Genomes (NYGC 30x, 3,202 samples) sample/population table.
set -euo pipefail
cd "$(dirname "$0")/.."
curl -fsSL -o data/raw/20130606_g1k_3202_samples_ped_population.txt \
  "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/20130606_g1k_3202_samples_ped_population.txt"
