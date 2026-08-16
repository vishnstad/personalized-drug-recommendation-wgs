"""
Pull real drug -> adverse-event associations from SIDER
(http://sideeffects.embl.de) — free flat-file download, no auth.

SIDER keys drugs by STITCH compound ID + a free-text drug name, not RxNorm, so we
join to our CPIC-derived Drug nodes by normalized drug name (lowercased, punctuation
stripped). This is a best-effort match, not a guaranteed 1:1 crosswalk -- unmatched
SIDER rows are simply not attached to the graph. Documented as such in
docs/layer2_writeup.md rather than silently faked.

Output: data/raw/sider_side_effects.tsv (raw download, cached)
        data/raw/sider_matched.json (drug_name -> [ {meddra_id, term}, ... ])
"""
import gzip
import json
import re
import shutil
from pathlib import Path

import requests

SIDER_URL = "http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
GZ_PATH = RAW_DIR / "sider_meddra_all_se.tsv.gz"
TSV_PATH = RAW_DIR / "sider_side_effects.tsv"


def normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def download() -> None:
    if TSV_PATH.exists():
        print(f"  already downloaded -> {TSV_PATH}")
        return
    print("  downloading SIDER meddra_all_se.tsv.gz ...")
    resp = requests.get(SIDER_URL, timeout=60, stream=True)
    resp.raise_for_status()
    with open(GZ_PATH, "wb") as f:
        shutil.copyfileobj(resp.raw, f)
    with gzip.open(GZ_PATH, "rb") as f_in, open(TSV_PATH, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    GZ_PATH.unlink()
    print(f"  extracted -> {TSV_PATH}")


# SIDER meddra_all_se.tsv columns (no header row):
# 0 stitch_id_flat, 1 stitch_id_stereo, 2 umls_cui_from_label, 3 meddra_type
# (PT/LLT), 4 umls_cui_meddra, 5 side_effect_name
def build_index() -> dict[str, list[dict]]:
    cpic_drugs = json.loads((RAW_DIR / "cpic_drug.json").read_text())
    wanted_names = {normalize_name(d["name"]): d["name"] for d in cpic_drugs if d.get("name")}

    # SIDER has no drug name column directly -- it ships a separate drug_names file
    # keyed by the same STITCH id. Pull that too (small file).
    names_url = "http://sideeffects.embl.de/media/download/drug_names.tsv"
    names_path = RAW_DIR / "sider_drug_names.tsv"
    if not names_path.exists():
        resp = requests.get(names_url, timeout=30)
        resp.raise_for_status()
        names_path.write_bytes(resp.content)

    stitch_to_name: dict[str, str] = {}
    with open(names_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            stitch_id, drug_name = parts[0], parts[1]
            stitch_to_name[stitch_id] = drug_name

    matched: dict[str, list[dict]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    with open(TSV_PATH, encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 6:
                continue
            stitch_flat, _stereo, _cui_label, meddra_type, meddra_cui, term = cols[:6]
            if meddra_type != "PT":  # keep preferred terms only, skip low-level terms
                continue
            sider_name = stitch_to_name.get(stitch_flat)
            if not sider_name:
                continue
            norm = normalize_name(sider_name)
            cpic_name = wanted_names.get(norm)
            if not cpic_name:
                continue
            key = (cpic_name, meddra_cui)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            matched.setdefault(cpic_name, []).append({"meddra_id": meddra_cui, "term": term})

    return matched


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading SIDER data ...")
    download()
    print("Matching SIDER ADRs to CPIC drug names ...")
    matched = build_index()
    out_path = RAW_DIR / "sider_matched.json"
    out_path.write_text(json.dumps(matched, indent=2))
    total_pairs = sum(len(v) for v in matched.values())
    print(f"Matched {len(matched)} drugs, {total_pairs} drug-ADR pairs -> {out_path}")


if __name__ == "__main__":
    main()
