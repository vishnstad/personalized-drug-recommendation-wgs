"""
Transform raw CPIC / HGNC / SIDER API dumps (data/raw/*.json) into normalized
node/relationship tables (data/processed/*.json) ready for Neo4j loading, per the
schema in ../schema/schema.md.

Run after fetch_cpic.py, fetch_hgnc.py, and (optionally) fetch_sider.py.
"""
import json
from collections import defaultdict
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_DIPLOTYPES_PER_PHENOTYPE = 6


def load_json(name: str, default=None):
    path = RAW_DIR / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, data) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  -> {len(data)} rows written to {path}")


def main() -> None:
    genes = load_json("cpic_gene.json", [])
    drugs = load_json("cpic_drug.json", [])
    pairs = load_json("cpic_pair.json", [])
    guidelines = load_json("cpic_guideline.json", [])
    recommendations = load_json("cpic_recommendation.json", [])
    diplotypes = load_json("cpic_diplotype.json", [])
    publications = load_json("cpic_publication.json", [])
    hgnc_lookup = load_json("hgnc_lookup.json", {})
    sider_matched = load_json("sider_matched.json", {})

    # ---- Gene nodes -----------------------------------------------------
    gene_nodes = []
    for g in genes:
        symbol = g["symbol"]
        enrich = hgnc_lookup.get(symbol, {})
        gene_nodes.append({
            "symbol": symbol,
            "hgnc_id": g.get("hgncid") or enrich.get("hgnc_id"),
            "name": enrich.get("name"),
            "chromosome": g.get("chr"),
        })
    print("Gene nodes:")
    write_json("nodes_gene.json", gene_nodes)

    # ---- Drug nodes -------------------------------------------------------
    drug_nodes = []
    for d in drugs:
        drug_nodes.append({
            "rxnorm_id": d["drugid"],
            "name": d.get("name"),
            "drugbank_id": d.get("drugbankid"),
            "atc_ids": d.get("atcid") or [],
        })
    print("Drug nodes:")
    write_json("nodes_drug.json", drug_nodes)

    # ---- Guideline nodes ----------------------------------------------
    guideline_nodes = []
    guideline_id_set = set()
    for gl in guidelines:
        guideline_nodes.append({
            "id": gl["id"],
            "name": gl.get("name"),
            "url": gl.get("url"),
            "genes": gl.get("genes") or [],
        })
        guideline_id_set.add(gl["id"])
    print("Guideline nodes:")
    write_json("nodes_guideline.json", guideline_nodes)

    # ---- Publication nodes + Guideline->Publication edges ---------------
    publication_nodes = []
    cites_edges = []
    seen_pmids = set()
    for p in publications:
        pmid = p.get("pmid")
        if not pmid:
            continue
        if pmid not in seen_pmids:
            seen_pmids.add(pmid)
            publication_nodes.append({
                "pmid": pmid,
                "title": p.get("title"),
                "year": p.get("year"),
                "journal": p.get("journal"),
                "doi": p.get("doi"),
                "url": p.get("url"),
            })
        gid = p.get("guidelineid")
        if gid in guideline_id_set:
            cites_edges.append({"guideline_id": gid, "pmid": pmid})
    print("Publication nodes:")
    write_json("nodes_publication.json", publication_nodes)
    print("Guideline CITES Publication edges:")
    write_json("edges_guideline_cites_publication.json", cites_edges)

    # ---- Gene-Drug ASSOCIATED_WITH edges (evidence-graded) ---------------
    known_gene_symbols = {g["symbol"] for g in genes}
    known_drug_ids = {d["drugid"] for d in drugs}
    associated_edges = []
    for p in pairs:
        if p.get("removed"):
            continue
        gene_sym, drug_id = p.get("genesymbol"), p.get("drugid")
        if gene_sym not in known_gene_symbols or drug_id not in known_drug_ids:
            continue
        associated_edges.append({
            "gene": gene_sym,
            "drug_rxnorm_id": drug_id,
            "cpic_level": p.get("cpiclevel"),
            "clinpgx_level": p.get("clinpgxlevel"),
            "pgx_testing": p.get("pgxtesting"),
            "used_for_recommendation": bool(p.get("usedforrecommendation")),
            "citations": p.get("citations") or [],
        })
    print("Gene ASSOCIATED_WITH Drug edges:")
    write_json("edges_gene_associated_with_drug.json", associated_edges)

    # ---- Phenotype nodes + Diplotype nodes (sampled) + HAS_DIPLOTYPE /
    #      RESULTS_IN_PHENOTYPE edges ------------------------------------
    phenotype_keys = set()  # (gene, phenotype_name)
    phenotype_meta: dict[tuple, dict] = {}
    diplotypes_by_phenotype = defaultdict(list)
    for d in diplotypes:
        gene_sym = d["genesymbol"]
        phenotype_name = d.get("generesult")
        if not phenotype_name:
            continue
        key = (gene_sym, phenotype_name)
        phenotype_keys.add(key)
        if key not in phenotype_meta and d.get("ehrpriority"):
            phenotype_meta[key] = {"ehr_priority": d.get("ehrpriority")}
        diplotypes_by_phenotype[key].append(d)

    # also pick up phenotype-equivalent labels referenced only from
    # recommendation.phenotypes / recommendation.allelestatus (covers genes like
    # HLA-B that don't appear in the diplotype table at all)
    for r in recommendations:
        for gene_sym, phenotype_name in (r.get("phenotypes") or {}).items():
            if gene_sym in known_gene_symbols and phenotype_name:
                phenotype_keys.add((gene_sym, phenotype_name))
        for gene_sym, allele_status in (r.get("allelestatus") or {}).items():
            if gene_sym in known_gene_symbols and allele_status:
                phenotype_keys.add((gene_sym, allele_status))

    phenotype_nodes = []
    for gene_sym, phenotype_name in sorted(phenotype_keys):
        meta = phenotype_meta.get((gene_sym, phenotype_name), {})
        phenotype_nodes.append({
            "id": f"{gene_sym}:{phenotype_name}",
            "gene": gene_sym,
            "name": phenotype_name,
            "ehr_priority": meta.get("ehr_priority"),
            "basis": "diplotype" if (gene_sym, phenotype_name) in diplotypes_by_phenotype else "allele_status",
        })
    print("Phenotype nodes:")
    write_json("nodes_phenotype.json", phenotype_nodes)

    diplotype_nodes = []
    has_diplotype_edges = []
    results_in_phenotype_edges = []
    for key, rows in diplotypes_by_phenotype.items():
        gene_sym, phenotype_name = key
        rows_sorted = sorted(rows, key=lambda r: len(r["diplotype"]))[:MAX_DIPLOTYPES_PER_PHENOTYPE]
        for row in rows_sorted:
            dip_id = f"{gene_sym}:{row['diplotype']}"
            diplotype_nodes.append({
                "id": dip_id,
                "gene": gene_sym,
                "name": row["diplotype"],
                "function1": row.get("function1"),
                "function2": row.get("function2"),
                "total_activity_score": row.get("totalactivityscore"),
            })
            has_diplotype_edges.append({"gene": gene_sym, "diplotype_id": dip_id})
            results_in_phenotype_edges.append({
                "diplotype_id": dip_id,
                "phenotype_id": f"{gene_sym}:{phenotype_name}",
            })
    print("Diplotype nodes (sampled):")
    write_json("nodes_diplotype.json", diplotype_nodes)
    print("Gene HAS_DIPLOTYPE edges:")
    write_json("edges_gene_has_diplotype.json", has_diplotype_edges)
    print("Diplotype RESULTS_IN_PHENOTYPE edges:")
    write_json("edges_diplotype_results_in_phenotype.json", results_in_phenotype_edges)

    # full (unsampled) diplotype -> phenotype lookup, kept flat for the
    # Layer1/Layer2 boundary (patient-diplotype resolution), not loaded as nodes
    full_lookup = [
        {"gene": d["genesymbol"], "diplotype": d["diplotype"], "phenotype": d.get("generesult")}
        for d in diplotypes
    ]
    write_json("diplotype_phenotype_lookup.json", full_lookup)

    # ---- Recommendation nodes + edges ------------------------------------
    known_guideline_ids = guideline_id_set
    recommendation_nodes = []
    recommends_drug_edges = []
    follows_guideline_edges = []
    has_recommendation_edges = []
    skipped_no_phenotype = 0
    for r in recommendations:
        rec_id = r["id"]
        drug_id = r.get("drugid")
        if drug_id not in known_drug_ids:
            continue
        recommendation_nodes.append({
            "id": rec_id,
            "drug_recommendation": r.get("drugrecommendation"),
            "classification": r.get("classification"),
            "implications": json.dumps(r.get("implications") or {}, ensure_ascii=False),
            "population": r.get("population"),
            "comments": r.get("comments"),
            "dosing_information": bool(r.get("dosinginformation")),
            "alternate_drug_available": bool(r.get("alternatedrugavailable")),
            # The full condition this recommendation is gated on. A CPIC row can require several genes
            # at once (e.g. amitriptyline: CYP2C19 PM *and* CYP2D6 NM), and CYP2D6 rows are further keyed
            # by activity score in `lookupkey`. Kept as JSON so retrieval can match the whole condition
            # against a patient instead of only the one phenotype edge it was reached through.
            "phenotypes_json": json.dumps({**(r.get("phenotypes") or {}), **(r.get("allelestatus") or {})}, sort_keys=True),
            "lookupkey_json": json.dumps(r.get("lookupkey") or {}, sort_keys=True),
        })
        recommends_drug_edges.append({"recommendation_id": rec_id, "drug_rxnorm_id": drug_id})
        gid = r.get("guidelineid")
        if gid in known_guideline_ids:
            follows_guideline_edges.append({"recommendation_id": rec_id, "guideline_id": gid})

        linked_any = False
        for gene_sym, phenotype_name in (r.get("phenotypes") or {}).items():
            if gene_sym in known_gene_symbols and phenotype_name:
                has_recommendation_edges.append({
                    "phenotype_id": f"{gene_sym}:{phenotype_name}",
                    "recommendation_id": rec_id,
                })
                linked_any = True
        for gene_sym, allele_status in (r.get("allelestatus") or {}).items():
            if gene_sym in known_gene_symbols and allele_status:
                has_recommendation_edges.append({
                    "phenotype_id": f"{gene_sym}:{allele_status}",
                    "recommendation_id": rec_id,
                })
                linked_any = True
        if not linked_any:
            skipped_no_phenotype += 1

    print("Recommendation nodes:")
    write_json("nodes_recommendation.json", recommendation_nodes)
    print("Recommendation RECOMMENDS Drug edges:")
    write_json("edges_recommendation_recommends_drug.json", recommends_drug_edges)
    print("Recommendation FOLLOWS_GUIDELINE edges:")
    write_json("edges_recommendation_follows_guideline.json", follows_guideline_edges)
    print("Phenotype HAS_RECOMMENDATION edges:")
    write_json("edges_phenotype_has_recommendation.json", has_recommendation_edges)
    print(f"  ({skipped_no_phenotype} recommendations had no phenotype/allele-status key to link)")

    # ---- ADR nodes + Drug CAUSES_ADR edges (SIDER, best-effort match) ----
    adr_nodes = {}
    causes_adr_edges = []
    for drug_name, entries in sider_matched.items():
        for entry in entries:
            meddra_id = entry["meddra_id"]
            adr_nodes[meddra_id] = {"id": meddra_id, "name": entry["term"], "meddra_id": meddra_id}
            causes_adr_edges.append({"drug_name": drug_name, "adr_id": meddra_id})
    print("ADR nodes:")
    write_json("nodes_adr.json", list(adr_nodes.values()))
    print("Drug CAUSES_ADR edges:")
    write_json("edges_drug_causes_adr.json", causes_adr_edges)

    print("\nNormalization complete.")


if __name__ == "__main__":
    main()
