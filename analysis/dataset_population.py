"""
Ancestry make-up of the 3,202-sample 1000 Genomes (NYGC 30x) dataset, and carrier
frequencies of star-allele-defining SNVs in our two gene regions, per superpopulation.

Uses data/raw (gene +/- 5 kb), NOT data/processed: the *17 defining SNV (rs12248560,
chr10:94,761,900) is a promoter variant upstream of the CYP2C19 gene body, so the
gene-body-only processed file does not contain it.

Caveat: single defining-SNV frequencies are a *proxy*, not star-allele calls (PharmCAT
does the real calling). CYP2D6 structural alleles (*5 deletion, xN duplications) are
invisible to SNV-level analysis.

Usage: python3 analysis/dataset_population.py
"""
import gzip
import json
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PED = ROOT / "data/raw/20130606_g1k_3202_samples_ped_population.txt"

# (gene, vcf, rsID, GRCh38 pos, ref, alt, meaning) -- positions/alleles from CPIC
# sequence_location (api.cpicpgx.org/v1/sequence_location)
TARGETS = [
    ("CYP2C19", "1kGP_chr10_CYP2C19_region.vcf.gz", "rs4244285", 94781859, "G", "A", "*2 no function (splice)"),
    ("CYP2C19", "1kGP_chr10_CYP2C19_region.vcf.gz", "rs4986893", 94780653, "G", "A", "*3 no function (stop)"),
    ("CYP2C19", "1kGP_chr10_CYP2C19_region.vcf.gz", "rs12248560", 94761900, "C", "T", "*17 increased function"),
    ("CYP2D6", "1kGP_chr22_CYP2D6_region.vcf.gz", "rs3892097", 42128945, "C", "T", "*4 no function (splice)"),
    ("CYP2D6", "1kGP_chr22_CYP2D6_region.vcf.gz", "rs1065852", 42130692, "G", "A", "*10 decreased (P34S; also on *4 backbone)"),
    ("CYP2D6", "1kGP_chr22_CYP2D6_region.vcf.gz", "rs28371725", 42127803, "C", "T", "*41 decreased (splice)"),
    ("CYP2D6", "1kGP_chr22_CYP2D6_region.vcf.gz", "rs16947", 42127941, "G", "A", "*2 normal (R296C)"),
]


def load_ped():
    rows = [l.split() for l in PED.read_text().splitlines()[1:]]
    return {r[1]: dict(father=r[2], mother=r[3], sex=r[4], pop=r[5], sup=r[6]) for r in rows}


def allele_freqs(vcf: Path, wanted: dict, samples_meta: dict):
    """wanted: {pos: (ref, alt)} -> {pos: {sup: [alt_alleles, total_alleles]}}"""
    out = {p: defaultdict(lambda: [0, 0]) for p in wanted}
    with gzip.open(vcf, "rt") as f:
        samples = []
        for line in f:
            if line.startswith("##"):
                continue
            cols = line.rstrip("\n").split("\t")
            if line.startswith("#CHROM"):
                samples = cols[9:]
                continue
            pos = int(cols[1])
            if pos not in wanted:
                continue
            ref, alts = cols[3], cols[4].split(",")
            wref, walt = wanted[pos]
            if ref != wref or walt not in alts:
                continue
            idx = str(alts.index(walt) + 1)
            for s, gt in zip(samples, cols[9:]):
                sup = samples_meta[s]["sup"]
                for a in gt.split(":")[0].replace("|", "/").split("/"):
                    if a == ".":
                        continue
                    out[pos][sup][1] += 1
                    out[pos][sup][0] += (a == idx)
    return out


CPIC_GROUP = {"AFR": "Sub-Saharan African", "AMR": "Latino", "EAS": "East Asian",
              "EUR": "European", "SAS": "Central/South Asian"}
CPIC_ALLELE = {"rs4244285": "*2", "rs4986893": "*3", "rs12248560": "*17",
               "rs3892097": "*4", "rs1065852": "*10", "rs28371725": "*41", "rs16947": "*2"}


def cpic_reference(gene: str, allele: str) -> dict:
    """CPIC weighted-average allele frequency per CPIC population group (live API)."""
    url = (f"https://api.cpicpgx.org/v1/population_frequency_view?genesymbol=eq.{gene}"
           f"&name=eq.{urllib.parse.quote(allele)}")
    with urllib.request.urlopen(url, timeout=60) as r:
        return {x["population_group"]: x["freq_weighted_avg"] for x in json.load(r)}


def main():
    meta = load_ped()
    print(f"Samples: {len(meta)}")
    sup = Counter(m["sup"] for m in meta.values())
    print("\nSuperpopulation counts:", dict(sorted(sup.items())))
    pop = Counter((m["sup"], m["pop"]) for m in meta.values())
    print("\nPopulation counts (superpop, pop, n):")
    for (s, p), n in sorted(pop.items()):
        print(f"  {s}  {p}  {n}")
    founders = sum(1 for m in meta.values() if m["father"] == "0" and m["mother"] == "0")
    print(f"\nFounders (no parents in set): {founders}; children in trios/duos: {len(meta) - founders}")
    print("Sex (1=male,2=female):", dict(Counter(m["sex"] for m in meta.values())))

    print("\nDefining-SNV alt-allele frequency by superpopulation (proxy, not star-allele calls):")
    sups = ["AFR", "AMR", "EAS", "EUR", "SAS"]
    print("gene     rsID        meaning                                   " + "  ".join(f"{s:>6}" for s in sups) + "     ALL")
    for gene in ("CYP2C19", "CYP2D6"):
        t = [x for x in TARGETS if x[0] == gene]
        res = allele_freqs(ROOT / "data/raw" / t[0][1], {x[3]: (x[4], x[5]) for x in t}, meta)
        for _, _, rs, pos, _, _, meaning in t:
            cells, a_tot, n_tot = [], 0, 0
            for s in sups:
                a, n = res[pos][s]
                a_tot, n_tot = a_tot + a, n_tot + n
                cells.append(f"{(a / n if n else float('nan')):6.3f}")
            print(f"{gene:8} {rs:11} {meaning:42} " + "  ".join(cells) + f"  {a_tot / n_tot if n_tot else float('nan'):6.3f}")
            try:
                ref = cpic_reference(gene, CPIC_ALLELE[rs])
                print(f"{'':8} {'CPIC ref':11} {CPIC_ALLELE[rs] + ' weighted avg (CPIC pop. groups)':42} "
                      + "  ".join(f"{ref.get(CPIC_GROUP[s], float('nan')):6.3f}" for s in sups))
            except Exception as exc:  # network optional
                print(f"{'':8} (CPIC reference unavailable: {exc})")


if __name__ == "__main__":
    main()
