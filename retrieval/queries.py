"""
Cypher path-retrieval layer (Layer 2's interface to Layer 3).

Layer 3's RAG orchestrator calls these functions with a patient's pharmacogene
phenotypes (already resolved upstream by Layer 1 / PharmCAT) and gets back the
relevant subgraph: gene -> diplotype -> phenotype -> recommendation -> drug, plus
evidence-graded gene-drug associations and known ADRs. Every function returns plain
dicts/lists (not driver Record objects) so they're safe to json.dumps() straight into
an LLM prompt.
"""
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
    """Full traceable path behind one recommendation: phenotype <- diplotype <- gene,
    recommendation -> drug, recommendation -> guideline -> publications, plus any known
    ADRs for the recommended drug. This is exactly what Layer 4's PyVis renderer draws."""
    query = """
        MATCH (rec:Recommendation {id: $rec_id})
        MATCH (ph:Phenotype)-[:HAS_RECOMMENDATION]->(rec)
        MATCH (rec)-[:RECOMMENDS]->(drug:Drug)
        OPTIONAL MATCH (dip:Diplotype)-[:RESULTS_IN_PHENOTYPE]->(ph)
        OPTIONAL MATCH (gene:Gene {symbol: ph.gene})-[:HAS_DIPLOTYPE]->(dip)
        OPTIONAL MATCH (rec)-[:FOLLOWS_GUIDELINE]->(gl:Guideline)
        OPTIONAL MATCH (gl)-[:CITES]->(pub:Publication)
        OPTIONAL MATCH (gene2:Gene {symbol: ph.gene})-[assoc:ASSOCIATED_WITH]->(drug)
        OPTIONAL MATCH (drug)-[:CAUSES_ADR]->(adr:ADR)
        RETURN ph, collect(DISTINCT dip) AS diplotypes, gene AS gene_node,
               rec, drug, gl, collect(DISTINCT pub) AS publications,
               assoc, collect(DISTINCT adr)[0..15] AS adrs
    """
    with driver.session() as session:
        record = session.run(query, rec_id=recommendation_id).single()
        if not record:
            return {}
        return {
            "phenotype": dict(record["ph"]),
            "diplotypes": [dict(d) for d in record["diplotypes"] if d],
            "gene": dict(record["gene_node"]) if record["gene_node"] else None,
            "recommendation": dict(record["rec"]),
            "drug": dict(record["drug"]),
            "guideline": dict(record["gl"]) if record["gl"] else None,
            "publications": [dict(p) for p in record["publications"] if p],
            "evidence": dict(record["assoc"]) if record["assoc"] else None,
            "adrs": [dict(a) for a in record["adrs"] if a],
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
    import json

    d = get_driver()
    try:
        print("Phenotypes known for CYP2D6:")
        print(json.dumps(list_phenotypes_for_gene(d, "CYP2D6"), indent=2))
        print("\nRecommendations for CYP2D6 Poor Metabolizer:")
        print(json.dumps(recommendations_for_phenotype(d, "CYP2D6", "Poor Metabolizer"), indent=2, default=str))
    finally:
        d.close()
