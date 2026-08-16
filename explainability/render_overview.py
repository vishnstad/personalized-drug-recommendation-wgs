"""
Ad-hoc overview render: a curated slice of the knowledge graph -- several
high-evidence (CPIC level A) genes, their drugs, and phenotypes -- to show the KG's
breadth in one image. Not part of the Layer 4 pipeline proper (that's
render_path.py, which renders the exact subgraph behind ONE recommendation); this is
a presentation/demo view over the same live Neo4j data.
"""
import sys
from pathlib import Path

from pyvis.network import Network

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.queries import get_driver  # noqa: E402

GENES = ["CYP2D6", "CYP2C19", "CYP2C9", "TPMT", "DPYD", "SLCO1B1", "HLA-B", "VKORC1"]

COLORS = {"Gene": "#4C72B0", "Phenotype": "#C44E52", "Drug": "#CCB974"}

QUERY = """
    MATCH (g:Gene)-[assoc:ASSOCIATED_WITH {cpic_level: 'A'}]->(d:Drug)
    WHERE g.symbol IN $genes
    WITH g, assoc, d
    ORDER BY d.name
    WITH g, collect({drug: d, assoc: assoc})[0..4] AS drugs
    OPTIONAL MATCH (p:Phenotype {gene: g.symbol})
    RETURN g AS gene, drugs, collect(DISTINCT p)[0..5] AS phenotypes
"""


def main() -> None:
    driver = get_driver()
    net = Network(height="900px", width="100%", directed=True, bgcolor="#ffffff", font_color="#222222")
    net.barnes_hut(gravity=-6000, spring_length=180, spring_strength=0.02)

    def add_node(node_id, label, kind, title=""):
        net.add_node(node_id, label=label, color=COLORS[kind], title=title or label, shape="dot",
                     size=26 if kind == "Gene" else 14)

    with driver.session() as session:
        for record in session.run(QUERY, genes=GENES):
            gene = record["gene"]
            gene_id = f"gene:{gene['symbol']}"
            add_node(gene_id, gene["symbol"], "Gene", title=f"HGNC: {gene.get('hgnc_id')}")
            for row in record["drugs"]:
                drug, assoc = row["drug"], row["assoc"]
                if not drug:
                    continue
                drug_id = f"drug:{drug['rxnorm_id']}"
                add_node(drug_id, drug["name"], "Drug", title=drug["rxnorm_id"])
                net.add_edge(gene_id, drug_id, label=f"CPIC {assoc.get('cpic_level')}", color="#999999")
            for phen in record["phenotypes"]:
                if not phen:
                    continue
                phen_id = f"phenotype:{phen['id']}"
                add_node(phen_id, phen["name"], "Phenotype")
                net.add_edge(gene_id, phen_id, label="", color="#dddddd")
    driver.close()

    net.set_options("""
    {
      "physics": {"stabilization": {"iterations": 200}},
      "edges": {"font": {"size": 9, "align": "middle"}, "color": {"color": "#bbbbbb"}}
    }
    """)
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "overview.html"
    net.write_html(str(out), open_browser=False, notebook=False)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
