"""Rule-based faithfulness check: an explanation may only mention facts present in the
retrieved graph evidence. Anything else is a hallucination and the explanation is rejected."""
import re


def check_explanation(text: str, drug: str, evidence: dict, all_drug_names: set[str]) -> list[str]:
    """Return a list of problems (empty = faithful).

    evidence: {"pmids": set[str], "levels": set[str]} retrieved for this drug.
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
    return problems
