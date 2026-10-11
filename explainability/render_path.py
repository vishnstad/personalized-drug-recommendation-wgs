"""
Render the exact subgraph behind one recommendation as an interactive PyVis HTML page --
"show your work" for a drug recommendation, so a clinician can see precisely which
gene/diplotype/phenotype/guideline led to it (not just trust the LLM's prose).

Usage:
    python3 explainability/render_path.py <recommendation_id> [output.html]
"""
import sys
from pathlib import Path

from pyvis.network import Network

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrieval.queries import get_driver, subgraph_for_recommendation  # noqa: E402

COLORS = {
    "Gene": "#4C72B0",
    "Diplotype": "#55A868",
    "Phenotype": "#C44E52",
    "Recommendation": "#8172B2",
    "Drug": "#CCB974",
    "Guideline": "#64B5CD",
    "Publication": "#8C8C8C",
    "ADR": "#DD8452",
}


def render(subgraph: dict, out_path: Path) -> None:
    net = Network(height="750px", width="100%", directed=True, bgcolor="#ffffff", font_color="#222222")
    net.barnes_hut(gravity=-4000, spring_length=150)

    def add_node(node_id: str, label: str, kind: str, title: str = "") -> None:
        net.add_node(node_id, label=label, color=COLORS.get(kind, "#999999"), title=title or label, shape="dot", size=18)

    gene = subgraph.get("gene")
    phenotype = subgraph["phenotype"]
    recommendation = subgraph["recommendation"]
    drug = subgraph["drug"]
    guideline = subgraph.get("guideline")
    evidence = subgraph.get("evidence")

    phenotype_id = f"phenotype:{phenotype['id']}"
    add_node(phenotype_id, phenotype["name"], "Phenotype",
              title=f"{phenotype['gene']} — {phenotype['name']} (basis: {phenotype.get('basis')})")

    if gene:
        gene_id = f"gene:{gene['symbol']}"
        add_node(gene_id, gene["symbol"], "Gene", title=f"HGNC: {gene.get('hgnc_id')}")
        for dip in subgraph.get("diplotypes", []):
            dip_id = f"diplotype:{dip['id']}"
            add_node(dip_id, dip["name"], "Diplotype",
                      title=f"function: {dip.get('function1')}/{dip.get('function2')}")
            net.add_edge(gene_id, dip_id, label="HAS_DIPLOTYPE")
            net.add_edge(dip_id, phenotype_id, label="RESULTS_IN_PHENOTYPE")
        if evidence:
            drug_id = f"drug:{drug['rxnorm_id']}"
            add_node(drug_id, drug["name"], "Drug", title=drug["rxnorm_id"])
            level = evidence.get("cpic_level") or "?"
            net.add_edge(gene_id, drug_id, label=f"ASSOCIATED_WITH (CPIC {level})")

    rec_id = f"recommendation:{recommendation['id']}"
    rec_label = (recommendation.get("drug_recommendation") or "")[:60]
    add_node(rec_id, rec_label + ("…" if len(recommendation.get("drug_recommendation") or "") > 60 else ""),
              "Recommendation", title=recommendation.get("drug_recommendation"))
    net.add_edge(phenotype_id, rec_id, label="HAS_RECOMMENDATION")

    drug_id = f"drug:{drug['rxnorm_id']}"
    add_node(drug_id, drug["name"], "Drug", title=drug["rxnorm_id"])
    net.add_edge(rec_id, drug_id, label="RECOMMENDS")

    if guideline:
        gl_id = f"guideline:{guideline['id']}"
        add_node(gl_id, guideline["name"], "Guideline", title=guideline.get("url") or "")
        net.add_edge(rec_id, gl_id, label="FOLLOWS_GUIDELINE")
        for pub in subgraph.get("publications", []):
            pub_id = f"publication:{pub['pmid']}"
            add_node(pub_id, f"PMID {pub['pmid']}", "Publication", title=pub.get("title") or "")
            net.add_edge(gl_id, pub_id, label="CITES")

    for adr in subgraph.get("adrs", []):
        adr_id = f"adr:{adr['id']}"
        add_node(adr_id, adr["name"], "ADR")
        net.add_edge(drug_id, adr_id, label="CAUSES_ADR")

    net.set_options("""
    {
      "physics": {"stabilization": {"iterations": 150}},
      "edges": {"font": {"size": 10, "align": "middle"}, "color": {"color": "#bbbbbb"}}
    }
    """)
    net.write_html(str(out_path), open_browser=False, notebook=False)
    print(f"Wrote {out_path}")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: render_path.py <recommendation_id> [output.html]", file=sys.stderr)
        sys.exit(1)
    rec_id = int(sys.argv[1])
    default_dir = Path(__file__).resolve().parent / "output"
    default_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else default_dir / f"path_{rec_id}.html"

    driver = get_driver()
    try:
        subgraph = subgraph_for_recommendation(driver, rec_id)
        if not subgraph:
            print(f"No recommendation found with id={rec_id}", file=sys.stderr)
            sys.exit(1)
        render(subgraph, out_path)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
