"""
Hybrid Retrieval Engine (Layer 3): Graph Path Retrieval + Vector Document Search (per PGxRAG).

Combines:
1. Structured Cypher path retrieval from the Neo4j Pharmacogenomic Knowledge Graph (queries.py)
2. Unstructured vector search over CPIC guidelines, clinical implications, and dosing texts using ChromaDB.

Produces an enriched, multi-hop context for the LLM that grounds both structured relations
(Gene -> Phenotype -> Recommendation -> Drug -> Guideline -> Publication) and nuanced guideline text.
"""

import json
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb.config import Settings

ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = ROOT / "data" / "chroma_db"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# Curated reference guidelines and clinical implications for project pharmacogenes
CORE_GUIDELINE_CORPUS = [
    {
        "id": "cpic_cyp2c19_clopidogrel",
        "gene": "CYP2C19",
        "drug": "clopidogrel",
        "text": "CPIC Guideline for CYP2C19 and Clopidogrel Therapy: Clopidogrel is an antiplatelet prodrug requiring CYP2C19 bioactivation. In CYP2C19 intermediate and poor metabolizers, significantly reduced active metabolite formation leads to diminished platelet inhibition and increased risk of major adverse cardiovascular events (MACE) and stent thrombosis. CPIC recommends choosing an alternative antiplatelet agent (e.g., prasugrel or ticagrelor) in acute coronary syndrome patients undergoing PCI.",
        "cpic_level": "A",
        "citations": ["PMID:23698643", "PMID:35032049"],
    },
    {
        "id": "cpic_cyp2c19_voriconazole",
        "gene": "CYP2C19",
        "drug": "voriconazole",
        "text": "CPIC Guideline for CYP2C19 and Voriconazole: Voriconazole is primarily metabolized by CYP2C19. In CYP2C19 poor and intermediate metabolizers, significantly elevated drug exposure increases the risk of neurotoxicity and hepatotoxicity. In ultrarapid metabolizers, reduced exposure increases risk of therapeutic failure. In poor metabolizers, choose an alternative antifungal agent (e.g. isavuconazole, liposomal amphotericin B) not dependent on CYP2C19.",
        "cpic_level": "A",
        "citations": ["PMID:27981716"],
    },
    {
        "id": "cpic_cyp2c19_ppis",
        "gene": "CYP2C19",
        "drug": "omeprazole",
        "text": "CPIC Guideline for CYP2C19 and Proton Pump Inhibitors (omeprazole, lansoprazole, pantoprazole, dexlansoprazole, esomeprazole): Poor and intermediate metabolizers have higher drug exposure and increased intragastric pH, allowing lower or standard doses. Ultrarapid and rapid metabolizers have lower drug concentrations and higher risk of treatment failure in H. pylori eradication and GERD; dose increases of 50-100% are recommended.",
        "cpic_level": "A",
        "citations": ["PMID:32711538"],
    },
    {
        "id": "cpic_cyp2d6_codeine",
        "gene": "CYP2D6",
        "drug": "codeine",
        "text": "CPIC Guideline for CYP2D6 and Codeine: Codeine is a prodrug bioactivated to morphine by CYP2D6. Poor metabolizers experience lack of analgesia due to negligible morphine formation (avoid codeine; choose non-tramadol alternative analgesic). Ultrarapid metabolizers experience rapid and excessive morphine conversion leading to severe or fatal respiratory depression even at standard doses (avoid codeine).",
        "cpic_level": "A",
        "citations": ["PMID:22378137", "PMID:24458010", "PMID:31562822"],
    },
    {
        "id": "cpic_cyp2d6_tramadol",
        "gene": "CYP2D6",
        "drug": "tramadol",
        "text": "CPIC Guideline for CYP2D6 and Tramadol: Tramadol requires CYP2D6 metabolism to its active analgesic metabolite O-desmethyltramadol (M1). In poor metabolizers, analgesia is diminished. In ultrarapid metabolizers, risk of opioid toxicity and respiratory depression is markedly increased. Avoid tramadol in both poor and ultrarapid metabolizers.",
        "cpic_level": "A",
        "citations": ["PMID:31562822"],
    },
    {
        "id": "cpic_cyp2d6_tamoxifen",
        "gene": "CYP2D6",
        "drug": "tamoxifen",
        "text": "CPIC Guideline for CYP2D6 and Tamoxifen Therapy in Breast Cancer: Tamoxifen is bioactivated to its potent active antiestrogen metabolite endoxifen by CYP2D6. Poor metabolizers exhibit significantly lower endoxifen concentrations and poorer recurrence-free survival. In poor metabolizers, an alternative endocrine therapy (such as an aromatase inhibitor) or dose increase should be considered. Moderate and strong CYP2D6 inhibitors should be avoided.",
        "cpic_level": "A",
        "citations": ["PMID:29707797"],
    },
    {
        "id": "cpic_cyp2d6_cyp2c19_tcas",
        "gene": "CYP2D6",
        "drug": "amitriptyline",
        "text": "CPIC Guideline for CYP2D6 and CYP2C19 and Tricyclic Antidepressants (amitriptyline, nortriptyline, imipramine): Tertiary amines (amitriptyline, imipramine) are demethylated by CYP2C19 to active secondary amines (nortriptyline, desipramine) and hydroxylated to inactive metabolites by CYP2D6. In CYP2D6 or CYP2C19 poor metabolizers, toxicity risk is elevated; dose reductions or alternative agents not metabolized by these enzymes are recommended.",
        "cpic_level": "A",
        "citations": ["PMID:27997040"],
    },
    {
        "id": "cpic_cyp2d6_cyp2c19_ssris",
        "gene": "CYP2C19",
        "drug": "citalopram",
        "text": "CPIC Guideline for CYP2C19 and CYP2D6 and SSRIs (citalopram, escitalopram, sertraline, paroxetine): Citalopram and escitalopram are predominantly cleared by CYP2C19. In CYP2C19 poor metabolizers, prolonged QT interval and torsades de pointes risk is increased; reduce starting dose by 50%. Paroxetine is a substrate and strong inhibitor of CYP2D6.",
        "cpic_level": "A",
        "citations": ["PMID:25974703"],
    },
    {
        "id": "cpic_cyp2d6_atomoxetine",
        "gene": "CYP2D6",
        "drug": "atomoxetine",
        "text": "CPIC Guideline for CYP2D6 and Atomoxetine: Atomoxetine is primarily metabolized by CYP2D6. Poor metabolizers exhibit 10-fold higher exposure and higher risk of adverse effects (insomnia, dry mouth, increased heart rate). CPIC recommends initiating therapy at a standard starting dose with slower titration schedule and lower target dose in poor and intermediate metabolizers.",
        "cpic_level": "A",
        "citations": ["PMID:30802956"],
    },
    {
        "id": "cpic_cyp2d6_ondansetron",
        "gene": "CYP2D6",
        "drug": "ondansetron",
        "text": "CPIC Guideline for CYP2D6 and 5-HT3 Receptor Antagonists (ondansetron, tropisetron): Ondansetron is cleared by CYP2D6. Ultrarapid metabolizers experience accelerated clearance and reduced antiemetic efficacy; choose alternative agent not predominantly metabolized by CYP2D6 (e.g. granisetron).",
        "cpic_level": "A",
        "citations": ["PMID:27003438"],
    },
]


class HybridRetriever:
    """Orchestrates structured Knowledge Graph path retrieval alongside vector search over guideline documents."""

    def __init__(self, chroma_path: Path = CHROMA_DIR):
        self.chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        self.collection = self.chroma_client.get_or_create_collection(
            name="cpic_guidelines",
            metadata={"description": "CPIC clinical pharmacogenomics guidelines and recommendations"},
        )
        self._ensure_corpus_indexed()

    def _ensure_corpus_indexed(self) -> None:
        """Seed the vector collection with CPIC guideline excerpts if empty."""
        count = self.collection.count()
        if count == 0:
            ids = [doc["id"] for doc in CORE_GUIDELINE_CORPUS]
            documents = [doc["text"] for doc in CORE_GUIDELINE_CORPUS]
            metadatas = [
                {
                    "gene": doc["gene"],
                    "drug": doc["drug"],
                    "cpic_level": doc["cpic_level"],
                    "citations": ",".join(doc["citations"]),
                }
                for doc in CORE_GUIDELINE_CORPUS
            ]
            self.collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def retrieve_guideline_text(self, query: str, top_k: int = 3, filter_gene: Optional[str] = None) -> list[dict[str, Any]]:
        """Perform semantic vector retrieval over CPIC guideline corpus."""
        where = {"gene": filter_gene} if filter_gene else None
        results = self.collection.query(query_texts=[query], n_results=top_k, where=where)

        docs = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc_id = results["ids"][0][i] if results["ids"] else ""
                dist = results["distances"][0][i] if results.get("distances") else None
                docs.append({
                    "id": doc_id,
                    "text": doc,
                    "gene": meta.get("gene"),
                    "drug": meta.get("drug"),
                    "cpic_level": meta.get("cpic_level"),
                    "citations": meta.get("citations", "").split(",") if meta.get("citations") else [],
                    "relevance_distance": dist,
                })
        return docs

    def retrieve_hybrid_context(
        self,
        driver: Any,
        phenotypes: dict[str, str],
        candidate_drugs: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Combine structured Neo4j graph retrieval with vector guideline context."""
        from retrieval import queries

        structured_results = {}
        text_excerpts = []

        for gene, phenotype in phenotypes.items():
            # 1. Graph retrieval
            try:
                rows = queries.recommendations_for_phenotype(driver, gene, phenotype)
            except Exception:
                rows = []
            structured_results[gene] = rows

            # 2. Vector text retrieval for this gene and phenotype
            query_str = f"{gene} {phenotype} dosing recommendations and adverse drug interactions"
            matched_docs = self.retrieve_guideline_text(query_str, top_k=2, filter_gene=gene)
            text_excerpts.extend(matched_docs)

        return {
            "phenotypes": phenotypes,
            "structured_graph_rows": structured_results,
            "vector_guideline_excerpts": text_excerpts,
        }
