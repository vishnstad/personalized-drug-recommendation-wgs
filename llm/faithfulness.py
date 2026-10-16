"""Rule-based faithfulness check: an explanation may only mention facts present in the
retrieved graph evidence. Anything else is a hallucination and the explanation is rejected."""
import re
from typing import Optional

# singular only: "normal metabolizers" (plural) describes a comparison group, not a claim about this patient
PHENOTYPE = r"(?:likely\s+)?(?:ultrarapid|rapid|normal|intermediate|poor)\s+metabolizer\b"


def phenotype_claims(text: str, genes: list[str]) -> list[tuple[str, str]]:
    """(gene, phenotype) pairs the text asserts: "CYP2D6 Poor Metabolizer", "CYP2D6 phenotype as a Poor
    Metabolizer" (gene, then <=3 words that are not another gene, then phenotype) and "Poor Metabolizer of/for CYP2D6"."""
    if not genes:
        return []
    g = "|".join(re.escape(x) for x in genes)
    claims = [(m.group(1), m.group(2)) for m in re.finditer(rf"\b({g})\b(?:\s+(?!(?:{g})\b)[\w']+){{0,3}}?\s+({PHENOTYPE})", text, re.I)]
    claims += [(m.group(2), m.group(1)) for m in re.finditer(rf"({PHENOTYPE})\s+(?:of|for)\s+({g})\b", text, re.I)]
    return [(gene.upper(), " ".join(p.split()).lower()) for gene, p in claims]


STAR = r"\*\d+[A-Za-z]?(?:x\d+|xN)?"
DOSE = r"\d+(?:\.\d+)?\s?(?:%|mg/kg/day|mg/kg|mg/day|mg)"


def homozygous_claims(text: str) -> set[str]:
    """Alleles the text says the patient carries on both copies ("two copies of the *2 allele", "homozygous for *4")."""
    pats = [rf"\b(?:two|both)\s+copies\s+(?:of|carry|have)\s+(?:the\s+)?(?:[\w-]+\s+)?({STAR})",
            rf"\bhomozygous\s+(?:for\s+)?(?:the\s+)?(?:[\w-]+\s+)?({STAR})"]
    return {m.group(1) for p in pats for m in re.finditer(p, text, re.I)}


def check_explanation(text: str, drug: str, evidence: dict, all_drug_names: set[str],
                      phenotypes: Optional[dict[str, str]] = None, evidence_text: Optional[str] = None,
                      diplotypes: Optional[dict[str, str]] = None) -> list[str]:
    """Return a list of problems (empty = faithful).

    evidence: {"pmids": set[str], "levels": set[str]} retrieved for this drug.
    phenotypes: the patient's {gene: phenotype}; if given, any phenotype the text attributes to one of
    these genes must be the patient's actual phenotype for it.
    evidence_text: the evidence the model was given; if given, every star allele (*4) and every dose or
    percentage (50%, 75 mg/day) in the text must appear in it.
    diplotypes: the patient's {gene: "*3/*4"}; if given, "two copies of *X" is only allowed for a *X/*X diplotype.
    """
    problems = []
    for pmid in re.findall(r"PMID:?\s*(\d+)", text):
        if pmid not in evidence["pmids"]:
            problems.append(f"cites PMID {pmid} that was not retrieved for {drug}")
    for level in re.findall(r"CPIC (?:evidence )?level\s+([A-D](?:/[A-D])?)", text, flags=re.I):
        if level.upper() not in evidence["levels"]:
            problems.append(f"states CPIC level {level.upper()} but graph has {sorted(evidence['levels'])}")
    lowered = text.lower()
    for other in all_drug_names:
        if other != drug and len(other) > 4 and re.search(rf"\b{re.escape(other)}\b", lowered):
            problems.append(f"mentions drug '{other}' that is not part of this evidence")
    if phenotypes:
        actual = {g.upper(): p for g, p in phenotypes.items()}
        for gene, claimed in sorted(set(phenotype_claims(text, list(phenotypes)))):
            if actual[gene].lower() != claimed:
                problems.append(f"calls the patient a {gene} {claimed.title()} but they are {gene} {actual[gene]}")
    if evidence_text is not None:
        squash = lambda v: re.sub(r"\s+", "", v.lower())  # noqa: E731
        ev = squash(evidence_text)
        for star in sorted(set(re.findall(STAR, text))):
            if squash(star) not in ev:
                problems.append(f"mentions allele {star} that is not in this patient's evidence")
        for dose in sorted(set(re.findall(DOSE, text, flags=re.I))):
            if squash(dose) not in ev:
                problems.append(f"states '{dose}' that does not appear in the evidence")
    if diplotypes:
        homs = {d.split("/")[0] for d in diplotypes.values() if d and "/" in d and len(set(d.split("/"))) == 1}
        for star in sorted(homozygous_claims(text) - homs):
            problems.append(f"says the patient has two copies of {star}, but the diplotypes are {', '.join(sorted(diplotypes.values()))}")
    return problems
