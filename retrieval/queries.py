"""
Cypher path-retrieval layer (Layer 2's interface to Layer 3).

Layer 3's RAG orchestrator calls these functions with a patient's pharmacogene
phenotypes (already resolved upstream by Layer 1 / PharmCAT) and gets back the
relevant subgraph: gene -> diplotype -> phenotype -> recommendation -> drug, plus
evidence-graded gene-drug associations and known ADRs. Every function returns plain
dicts/lists (not driver Record objects) so they're safe to json.dumps() straight into
an LLM prompt.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "pgxkgpassword")


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def recommendations_for_phenotype(driver, gene: str, phenotype_name: str) -> list[dict]:
    """Given one resolved phenotype (e.g. gene='CYP2D6', phenotype_name='Poor Metabolizer'),
    return every CPIC recommendation gated on it, with the drug, guideline, and citations
    attached -- this is the core retrieval call for a single-gene query."""
    query = """
        MATCH (ph:Phenotype {id: $phenotype_id})-[:HAS_RECOMMENDATION]->(rec:Recommendation)
        MATCH (rec)-[:RECOMMENDS]->(drug:Drug)
        OPTIONAL MATCH (rec)-[:FOLLOWS_GUIDELINE]->(gl:Guideline)
        OPTIONAL MATCH (gl)-[:CITES]->(pub:Publication)
        OPTIONAL MATCH (g:Gene {symbol: $gene})-[assoc:ASSOCIATED_WITH]->(drug)
        RETURN drug.name AS drug, drug.rxnorm_id AS drug_rxnorm_id,
               rec.drug_recommendation AS recommendation,
               rec.classification AS classification,
               rec.implications AS implications,
               gl.name AS guideline, gl.url AS guideline_url,
               assoc.cpic_level AS cpic_level, assoc.clinpgx_level AS clinpgx_level,
               collect(DISTINCT pub.pmid) AS guideline_pmids,
               coalesce(assoc.citations, []) AS pair_pmids
        ORDER BY drug.name
    """
    phenotype_id = f"{gene}:{phenotype_name}"
    with driver.session() as session:
        return [dict(r) for r in session.run(query, phenotype_id=phenotype_id, gene=gene)]


NO_RESULT = "No Result"
LEVEL_ORDER = ["A", "A/B", "B", "B/C", "C", "C/D", "D"]


def _lookup_matches(key: str, score: float) -> bool:
    """CPIC lookup keys for activity-score genes are strings like '1.0', '0.25' or '≥3.75'."""
    k = key.strip()
    try:
        if k.startswith(("≥", ">=")):
            return score >= float(k.lstrip("≥>="))
        return float(k) == score
    except ValueError:
        return True  # not a numeric key (e.g. a phenotype name) -> no extra constraint


def recommendations_for_patient(driver, phenotypes: dict[str, str],
                                activity_scores: dict[str, float] | None = None) -> list[dict]:
    """Patient-level retrieval: every CPIC recommendation whose *full* condition matches this patient.

    A CPIC recommendation can be gated on several genes at once (e.g. amitriptyline is keyed on the
    CYP2C19 *and* CYP2D6 phenotype pair), so reaching it through one matching phenotype edge is not
    enough -- every gene in its condition must match. A gene the patient was not genotyped for counts
    as CPIC's own "No Result" category. Where CPIC further splits a phenotype by activity score
    (CYP2D6 `lookupkey`), the patient's score selects the matching row when it is known.
    Rows for different populations (adults/pediatrics, ACS-PCI/non-ACS, ...) are all returned and
    carry `population`, since they are different clinical contexts, not alternatives to merge."""
    query = """
        MATCH (ph:Phenotype)-[:HAS_RECOMMENDATION]->(rec:Recommendation)
        WHERE ph.id IN $phenotype_ids
        WITH DISTINCT rec
        MATCH (rec)-[:RECOMMENDS]->(drug:Drug)
        OPTIONAL MATCH (rec)-[:FOLLOWS_GUIDELINE]->(gl:Guideline)
        OPTIONAL MATCH (gl)-[:CITES]->(pub:Publication)
        WITH rec, drug, gl, collect(DISTINCT pub.pmid) AS guideline_pmids
        OPTIONAL MATCH (g:Gene)-[assoc:ASSOCIATED_WITH]->(drug)
        WHERE g.symbol IN $genes
        RETURN rec.id AS recommendation_id, drug.name AS drug, drug.rxnorm_id AS drug_rxnorm_id,
               rec.drug_recommendation AS recommendation, rec.classification AS classification,
               rec.implications AS implications, rec.population AS population,
               rec.phenotypes_json AS phenotypes_json, rec.lookupkey_json AS lookupkey_json,
               gl.name AS guideline, gl.url AS guideline_url, guideline_pmids,
               collect(DISTINCT {gene: g.symbol, cpic_level: assoc.cpic_level,
                                 clinpgx_level: assoc.clinpgx_level,
                                 citations: coalesce(assoc.citations, [])}) AS pair_evidence
        ORDER BY drug, recommendation_id
    """
    ids = [f"{g}:{p}" for g, p in phenotypes.items()]
    with driver.session() as session:
        raw = [dict(r) for r in session.run(query, phenotype_ids=ids, genes=list(phenotypes))]

    scores = activity_scores or {}
    matched = []
    for r in raw:
        if r["phenotypes_json"] is None:
            raise RuntimeError("Recommendation nodes lack phenotypes_json -- re-run the ETL (knowledge_graph/etl/run_etl.sh).")
        condition = json.loads(r["phenotypes_json"])
        if any(phenotypes.get(gene, NO_RESULT) != value for gene, value in condition.items()):
            continue
        lookup = json.loads(r["lookupkey_json"] or "{}")
        if any(gene in scores and scores[gene] is not None and not _lookup_matches(str(key), scores[gene])
               for gene, key in lookup.items()):
            continue
        evidence = [e for e in r.pop("pair_evidence") if e["gene"] in condition]
        levels = [e["cpic_level"] for e in evidence if e["cpic_level"] in LEVEL_ORDER]
        r.update({
            "condition": condition,
            "lookupkey": lookup,
            "genes": sorted(condition),
            "pair_evidence": evidence,
            "cpic_level": min(levels, key=LEVEL_ORDER.index) if levels else None,
            "clinpgx_level": next((e["clinpgx_level"] for e in evidence if e["clinpgx_level"]), None),
            "pair_pmids": sorted({p for e in evidence for p in e["citations"]}),
        })
        del r["phenotypes_json"], r["lookupkey_json"]
        matched.append(r)

    # identical advice can appear once per activity-score key; keep one row per distinct context + text
    seen, unique = set(), []
    for r in matched:
        sig = (r["drug"], r["population"], json.dumps(r["condition"], sort_keys=True), r["recommendation"], r["classification"])
        if sig not in seen:
            seen.add(sig)
            unique.append(r)
    return unique


def evidence_for_gene_drug(driver, gene: str, drug_name: str) -> dict | None:
    """The single evidence-graded edge behind a gene-drug pair (CPIC A/B/C/D level +
    citations) -- used by explainability/evidence.py to tag a claim."""
    query = """
        MATCH (g:Gene {symbol: $gene})-[e:ASSOCIATED_WITH]->(d:Drug {name: $drug_name})
        RETURN g.symbol AS gene, d.name AS drug, e.cpic_level AS cpic_level,
               e.clinpgx_level AS clinpgx_level, e.pgx_testing AS pgx_testing,
               e.citations AS citations
    """
    with driver.session() as session:
        record = session.run(query, gene=gene, drug_name=drug_name).single()
        return dict(record) if record else None


def subgraph_for_recommendation(driver, recommendation_id: int) -> dict:
    """Full traceable path behind one recommendation. A recommendation can be gated on several genes
    (e.g. CYP2C19 + CYP2D6 for amitriptyline), so it returns one *branch* per gene in its condition:
    gene <- diplotypes -> phenotype, plus that gene's evidence-graded edge to the drug. Shared parts:
    recommendation -> drug, recommendation -> guideline -> publications, and known ADRs for the drug.
    This is exactly what Layer 4's PyVis renderer draws."""
    query = """
        MATCH (rec:Recommendation {id: $rec_id})-[:RECOMMENDS]->(drug:Drug)
        OPTIONAL MATCH (rec)-[:FOLLOWS_GUIDELINE]->(gl:Guideline)
        OPTIONAL MATCH (gl)-[:CITES]->(pub:Publication)
        OPTIONAL MATCH (drug)-[:CAUSES_ADR]->(adr:ADR)
        WITH rec, drug, gl, collect(DISTINCT pub) AS pubs, collect(DISTINCT adr)[0..15] AS adrs
        MATCH (ph:Phenotype)-[:HAS_RECOMMENDATION]->(rec)
        OPTIONAL MATCH (gene:Gene {symbol: ph.gene})
        OPTIONAL MATCH (gene)-[assoc:ASSOCIATED_WITH]->(drug)
        OPTIONAL MATCH (dip:Diplotype)-[:RESULTS_IN_PHENOTYPE]->(ph)
        WITH rec, drug, gl, pubs, adrs, ph, gene, assoc, collect(DISTINCT dip)[0..4] AS dips
        RETURN rec, drug, gl, pubs, adrs,
               collect({phenotype: ph, gene: gene, evidence: assoc, diplotypes: dips}) AS branches
    """
    with driver.session() as session:
        record = session.run(query, rec_id=recommendation_id).single()
        if not record:
            return {}
        return {
            "recommendation": dict(record["rec"]),
            "drug": dict(record["drug"]),
            "guideline": dict(record["gl"]) if record["gl"] else None,
            "publications": [dict(p) for p in record["pubs"] if p],
            "adrs": [dict(a) for a in record["adrs"] if a],
            "branches": [
                {
                    "phenotype": dict(b["phenotype"]),
                    "gene": dict(b["gene"]) if b["gene"] else None,
                    "evidence": dict(b["evidence"]) if b["evidence"] else None,
                    "diplotypes": [dict(d) for d in b["diplotypes"] if d],
                }
                for b in record["branches"]
            ],
        }


def search_drug_by_gene(driver, gene: str) -> list[dict]:
    """All drugs with a CPIC evidence-graded association to a gene, sorted by evidence
    strength -- useful when Layer 3 needs "what drugs matter for this gene" without a
    specific phenotype yet resolved."""
    query = """
        MATCH (g:Gene {symbol: $gene})-[e:ASSOCIATED_WITH]->(d:Drug)
        RETURN d.name AS drug, d.rxnorm_id AS drug_rxnorm_id,
               e.cpic_level AS cpic_level, e.pgx_testing AS pgx_testing
        ORDER BY e.cpic_level, d.name
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, gene=gene)]


def list_phenotypes_for_gene(driver, gene: str) -> list[dict]:
    """All known phenotype categories for a gene -- lets a caller validate/normalize a
    Layer-1-produced phenotype string against what the graph actually has."""
    query = """
        MATCH (p:Phenotype {gene: $gene})
        RETURN p.id AS id, p.name AS name, p.basis AS basis, p.ehr_priority AS ehr_priority
        ORDER BY p.name
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, gene=gene)]


if __name__ == "__main__":
    d = get_driver()
    try:
        print("Phenotypes known for CYP2D6:")
        print(json.dumps(list_phenotypes_for_gene(d, "CYP2D6"), indent=2))
        print("\nRecommendations for CYP2D6 Poor Metabolizer:")
        print(json.dumps(recommendations_for_phenotype(d, "CYP2D6", "Poor Metabolizer"), indent=2, default=str))
    finally:
        d.close()
