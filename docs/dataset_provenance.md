# Dataset provenance and ancestry

## What the dataset is

The genomic input is the **1000 Genomes Project (1kGP) high-coverage resource** produced by the
New York Genome Center (NYGC): **3,202 individuals**, whole-genome sequenced on Illumina to
**~30x coverage**, aligned to **GRCh38**, jointly genotyped and phased. Release used:
`20220422_3202_phased_SNV_INDEL_SV` (EMBL-EBI / IGSR FTP). Reference paper: Byrska-Bishop et al.,
*High-coverage whole-genome sequencing of the expanded 1000 Genomes Project cohort including 602
trios*, Cell 185(18):3426–3440 (2022), doi:10.1016/j.cell.2022.08.004.

Facts that matter for interpretation:

- The cohort is the original **2,504 unrelated** phase-3 samples plus **698 related** samples
  (602 complete trios in the paper; our metadata table shows 2,590 founders and 612 samples with a
  parent in the set).
- DNA came from **lymphoblastoid cell lines (LCLs)** — immortalised B cells — not fresh blood.
  Cell-line culture can introduce artefacts, so these are reference-panel genomes, not clinical specimens.
- The samples are **healthy-volunteer reference donors with no drug-response data**. We can derive
  genotypes and predicted phenotypes from them, but we cannot validate a drug recommendation against
  an observed clinical outcome. State this limit in the report.

## How the data was taken (what the team actually did)

1. Did **not** download reads (FASTQ/CRAM). Used the already variant-called, phased VCFs.
2. Per-chromosome files are large (chr10 1.4 GB, chr22 425 MB), so `bcftools view -r` was run
   against the **remote, tabix-indexed** VCF over HTTPS, fetching only the bytes for each gene
   region ±5 kb → `data/raw/`. Scripts: `scripts/download_cyp2c19_region.sh`,
   `scripts/download_cyp2d6_region.sh`.
3. A local re-slice to the exact gene body gives `data/processed/`
   (`scripts/extract_processed_regions.sh`).
4. Gene coordinates (GRCh38, NCBI Gene) are in `genomic/gene_coordinates.json`.
5. Sample/population labels come from the IGSR table
   `20130606_g1k_3202_samples_ped_population.txt`
   (`scripts/download_sample_metadata.sh` → `data/raw/`).

| File | Region | Variants | Samples |
|---|---|---|---|
| `data/raw/1kGP_chr10_CYP2C19_region.vcf.gz` | CYP2C19 ±5 kb | 3,559 | 3,202 |
| `data/raw/1kGP_chr22_CYP2D6_region.vcf.gz` | CYP2D6 ±5 kb | 545 | 3,202 |
| `data/processed/cyp2c19.vcf.gz` | CYP2C19 gene body | 3,255 | 3,202 |
| `data/processed/cyp2d6.vcf.gz` | CYP2D6 gene body | 245 | 3,202 |

### Finding: the processed CYP2C19 file drops the `*17` defining variant

`CYP2C19*17` (increased function) is defined by rs12248560 (chr10:94,761,900 C>T), a **promoter**
variant ~780 bp *upstream* of the gene start (94,762,681). It is present in
`data/raw/1kGP_chr10_CYP2C19_region.vcf.gz` and **absent** from `data/processed/cyp2c19.vcf.gz`
(verified by position lookup). Feeding the gene-body file to PharmCAT would make `*17` impossible to
call and silently turn Rapid/Ultrarapid metabolizers into Normal. **Use the raw ±5 kb files (or
re-slice with padding) for phenotype calling.** The same logic applies to any other upstream
regulatory variant.

## Ancestry ("ethnicity") of the dataset

1kGP does not record ethnicity or race. It records **population** (26 sampling groups, defined by
where the donor sample was collected and the donor's stated ancestry) grouped into **5
superpopulations**. Use "genetic/continental ancestry group", not "ethnicity", in the report.
Computed by `analysis/dataset_population.py` from the metadata table:

| Superpopulation | Samples | Share | Populations (n) |
|---|---|---|---|
| AFR — African | 893 | 27.9% | ACB 116, ASW 74, ESN 149, GWD 178, LWK 99, MSL 99, YRI 178 |
| EUR — European | 633 | 19.8% | CEU 179, FIN 99, GBR 91, IBS 157, TSI 107 |
| SAS — South Asian | 601 | 18.8% | BEB 131, GIH 103, ITU 107, PJL 146, STU 114 |
| EAS — East Asian | 585 | 18.3% | CDX 93, CHB 103, CHS 163, JPT 104, KHV 122 |
| AMR — Admixed American | 490 | 15.3% | CLM 132, MXL 97, PEL 122, PUR 139 |
| **Total** | **3,202** | | 26 populations; 1,599 male / 1,603 female |

Population codes: ACB African Caribbean in Barbados · ASW African ancestry in SW USA · ESN Esan
(Nigeria) · GWD Gambian (Western Division) · LWK Luhya (Webuye, Kenya) · MSL Mende (Sierra Leone) ·
YRI Yoruba (Ibadan, Nigeria) · CLM Colombian (Medellín) · MXL Mexican ancestry (Los Angeles) · PEL
Peruvian (Lima) · PUR Puerto Rican · CDX Chinese Dai (Xishuangbanna) · CHB Han Chinese (Beijing) ·
CHS Southern Han Chinese · JPT Japanese (Tokyo) · KHV Kinh (Ho Chi Minh City) · CEU Utah residents
(N/W European ancestry) · FIN Finnish · GBR British (England & Scotland) · IBS Iberian (Spain) ·
TSI Toscani (Italy) · BEB Bengali (Bangladesh) · GIH Gujarati (Houston) · ITU Indian Telugu (UK) ·
PJL Punjabi (Lahore) · STU Sri Lankan Tamil (UK).

**Why this matters for pharmacogenomics:** allele frequencies differ sharply between ancestry
groups, so the same drug-gene pair has very different population impact. Defining-SNV frequencies in
this cohort (alt-allele frequency; proxy for the star allele, not a PharmCAT call):

| Gene | Variant (allele) | AFR | AMR | EAS | EUR | SAS |
|---|---|---|---|---|---|---|
| CYP2C19 | rs4244285 (`*2`, no function) | 0.161 | 0.110 | 0.322 | 0.142 | 0.355 |
| CYP2C19 | rs4986893 (`*3`, no function) | 0.002 | 0.000 | 0.054 | 0.000 | 0.014 |
| CYP2C19 | rs12248560 (`*17`, increased) | 0.236 | 0.120 | 0.015 | 0.224 | 0.148 |
| CYP2D6 | rs3892097 (`*4`, no function) | 0.063 | 0.122 | 0.002 | 0.188 | 0.108 |
| CYP2D6 | rs28371725 (`*41`, decreased) | 0.017 | 0.067 | 0.034 | 0.092 | 0.119 |

Reading it: CYP2C19 loss-of-function (`*2`/`*3`) is ~2x more common in East and South Asians than
Europeans, so clopidogrel failure risk is highest there; CYP2D6 `*4` is common in Europeans and
nearly absent in East Asians, who instead carry the decreased-function `*10` (CPIC: ~43%).

**Sanity check against an independent source.** Our frequencies agree with CPIC's published
weighted-average allele frequencies where one SNV defines one allele (e.g. CYP2C19 `*2` EUR
0.142 vs CPIC 0.147; AFR 0.161 vs 0.157; CYP2D6 `*4` EUR 0.188 vs 0.185; AMR 0.122 vs 0.121).
They diverge where the SNV is shared across several haplotypes — CYP2D6 rs1065852 (P34S) sits on
`*10` but also on `*4`/`*36` backbones, and rs16947 (R296C) is on many alleles — which is exactly why
single-SNV analysis is only a proxy and a haplotype caller (PharmCAT) is required. Full table:
run `python3 analysis/dataset_population.py`.

## Limitations to state in the report

- **Coverage gaps:** no Oceanian or Near-Eastern donors. CPIC reports CYP2C19 Poor Metabolizer
  frequency of ~57% in Oceanian populations versus ~2% in Europeans — a population this dataset cannot represent.
- **Admixture:** AMR and ASW/ACB are admixed; superpopulation is a coarse label, not a genetic ancestry estimate.
- **CYP2D6 structural variation** (`*5` deletion, `xN` duplications, CYP2D7 hybrids) is not visible to the
  SNV-level analysis above; it needs a dedicated caller (Aldy/StellarPGx, per the tech stack) — otherwise
  samples default to `*1` and activity is misestimated.
- **No outcome labels:** reference donors have no recorded drug response.

Sources: Byrska-Bishop et al. 2022 (Cell); IGSR/NYGC data release notes
(<https://www.internationalgenome.org/announcements/3202-samples-at-high-coverage-from-NYGC/>);
CPIC population frequency tables (<https://api.cpicpgx.org/v1/population_frequency_view>).
