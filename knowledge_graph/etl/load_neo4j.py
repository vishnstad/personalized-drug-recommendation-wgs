"""
Batch-load the normalized node/relationship tables (data/processed/*.json) into
Neo4j via the official Python driver. Idempotent (uses MERGE throughout), so it's
safe to re-run after re-normalizing.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
BATCH_SIZE = 500

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "pgxkgpassword")


def load_json(name: str):
    path = PROCESSED_DIR / name
    if not path.exists():
        print(f"  skip {name} (not found)")
        return []
    return json.loads(path.read_text())


def run_batched(session, query: str, rows: list[dict], label: str) -> None:
    total = len(rows)
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        session.run(query, rows=batch)
    print(f"  {label}: {total} rows")


NODE_LOADERS = [
    ("nodes_gene.json", """
        UNWIND $rows AS row
        MERGE (g:Gene {symbol: row.symbol})
        SET g.hgnc_id = row.hgnc_id, g.name = row.name, g.chromosome = row.chromosome
    """, "Gene nodes"),
    ("nodes_drug.json", """
        UNWIND $rows AS row
        MERGE (d:Drug {rxnorm_id: row.rxnorm_id})
        SET d.name = row.name, d.drugbank_id = row.drugbank_id, d.atc_ids = row.atc_ids
    """, "Drug nodes"),
    ("nodes_guideline.json", """
        UNWIND $rows AS row
        MERGE (g:Guideline {id: row.id})
        SET g.name = row.name, g.url = row.url, g.genes = row.genes
    """, "Guideline nodes"),
    ("nodes_publication.json", """
        UNWIND $rows AS row
        MERGE (p:Publication {pmid: row.pmid})
        SET p.title = row.title, p.year = row.year, p.journal = row.journal,
            p.doi = row.doi, p.url = row.url
    """, "Publication nodes"),
    ("nodes_phenotype.json", """
        UNWIND $rows AS row
        MERGE (p:Phenotype {id: row.id})
        SET p.gene = row.gene, p.name = row.name, p.ehr_priority = row.ehr_priority,
            p.basis = row.basis
    """, "Phenotype nodes"),
    ("nodes_diplotype.json", """
        UNWIND $rows AS row
        MERGE (d:Diplotype {id: row.id})
        SET d.gene = row.gene, d.name = row.name, d.function1 = row.function1,
            d.function2 = row.function2, d.total_activity_score = row.total_activity_score
    """, "Diplotype nodes"),
    ("nodes_recommendation.json", """
        UNWIND $rows AS row
        MERGE (r:Recommendation {id: row.id})
        SET r.drug_recommendation = row.drug_recommendation,
            r.classification = row.classification,
            r.implications = row.implications,
            r.population = row.population,
            r.comments = row.comments,
            r.dosing_information = row.dosing_information,
            r.alternate_drug_available = row.alternate_drug_available
    """, "Recommendation nodes"),
    ("nodes_adr.json", """
        UNWIND $rows AS row
        MERGE (a:ADR {id: row.id})
        SET a.name = row.name, a.meddra_id = row.meddra_id
    """, "ADR nodes"),
]

EDGE_LOADERS = [
    ("edges_gene_associated_with_drug.json", """
        UNWIND $rows AS row
        MATCH (g:Gene {symbol: row.gene}), (d:Drug {rxnorm_id: row.drug_rxnorm_id})
        MERGE (g)-[e:ASSOCIATED_WITH]->(d)
        SET e.cpic_level = row.cpic_level, e.clinpgx_level = row.clinpgx_level,
            e.pgx_testing = row.pgx_testing,
            e.used_for_recommendation = row.used_for_recommendation,
            e.citations = row.citations
    """, "Gene-[:ASSOCIATED_WITH]->Drug"),
    ("edges_gene_has_diplotype.json", """
        UNWIND $rows AS row
        MATCH (g:Gene {symbol: row.gene}), (d:Diplotype {id: row.diplotype_id})
        MERGE (g)-[:HAS_DIPLOTYPE]->(d)
    """, "Gene-[:HAS_DIPLOTYPE]->Diplotype"),
    ("edges_diplotype_results_in_phenotype.json", """
        UNWIND $rows AS row
        MATCH (d:Diplotype {id: row.diplotype_id}), (p:Phenotype {id: row.phenotype_id})
        MERGE (d)-[:RESULTS_IN_PHENOTYPE]->(p)
    """, "Diplotype-[:RESULTS_IN_PHENOTYPE]->Phenotype"),
    ("edges_phenotype_has_recommendation.json", """
        UNWIND $rows AS row
        MATCH (p:Phenotype {id: row.phenotype_id}), (r:Recommendation {id: row.recommendation_id})
        MERGE (p)-[:HAS_RECOMMENDATION]->(r)
    """, "Phenotype-[:HAS_RECOMMENDATION]->Recommendation"),
    ("edges_recommendation_recommends_drug.json", """
        UNWIND $rows AS row
        MATCH (r:Recommendation {id: row.recommendation_id}), (d:Drug {rxnorm_id: row.drug_rxnorm_id})
        MERGE (r)-[:RECOMMENDS]->(d)
    """, "Recommendation-[:RECOMMENDS]->Drug"),
    ("edges_recommendation_follows_guideline.json", """
        UNWIND $rows AS row
        MATCH (r:Recommendation {id: row.recommendation_id}), (g:Guideline {id: row.guideline_id})
        MERGE (r)-[:FOLLOWS_GUIDELINE]->(g)
    """, "Recommendation-[:FOLLOWS_GUIDELINE]->Guideline"),
    ("edges_guideline_cites_publication.json", """
        UNWIND $rows AS row
        MATCH (g:Guideline {id: row.guideline_id}), (p:Publication {pmid: row.pmid})
        MERGE (g)-[:CITES]->(p)
    """, "Guideline-[:CITES]->Publication"),
    ("edges_drug_causes_adr.json", """
        UNWIND $rows AS row
        MATCH (d:Drug {name: row.drug_name}), (a:ADR {id: row.adr_id})
        MERGE (d)-[:CAUSES_ADR]->(a)
    """, "Drug-[:CAUSES_ADR]->ADR"),
]


def main() -> None:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        print("Loading nodes...")
        for filename, query, label in NODE_LOADERS:
            rows = load_json(filename)
            if rows:
                run_batched(session, query, rows, label)

        print("Loading relationships...")
        for filename, query, label in EDGE_LOADERS:
            rows = load_json(filename)
            if rows:
                run_batched(session, query, rows, label)

        print("\nGraph summary:")
        result = session.run("""
            MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC
        """)
        for record in result:
            print(f"  {record['label']}: {record['n']}")
        result = session.run("""
            MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC
        """)
        for record in result:
            print(f"  [{record['rel']}]: {record['n']}")
    driver.close()


if __name__ == "__main__":
    main()
