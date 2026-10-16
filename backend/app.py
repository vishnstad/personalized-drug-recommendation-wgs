"""
Layer 5 backend: FastAPI service over the pipeline (Layer 1 profile -> Layer 2/3 ranking -> Layer 4 graph),
plus the web UI (frontend/, served at /).

    uvicorn backend.app:app --host 0.0.0.0 --port 8010      (repo root; or `docker compose up backend`)

API (all under /api; interactive docs at /docs)
  GET  /api/health                      Neo4j / LLM / PharmCAT status
  GET  /api/samples                     1000 Genomes samples (+ whether a profile is cached)
  GET  /api/phenotypes/{gene}           valid CPIC phenotype names (manual entry)
  POST /api/profile/{sample_id}         Layer 1: VCF slice -> PharmCAT -> annotated profile (cached)
  POST /api/recommend                   ranked, evidence-tagged recommendations (graph rationales, instant)
  POST /api/explain                     LLM explanation for one drug (detailed sections or brief), faithfulness-gated, cached
  GET  /api/graph/{recommendation_id}   evidence path as graph elements (nodes/edges) for the UI
  GET  /api/graph/{id}/html             same path as a standalone PyVis page
  GET  /api/kg/stats                    node / relationship counts of the loaded knowledge graph
  GET  /api/kg/gene/{gene}              gene -> drug evidence edges (CPIC level) for the graph explorer
"""
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from genomic.patient_profile import DEFAULT_OUT_DIR, load_or_generate_profile, load_pedigree_metadata  # noqa: E402
from genomic.toolchain import PHARMCAT_JAR  # noqa: E402
from llm import client  # noqa: E402
from llm import recommend as rec  # noqa: E402
from retrieval.queries import get_driver, list_phenotypes_for_gene, subgraph_for_recommendation  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pgx")
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["driver"] = get_driver()
    state["samples"] = load_pedigree_metadata()
    log.info("startup | samples=%d neo4j=%s llm=%s model=%s pharmcat_jar=%s",
             len(state["samples"]), os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
             client.BASE_URL, client.MODEL, PHARMCAT_JAR.exists())
    yield
    state["driver"].close()


app = FastAPI(title="PGx Recommender API", version="1.0", lifespan=lifespan)
api = APIRouter(prefix="/api")


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        log.info("http | %s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000)
    return response


class RecommendRequest(BaseModel):
    sample_id: Optional[str] = Field(None, description="1000 Genomes sample; runs/loads its Layer 1 profile")
    phenotypes: Optional[dict[str, str]] = Field(None, description='Manual entry, e.g. {"CYP2D6": "Poor Metabolizer"}')
    activity_scores: Optional[dict[str, float]] = None


class ExplainRequest(BaseModel):
    phenotypes: dict[str, str]
    activity_scores: Optional[dict[str, float]] = None
    drug: str
    detail: str = Field("detailed", description='"detailed" (six sections) or "brief" (2-3 sentences)')
    sample_id: Optional[str] = Field(None, description="adds the patient's alleles and their functions to the evidence")


def _profile(sample_id: str, force: bool = False) -> dict:
    if sample_id not in state["samples"]:
        raise HTTPException(404, f"Unknown 1000 Genomes sample '{sample_id}'")
    cached = (DEFAULT_OUT_DIR / sample_id / f"{sample_id}_patient_profile.json").exists() and not force
    t0 = time.perf_counter()
    try:
        p = load_or_generate_profile(sample_id, force=force)
    except Exception as exc:  # bcftools/PharmCAT failures carry their stderr
        log.error("layer1 | %s failed: %s", sample_id, str(exc).splitlines()[0])
        raise HTTPException(500, f"Layer 1 failed for {sample_id}: {exc}")
    calls = ", ".join(f"{g} {d['diplotype']} -> {d['phenotype']}" for g, d in p["genes"].items())
    log.info("layer1 | %s %s in %.1fs | %s", sample_id, "cached" if cached else "bcftools+PharmCAT",
             time.perf_counter() - t0, calls)
    return p


@api.get("/health")
def health():
    try:
        state["driver"].verify_connectivity()
        neo4j = True
    except Exception:
        neo4j = False
    return {"neo4j": neo4j, "llm": client.available(), "llm_model": client.MODEL, "llm_url": client.BASE_URL,
            "pharmcat_jar": PHARMCAT_JAR.exists()}


@api.get("/samples")
def samples():
    out = []
    for sid, meta in state["samples"].items():
        cached = (DEFAULT_OUT_DIR / sid / f"{sid}_patient_profile.json").exists()
        out.append({**meta, "profile_cached": cached})
    return out


@api.get("/phenotypes/{gene}")
def phenotypes(gene: str):
    return [p["name"] for p in list_phenotypes_for_gene(state["driver"], gene)]


@api.post("/profile/{sample_id}")
def profile(sample_id: str, force: bool = False):
    return _profile(sample_id, force)


@api.post("/recommend")
def recommend(req: RecommendRequest):
    t0 = time.perf_counter()
    if req.sample_id:
        p = _profile(req.sample_id)
        result = rec.recommend(state["driver"], p["phenotypes"], sample_id=p["sample_id"],
                               demographics=p["demographics"], diplotypes=p["diplotypes"],
                               activity_scores=rec.activity_scores_from_profile(p), strict=False)
        result["profile"] = p
    elif req.phenotypes:
        try:
            result = rec.recommend(state["driver"], req.phenotypes, activity_scores=req.activity_scores)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    else:
        raise HTTPException(422, "Provide sample_id or phenotypes")
    actions = {}
    for r in result["recommendations"]:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    log.info("layer3 | %s | %d drugs %s | %d rows filtered | %.2fs", req.sample_id or result["patient_phenotypes"],
             result["n_drugs"], actions, len(result["filtered_out"]), time.perf_counter() - t0)
    return result


@api.post("/explain")
def explain(req: ExplainRequest):
    t0 = time.perf_counter()
    genotypes = rec.genotypes_from_profile(_profile(req.sample_id)) if req.sample_id else None
    try:
        ex = rec.explain_drug(state["driver"], req.phenotypes, req.drug, req.activity_scores,
                              use_llm=client.available(), detail=req.detail, genotypes=genotypes)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    rejected = ex.get("rejected_llm_output")
    reason = rejected.get("problems") if isinstance(rejected, dict) else rejected
    log.info("llm | %s | %s | model=%s source=%s words=%d%s | %.1fs", req.drug, req.detail, client.MODEL, ex["source"],
             len(ex["text"].split()), f" rejected={reason}" if reason else "", time.perf_counter() - t0)
    return ex


@api.get("/graph/{recommendation_id}")
def graph(recommendation_id: int, sample_id: Optional[str] = None):
    """Evidence path as typed nodes/edges (rendered client-side)."""
    sub = subgraph_for_recommendation(state["driver"], recommendation_id)
    if not sub:
        raise HTTPException(404, f"No recommendation {recommendation_id}")
    nodes, edges = {}, []

    def node(nid, label, kind, **data):
        nodes.setdefault(nid, {"id": nid, "label": label, "type": kind, **data})

    r, d = sub["recommendation"], sub["drug"]
    rid, did = f"rec:{r['id']}", f"drug:{d['rxnorm_id']}"
    node(rid, r.get("classification") or "Recommendation", "Recommendation",
         text=r.get("drug_recommendation"), population=r.get("population"), classification=r.get("classification"))
    node(did, d["name"], "Drug", ident=d["rxnorm_id"])
    edges.append({"source": rid, "target": did, "label": "RECOMMENDS"})
    patient = _profile(sample_id) if sample_id else None
    if patient:
        node("patient", sample_id, "Patient")
    for b in sub["branches"]:
        ph, gene, ev = b["phenotype"], b.get("gene"), b.get("evidence")
        pid = f"ph:{ph['id']}"
        node(pid, ph["name"], "Phenotype", gene=ph["gene"])
        edges.append({"source": pid, "target": rid, "label": "HAS_RECOMMENDATION"})
        if gene:
            gid = f"gene:{gene['symbol']}"
            node(gid, gene["symbol"], "Gene", ident=gene.get("hgnc_id"))
            if patient and gene["symbol"] in patient["diplotypes"]:
                dip = patient["diplotypes"][gene["symbol"]]
                did_ = f"pdip:{gene['symbol']}"
                node(did_, dip, "Diplotype", own=True)
                edges += [{"source": "patient", "target": did_, "label": "HAS_GENOTYPE"},
                          {"source": gid, "target": did_, "label": "HAS_DIPLOTYPE"},
                          {"source": did_, "target": pid, "label": "RESULTS_IN_PHENOTYPE"}]
            else:
                edges.append({"source": gid, "target": pid, "label": "HAS_PHENOTYPE"})
            if ev:
                edges.append({"source": gid, "target": did, "label": f"CPIC level {ev.get('cpic_level') or '?'}",
                              "kind": "ASSOCIATED_WITH"})
    if sub.get("guideline"):
        gl = sub["guideline"]
        glid = f"gl:{gl['id']}"
        node(glid, gl["name"], "Guideline", url=gl.get("url"))
        edges.append({"source": rid, "target": glid, "label": "FOLLOWS_GUIDELINE"})
        for pub in sub["publications"]:
            pubid = f"pmid:{pub['pmid']}"
            node(pubid, f"PMID {pub['pmid']}", "Publication", title=pub.get("title"), year=pub.get("year"))
            edges.append({"source": glid, "target": pubid, "label": "CITES"})
    for adr in sub["adrs"][:8]:
        aid = f"adr:{adr['id']}"
        node(aid, adr["name"], "ADR")
        edges.append({"source": did, "target": aid, "label": "CAUSES_ADR"})
    return {"nodes": list(nodes.values()), "edges": edges}


@api.get("/graph/{recommendation_id}/html", response_class=HTMLResponse)
def graph_html(recommendation_id: int, sample_id: Optional[str] = None):
    from explainability.render_path import render_html

    sub = subgraph_for_recommendation(state["driver"], recommendation_id)
    if not sub:
        raise HTTPException(404, f"No recommendation {recommendation_id}")
    patient = {"id": sample_id, "diplotypes": _profile(sample_id).get("diplotypes", {})} if sample_id else None
    return render_html(sub, patient)


@api.get("/kg/stats")
def kg_stats():
    with state["driver"].session() as s:
        nodes = {r["label"]: r["n"] for r in s.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n")}
        rels = {r["type"]: r["n"] for r in s.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n")}
    return {"nodes": nodes, "relationships": rels}


@api.get("/kg/gene/{gene}")
def kg_gene(gene: str):
    """Every drug with a CPIC evidence-graded association to this gene, and the gene's phenotype categories."""
    with state["driver"].session() as s:
        drugs = [dict(r) for r in s.run(
            """MATCH (g:Gene {symbol: $gene})-[e:ASSOCIATED_WITH]->(d:Drug)
               OPTIONAL MATCH (d)<-[:RECOMMENDS]-(r:Recommendation)<-[:HAS_RECOMMENDATION]-(:Phenotype {gene: $gene})
               RETURN d.name AS drug, e.cpic_level AS cpic_level, count(DISTINCT r) AS recommendations
               ORDER BY drug""", gene=gene)]
        phenotypes = [dict(r) for r in s.run(
            """MATCH (p:Phenotype {gene: $gene})
               OPTIONAL MATCH (p)-[:HAS_RECOMMENDATION]->(r:Recommendation)
               RETURN p.name AS name, count(r) AS recommendations ORDER BY name""", gene=gene)]
    return {"gene": gene, "drugs": drugs, "phenotypes": phenotypes}


app.include_router(api)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="ui")
