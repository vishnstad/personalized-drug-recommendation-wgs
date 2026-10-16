# Genomic Setup — Milestone 1

This document explains, in plain language, what we did to get a small, real,
reproducible genomic dataset ready for the pharmacogenomics part of this
project. It assumes no prior bioinformatics background.

## 1. What is WGS data, and what did we download?

**WGS (Whole Genome Sequencing)** means reading essentially all 3+ billion
letters (A/C/G/T) of a person's DNA, not just a few genes. Sequencing
machines don't directly output "the genome" — they output millions of short,
overlapping snippets of DNA that then get aligned against a **reference
genome** (see GRCh38 below) and compared to find where each individual
differs from that reference. Those differences are called **variants**.

We used the **1000 Genomes Project** high-coverage dataset: 3,202 people from
populations around the world, each sequenced at **30x coverage** (each base
of their genome was read about 30 times on average, which is considered
high-quality/high-confidence sequencing) by the New York Genome Center
(NYGC), aligned to GRCh38. This is one of the most widely used, freely
available, ethically-consented public genomic resources in the field — it's
exactly what the project plan calls for.

We did **not** download raw sequencing reads (that would mean re-doing
alignment and variant calling ourselves, which is a huge, separate
undertaking). Instead we used the **already-processed, already-variant-called
VCF files** that the 1000 Genomes Project publishes — this is the standard
starting point for downstream analysis like ours.

## 2. What is a VCF?

A **VCF (Variant Call Format)** file is a plain-text (usually gzip-compressed)
table that lists every genetic variant found in a set of samples, one row per
variant. Roughly:

```
#CHROM  POS       ID              REF  ALT  ...  FORMAT  SAMPLE1  SAMPLE2  ...
chr10   94757767  10:94757767:A:G A    G    ...  GT       0|0      1|0     ...
```

- **CHROM / POS**: which chromosome, and which position on it.
- **REF / ALT**: the reference-genome base(s) vs. the alternative (variant)
  base(s) seen in at least one sample.
- **FORMAT / per-sample columns**: for each sample, its **genotype (GT)** —
  e.g. `0|0` means "reference on both copies," `0|1` means "one reference,
  one variant copy," `1|1` means "variant on both copies." The `|` means the
  two copies are *phased* (we know which chromosome — maternal/paternal —
  each allele came from), which matters a lot for pharmacogenomics because
  some drug-response haplotypes depend on which variants sit on the *same*
  chromosome copy.

## 3. Why this dataset?

The project plan specifically calls for 1000 Genomes 30x WGS, GRCh38. This
dataset is:
- **Real, not synthetic** — required by the project plan.
- **Public and well documented**, so our results are reproducible and the
  data provenance can be cited in the final report/thesis.
- **Large and diverse** (3,202 individuals across many populations), which
  matters for pharmacogenomics since drug-response allele frequencies vary
  significantly between populations.
- **Already variant-called and phased**, so we can start directly at the
  "VCF" stage of our pipeline instead of building a sequencing pipeline
  first (out of scope for this project).

## 4. Why CYP2C19 and CYP2D6?

Both are **pharmacogenes** — genes whose variants are well-established to
change how a person metabolizes many common drugs (CYP2C19 affects drugs
like clopidogrel and some antidepressants/PPIs; CYP2D6 affects a large
fraction of all prescribed drugs, including many antidepressants, opioids,
and beta-blockers). They are:
- Two of the most clinically actionable pharmacogenes (both have CPIC/FDA
  drug-dosing guidelines).
- Directly supported by **PharmCAT** (the phenotype-calling tool named in the
  project plan), which we will integrate in a later milestone.
- A manageable starting scope — focusing on two well-studied genes lets us
  build and validate the whole pipeline before considering expanding to more
  genes.

## 5. What does GRCh38 mean?

**GRCh38** (Genome Reference Consortium Human Build 38) is the current
standard human reference genome assembly — a specific, agreed-upon version
of "the" human genome sequence that all coordinates (like "chr10:94,762,681")
are measured against. Using the same reference build everywhere in the
pipeline is critical: a position like `chr10:94762681` means a *different*
physical location in the older GRCh37/hg19 build. Every tool and file in this
project must agree on GRCh38, or coordinates silently mean the wrong thing.

## 6. What does bcftools do?

**bcftools** is the standard command-line tool for reading, filtering,
querying, and manipulating VCF/BCF files. We used it to:
- Query only a small genomic **region** out of a much larger remote file,
  without downloading the whole thing (using the file's index).
- Inspect file headers, sample lists, and variant counts.
- Compress and index (`.tbi`) our extracted VCFs so other tools can
  efficiently look up regions in them later.

## 7. What does cyvcf2 do?

**cyvcf2** is a fast Python library (built on the same underlying `htslib` C
library that powers bcftools) for reading VCF/BCF files from Python code. We
use it in `genomic/inspect_vcf.py` to programmatically read variants and
genotypes — this is the same kind of access our future variant-processing
code (further down the pipeline) will build on.

## 8. What tools were installed, and how

- **Python virtual environment** (`.venv/`, inside WSL Ubuntu): only
  `cyvcf2` and `pandas` installed via `pip`.
- **bcftools 1.24 + htslib/tabix 1.24** (`.tools/`, inside WSL Ubuntu):
  installed with `micromamba` (a small, no-admin-rights package manager)
  from the bioconda/conda-forge channels, into a project-local folder — no
  `sudo`/system-wide changes were made.
- We chose to run bioinformatics tools inside **WSL2 Ubuntu** rather than
  natively on Windows because `bcftools` has no native Windows build. The
  project folder itself lives on the Windows drive
  (`D:\Documents\College_purpose\Sem7\DNA\personalized-drug-recommendation`)
  and WSL accesses it at
  `/mnt/d/Documents/College_purpose/Sem7/DNA/personalized-drug-recommendation`,
  so the same files are editable from Windows tools and usable from Linux
  command-line tools.

## 9. What files were downloaded, and what commands were run

**Official source** (EMBL-EBI FTP, part of the International Genome Sample
Resource / IGSR): the NYGC 1000 Genomes 30x high-coverage, GRCh38-aligned,
jointly-genotyped and phased SNV/INDEL/SV panel (3,202 samples), released
2022-04-22:

```
https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/
```

Full per-chromosome files there are large (chr10 = 1.4 GB, chr22 = 425 MB).
Since we only need two small gene regions, we used `bcftools`'s ability to
query a **remote, tabix-indexed** VCF over HTTPS and only fetch the bytes
covering our region of interest — the full chromosome files never touched
disk.

**Gene coordinates** (GRCh38, from NCBI Gene — see
`genomic/gene_coordinates.json` for the full record with source URLs):

| Gene | NCBI Gene ID | Location (GRCh38) |
|---|---|---|
| CYP2C19 | 1557 | chr10:94,762,681–94,855,547 |
| CYP2D6 | 1565 | chr22:42,126,499–42,130,810 |

**Commands executed** (see `scripts/` for the exact scripts):

1. `scripts/download_cyp2c19_region.sh` — remote `bcftools view -r
   chr10:94757681-94860547` (gene ± 5 kb) against the chr10 URL above →
   `data/raw/1kGP_chr10_CYP2C19_region.vcf.gz`
2. `scripts/download_cyp2d6_region.sh` — remote `bcftools view -r
   chr22:42121499-42135810` (gene ± 5 kb) against the chr22 URL above →
   `data/raw/1kGP_chr22_CYP2D6_region.vcf.gz`
3. `scripts/inspect_raw_vcfs.sh` — `bcftools view -h`, `bcftools query -l`,
   `bcftools view -H | wc -l` on both raw files, to inspect headers, sample
   lists, contigs, and variant counts.
4. `genomic/inspect_vcf.py` — a `cyvcf2`-based script that reads a VCF and
   prints chromosome/position/REF/ALT/genotype for the first few variants
   and samples.
5. `scripts/extract_processed_regions.sh` — local (no network) `bcftools
   view -r` re-slicing the raw files down to the *exact* gene boundary (no
   padding) → `data/processed/cyp2c19.vcf.gz`, `data/processed/cyp2d6.vcf.gz`.

## 10. What the resulting files contain

| File | Region | Variants | Samples | Size |
|---|---|---|---|---|
| `data/raw/1kGP_chr10_CYP2C19_region.vcf.gz` | chr10 gene ± 5kb | 3,559 | 3,202 | 1.3 MB |
| `data/raw/1kGP_chr22_CYP2D6_region.vcf.gz` | chr22 gene ± 5kb | 545 | 3,202 | 247 KB |
| `data/processed/cyp2c19.vcf.gz` | exact CYP2C19 gene body | 3,255 | 3,202 | 1.2 MB |
| `data/processed/cyp2d6.vcf.gz` | exact CYP2D6 gene body | 245 | 3,202 | 95 KB |

All four files are gzip-compressed, tabix-indexed (`.tbi` sidecar files) VCFs
containing phased genotypes for all 3,202 1000 Genomes samples, restricted to
these two gene regions. `data/raw/` is the direct, unmodified output of the
remote region query against the official source (kept as our record of "what
we obtained, and how"); `data/processed/` is the further-refined, exact-gene
subset intended for downstream pharmacogenomic processing.

## 11. Milestone 1 & Layer 1 Completion: Automated Sample Phenotyping

PharmCAT 3.4.0 is fully integrated into the project pipeline:
1. `genomic/preprocess_sample.py`: Automatically slices individual sample genotypes across both gene regions (chr10 CYP2C19 and chr22 CYP2D6) from the 3,202 1000 Genomes panel, normalizes multiallelic variants, and produces a single combined, indexed sample VCF (`data/processed/samples/<sample_id>/<sample_id>_pgx.vcf.gz`).
2. `genomic/call_phenotypes.py`: Executes PharmCAT's Named Allele Matcher, Phenotyper, and Reporter (`tools/pharmcat/pharmcat-3.4.0-all.jar`) with `-research cyp2d6` on the sample VCF, parsing the resulting `.report.tsv` and `.phenotype.json` into structured star-allele diplotypes, activity scores, and CPIC metabolizer phenotypes.
3. `genomic/structural_annotator.py`: Implements structural variant confidence assessment (highlighting short-read copy-number assumptions for CYP2D6) and flags Variants of Unknown Significance (VUS) per Lauschke et al. 2023.
4. `genomic/patient_profile.py`: Orchestrates the complete pipeline, enriches with demographic metadata (population, superpopulation, sex from IGSR pedigree file), and exports a standardized patient profile JSON directly feeding into Layer 2 and Layer 3.
5. `tests/test_genomic.py`: Unit and integration test suite verifying sample extraction, PharmCAT calling, structural assessments, and patient profile generation.
