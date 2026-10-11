"""
Validate the loaded Neo4j graph. Three kinds of checks, each printed PASS/FAIL:

  1. Counts vs the live CPIC API (independent of our cached/normalized files)
  2. Structural integrity (cardinalities, orphans, ID formats, allowed values)
  3. Spot-checks: random Recommendation / gene-drug pair rows re-fetched from CPIC
     and compared field-by-field with what is in Neo4j

Usage (graph loaded, Neo4j up):  python3 knowledge_graph/validate_graph.py
Exit code is non-zero if any check fails. Writes a JSON report next to this file's docs.
"""
import json
import random
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.queries import get_driver  # noqa: E402

API = "https://api.cpicpgx.org/v1"
results: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


def api_count(table: str, query: str = "") -> int:
    r = requests.get(f"{API}/{table}?{query}&limit=1", headers={"Prefer": "count=exact"}, timeout=30)
    r.raise_for_status()
    return int(r.headers["Content-Range"].split("/")[1])


def api_rows(table: str, query: str) -> list[dict]:
    r = requests.get(f"{API}/{table}?{query}", timeout=30)
    r.raise_for_status()
    return r.json()


def q(session, cypher: str, **kw):
    return session.run(cypher, **kw).single()[0]


def main() -> None:
    driver = get_driver()
    with driver.session() as s:
        # ---- 1. counts vs live CPIC ----
        for label, table in [("Gene", "gene"), ("Drug", "drug"), ("Guideline", "guideline"),
                             ("Recommendation", "recommendation")]:
            n_graph, n_api = q(s, f"MATCH (n:{label}) RETURN count(n)"), api_count(table)
            check(f"{label} nodes == CPIC {table} rows", n_graph == n_api, f"graph={n_graph} cpic={n_api}")

        n_graph = q(s, "MATCH ()-[e:ASSOCIATED_WITH]->() RETURN count(e)")
        n_api = api_count("pair", "removed=eq.false")
        check("ASSOCIATED_WITH edges == CPIC non-removed pairs", n_graph == n_api, f"graph={n_graph} cpic={n_api}")

        n_graph = q(s, "MATCH (r:Recommendation)-[e:RECOMMENDS]->(:Drug) RETURN count(e)")
        check("every Recommendation has exactly one RECOMMENDS edge",
              n_graph == q(s, "MATCH (r:Recommendation) RETURN count(r)"), f"edges={n_graph}")

        # ---- 2. structural integrity ----
        def zero(name, cypher):
            n = q(s, cypher)
            check(name, n == 0, f"violations={n}")

        zero("no Recommendation without a drug",
             "MATCH (r:Recommendation) WHERE NOT (r)-[:RECOMMENDS]->(:Drug) RETURN count(r)")
        zero("no Recommendation without a guideline",
             "MATCH (r:Recommendation) WHERE NOT (r)-[:FOLLOWS_GUIDELINE]->(:Guideline) RETURN count(r)")
        zero("no Diplotype without exactly one Phenotype",
             "MATCH (d:Diplotype) WHERE size([(d)-[:RESULTS_IN_PHENOTYPE]->(:Phenotype) | 1]) <> 1 RETURN count(d)")
        zero("no Diplotype without its Gene",
             "MATCH (d:Diplotype) WHERE NOT (:Gene)-[:HAS_DIPLOTYPE]->(d) RETURN count(d)")
        zero("Phenotype.gene always matches a Gene node",
             "MATCH (p:Phenotype) WHERE NOT EXISTS { MATCH (g:Gene {symbol: p.gene}) } RETURN count(p)")
        zero("Gene.hgnc_id malformed (expect HGNC:<digits>)",
             "MATCH (g:Gene) WHERE g.hgnc_id IS NULL OR NOT g.hgnc_id =~ 'HGNC:[0-9]+' RETURN count(g)")
        # CPIC keys drugs by several namespaces, not only RxNorm (drug classes use ATC, a few use
        # DrugBank/MeSH/MedDRA, and one uses the placeholder RxNorm:NA). The `rxnorm_id` property
        # therefore holds CPIC's namespaced drugid; assert that form and report the breakdown.
        zero("Drug.rxnorm_id is not a '<namespace>:<id>' key",
             "MATCH (d:Drug) WHERE NOT d.rxnorm_id =~ '(RxNorm|ATC|Drugbank|MeSH|MedDRA):[^ ]+' RETURN count(d)")
        ns = {r[0]: r[1] for r in s.run("MATCH (d:Drug) RETURN split(d.rxnorm_id, ':')[0], count(*)")}
        check("Drug ID namespaces (info)", True, str(dict(sorted(ns.items()))))
        na = q(s, "MATCH (d:Drug) WHERE d.rxnorm_id = 'RxNorm:NA' RETURN count(d)")
        check("Drugs with CPIC placeholder RxNorm:NA (known CPIC data gap)", na <= 1, f"count={na}")
        zero("Publication.pmid not numeric",
             "MATCH (p:Publication) WHERE NOT p.pmid =~ '[0-9]+' RETURN count(p)")
        levels = {r[0] for r in s.run("MATCH ()-[e:ASSOCIATED_WITH]->() RETURN DISTINCT e.cpic_level")}
        allowed = {"A", "B", "C", "D", "A/B", "B/C", "C/D", "Retired", None}
        check("cpic_level values are all valid CPIC grades", levels <= allowed, f"seen={sorted(map(str, levels))}")
        zero("ADR nodes with no Drug pointing at them",
             "MATCH (a:ADR) WHERE NOT (:Drug)-[:CAUSES_ADR]->(a) RETURN count(a)")
        zero("duplicate (gene,drug) ASSOCIATED_WITH edges",
             "MATCH (g:Gene)-[e:ASSOCIATED_WITH]->(d:Drug) WITH g,d,count(e) AS c WHERE c>1 RETURN count(*)")

        # ---- 3. spot-checks against live CPIC ----
        random.seed(7)
        ids = [r[0] for r in s.run("MATCH (r:Recommendation) RETURN r.id")]
        bad = 0
        sample = random.sample(ids, 25)
        for rid in sample:
            row = api_rows("recommendation", f"id=eq.{rid}")[0]
            g = s.run("MATCH (r:Recommendation {id:$id})-[:RECOMMENDS]->(d:Drug) "
                      "RETURN r.drug_recommendation AS t, r.classification AS c, d.rxnorm_id AS d", id=rid).single()
            if (g["t"], g["c"], g["d"]) != (row["drugrecommendation"], row["classification"], row["drugid"]):
                bad += 1
        check("25 random Recommendations match CPIC (text, classification, drug)", bad == 0, f"mismatches={bad}")

        pairs = [(r[0], r[1]) for r in s.run(
            "MATCH (g:Gene)-[e:ASSOCIATED_WITH]->(d:Drug) RETURN g.symbol, d.rxnorm_id")]
        bad = 0
        for gene, drug in random.sample(pairs, 25):
            row = api_rows("pair", f"genesymbol=eq.{gene}&drugid=eq.{drug}&removed=eq.false")[0]
            e = s.run("MATCH (:Gene {symbol:$g})-[e:ASSOCIATED_WITH]->(:Drug {rxnorm_id:$d}) "
                      "RETURN e.cpic_level AS l LIMIT 1", g=gene, d=drug).single()
            if e["l"] != row["cpiclevel"]:
                bad += 1
        check("25 random gene-drug pairs: CPIC evidence level matches CPIC", bad == 0, f"mismatches={bad}")

        # ---- the two project genes: phenotype / drug coverage snapshot ----
        for gene in ("CYP2C19", "CYP2D6"):
            n_p = q(s, "MATCH (p:Phenotype {gene:$g}) RETURN count(p)", g=gene) if False else \
                s.run("MATCH (p:Phenotype {gene:$g}) RETURN count(p) AS n", g=gene).single()["n"]
            n_d = s.run("MATCH (:Gene {symbol:$g})-[:ASSOCIATED_WITH]->(d:Drug) RETURN count(DISTINCT d) AS n", g=gene).single()["n"]
            check(f"{gene} present with phenotypes and drugs", n_p > 0 and n_d > 0, f"phenotypes={n_p} drugs={n_d}")
    driver.close()

    failed = [r for r in results if not r["pass"]]
    out = Path(__file__).resolve().parent.parent / "docs" / "neo4j_validation_report.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed -> {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
