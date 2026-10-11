# The two pharmacogenes: CYP2C19 and CYP2D6

Facts marked **[CPIC]**, **[HGNC]** or **[project data]** were pulled directly from those sources
(`api.cpicpgx.org`, `rest.genenames.org`, `genomic/gene_coordinates.json`). Items marked
**[general]** are standard pharmacology/genetics background not re-verified against a primary
source in this session — check before quoting in the final report.

## 1. What they are

Both genes encode **cytochrome P450 (CYP) enzymes**: haem-containing monooxygenases embedded in the
membrane of the endoplasmic reticulum, most abundant in the **liver** **[general]**. They perform
**phase-I metabolism** — adding an oxygen atom to a drug so it can be cleared, or, for *prodrugs*,
converting an inactive molecule into its active form. Genetic variation changes how much working
enzyme a person makes, so it changes drug exposure. Together CYP2D6 and CYP2C19 metabolise roughly
30% of clinically used drugs (Petrović, Pešić & Lauschke 2019, via literature search).

| | **CYP2C19** | **CYP2D6** |
|---|---|---|
| HGNC ID / symbol | HGNC:2621 **[HGNC]** | HGNC:2625 **[HGNC]** |
| Official name | cytochrome P450 family 2 subfamily C member 19 | cytochrome P450 family 2 subfamily D member 6 *(gene/pseudogene)* |
| Cytogenetic band | 10q23.33 **[HGNC]** | 22q13.2 **[HGNC]** |
| GRCh38 location | chr10:94,762,681–94,855,547 (~92.9 kb) **[project data]** | chr22:42,126,499–42,130,810 (~4.3 kb) **[project data]** |
| NCBI Gene / Ensembl | 1557 / ENSG00000165841 **[HGNC]** | 1565 / ENSG00000100197 **[HGNC]** |
| RefSeqGene / protein | NG_008384.3 / NP_000760.1 **[CPIC]** | NG_008376.4 / NP_000097.3 **[CPIC]** |
| Alleles defined (CPIC) | 49 **[CPIC]** | 208 **[CPIC]** |
| Genotype→phenotype method | **Phenotype lookup** (function of each allele pair) **[CPIC]** | **Activity score** (numeric sum) **[CPIC]** |
| Neighbourhood | CYP2C cluster on 10q23 (CYP2C18/2C19/2C9/2C8) **[general]** | Next to pseudogenes CYP2D7 and CYP2D8P **[general]**; HGNC lists it as "gene/pseudogene" |
| Structural variation | Rare | Common: deletion, duplications, CYP2D7 hybrids |

Allele function classes in CPIC's table **[CPIC]**:

- **CYP2C19** (49 alleles): 12 no function, 6 decreased, 7 normal, **1 increased (`*17`)**, 10 uncertain, 13 unassigned.
- **CYP2D6** (208 alleles): 48 no function, 25 decreased, 16 normal, **8 increased (all gene-duplication alleles, e.g. `*1x2`, `*2x≥3`)**, 53 uncertain, 33 unknown, 25 unassigned.

## 2. Why variants change the enzyme (molecular mechanism)

| Allele | Defining change | Mechanism → effect |
|---|---|---|
| CYP2C19 `*2` (rs4244285) | splice-site variant (CPIC: "splicing defect") | aberrant mRNA splicing → truncated, non-functional protein → **no function** |
| CYP2C19 `*3` (rs4986893) | p.W212X | premature stop codon → no protein → **no function** |
| CYP2C19 `*17` (rs12248560) | promoter variant (chr10:94,761,900; CPIC: "expression") | more transcription → more enzyme → **increased function** |
| CYP2D6 `*4` (rs3892097) | splice defect | no functional enzyme → **no function** |
| CYP2D6 `*5` | whole-gene deletion | no gene copy → **no function** |
| CYP2D6 `*10` (rs1065852, P34S) | amino-acid change | unstable enzyme → **decreased function** |
| CYP2D6 `*41` (rs28371725) | splice-affecting | less normal transcript → **decreased function** |
| CYP2D6 `*1xN`, `*2xN` | extra gene copies | more enzyme → **increased function** |

Each person has two copies of each gene, so the pair of alleles (the **diplotype**) sets total activity.

## 3. From diplotype to phenotype — the two methods

- **CYP2C19 uses a phenotype lookup.** Each allele gets a function class and the *pair* decides the
  phenotype: two no-function alleles → Poor (PM); no-function + normal → Intermediate (IM); two
  normal → Normal (NM); `*1/*17` → Rapid (RM); `*17/*17` → Ultrarapid (UM). CPIC also has
  "Likely PM/IM" and "Indeterminate" for uncertain alleles — 8 categories in total **[CPIC]**.
- **CYP2D6 uses an activity score.** Each allele scores 0 (no function), 0.5 (decreased) or 1.0
  (normal); duplications multiply the copy's contribution; the two alleles are summed. CPIC's
  current buckets in our data **[CPIC]**: **PM = 0**; **IM = 0.25–1.0**; **NM = 1.25–2.25**; **UM
  > 2.25** (scores up to ≥6.0 appear for `xN` copies). Plus "Indeterminate" — 5 categories.

Why two methods: CYP2C19 has few, well-separated allele classes; CYP2D6 has many alleles with
graded effects and copy-number changes, which a three-level class cannot capture. Using one gene of each
type exercises both code paths in the pipeline.

## 4. Clinical relevance — what each gene does to drugs

Two distinct mechanisms **[general]**, both visible in our graph:

1. **Prodrug activation** — a poor metaboliser cannot make the active drug, so it *fails*; an
   ultrarapid metaboliser makes too much too fast, so it can be *toxic*.
   - CYP2C19 → **clopidogrel** (CPIC A): PM/IM cannot form the active thiol metabolite → inadequate
     platelet inhibition → stent thrombosis risk → use prasugrel/ticagrelor.
   - CYP2D6 → **codeine** (CPIC A): activated to morphine. PM: no analgesia. UM: morphine
     toxicity, respiratory depression (FDA boxed warning). Same logic for **tramadol** and **tamoxifen** (→ endoxifen).
2. **Active-drug clearance** — the enzyme removes the drug; a poor metaboliser accumulates it
   (adverse effects), an ultrarapid metaboliser under-doses it.
   - CYP2C19 → **voriconazole**, **PPIs** (omeprazole, pantoprazole, lansoprazole), **citalopram/
     escitalopram/sertraline**, **amitriptyline**.
   - CYP2D6 → **TCAs**, **paroxetine/fluvoxamine**, **atomoxetine**, **ondansetron/tropisetron**,
     **metoprolol** and many antipsychotics.

Drug counts from the graph **[CPIC]** (full lists and ATC grouping in `phenotypes_and_drugs.md`):
CYP2C19 has **27** linked drugs (9 at CPIC level A); CYP2D6 has **79** (11 at level A, 4 at A/B).
**15 drugs are linked to both genes** (mostly antidepressants), and several CPIC guidelines are
written jointly for both — so a patient's two phenotypes must be considered *together*, which is
exactly the multi-hop query the graph is for.

## 5. Why this matters for the project (and its limits)

- **Population dependence:** CYP2C19 PM is 2.4% in Europeans but 13.0% in East Asians and ~57% in
  Oceanians; CYP2D6 PM is 6.5% in Europeans but 0.8% in East Asians **[CPIC]**. Same drug, different risk.
- **Genotype ≠ phenotype in practice (phenoconversion) [general]:** strong inhibitors (e.g. the SSRIs
  paroxetine and fluoxetine on CYP2D6) can make a genetically normal patient behave like a poor
  metaboliser. Our pipeline predicts the *genetic* phenotype only; a clinical system must also read the medication list.
- **CYP2D6 is hard to genotype from short reads:** the CYP2D7 pseudogene is highly similar, and
  deletions/duplications/hybrids can be missed, defaulting the call to `*1` and misestimating activity.
  Flag this limit for the CYP2D6 results.
- **Variants outside the gene body matter:** `CYP2C19*17` is a promoter SNV — see the finding in
  `dataset_provenance.md` about the gene-body-only processed VCF.

## Sources

- HGNC REST API, `rest.genenames.org/fetch/symbol/{CYP2C19,CYP2D6}` (queried this session).
- CPIC API: `gene`, `allele`, `gene_result`, `sequence_location`, `pair`, `population_frequency_view` (queried this session).
- Petrović J, Pešić V, Lauschke VM. *Frequencies of clinically important CYP2C19 and CYP2D6 alleles are graded across Europe.* (PMC6906321).
- Gaedigk A et al. *Prediction of CYP2D6 phenotype from genotype across world populations.* Genet Med 2017 (<https://www.nature.com/articles/gim201680>).
- CPIC guideline for clopidogrel based on CYP2C19 genotype (<https://cpicpgx.org/?p=2763>); CPIC CYP2D6/tamoxifen guideline.
- PharmVar CYP2D6 tutorial (structural variants and CYP2D7 hybrids).
