"use strict";
// Web UI for the PGx pipeline. Talks only to the FastAPI backend under /api.

// ------------------------------------------------------------------ reference data
const GENES = ["CYP2C19", "CYP2D6"];
const GENE_INFO = { // NCBI Gene, GRCh38 (genomic/gene_coordinates.json)
  CYP2C19: { chrom: "chr10", start: 94762681, end: 94855547, strand: "+" },
  CYP2D6: { chrom: "chr22", start: 42126499, end: 42130810, strand: "−" },
};
const STEPS = ["genome", "genotype", "graph", "recs", "method"];
const STEP_NAME = { genome: "Genome", genotype: "Genotype", graph: "Knowledge graph", recs: "Recommendations", method: "Method" };
const ACTION_ORDER = ["avoid", "review", "adjust", "standard", "none"];
const ACTIONS = {
  avoid: { label: "Avoid", icon: "✕", desc: "CPIC advises choosing an alternative drug." },
  review: { label: "Review", icon: "!", desc: "Mixed advice (e.g. lower the dose or switch drug); needs clinical judgement." },
  adjust: { label: "Adjust dose", icon: "±", desc: "Use, but with a changed starting dose or titration." },
  standard: { label: "Standard", icon: "✓", desc: "Use label-recommended dosing." },
  none: { label: "No recommendation", icon: "–", desc: "CPIC makes no recommendation for this genotype." },
};
const STATUS = { avoid: "#d03b3b", review: "#ec835a", adjust: "#fab219", standard: "#0ca30c", none: "#898781" };
const STATUS_TINT = { avoid: "#fbe7e7", review: "#fdeee7", adjust: "#fef4dd", standard: "#e2f5e2", none: "#efefed" };
const TYPE_COLOR = { // fill, border (validated categorical slots; neutrals for secondary node types)
  Patient: ["#0b0b0b", "#0b0b0b"], Gene: ["#dbe9fa", "#2a78d6"], Diplotype: ["#d6f2e7", "#1baf7a"],
  Phenotype: ["#e4e0fa", "#6250d6"], Recommendation: ["#ecebe7", "#52514e"], Guideline: ["#fbe4ed", "#e87ba4"],
  Publication: ["#ffffff", "#c3c2b7"], ADR: ["#ffffff", "#c3c2b7"], Drug: ["#ffffff", "#898781"],
};
const TYPE_NAME = { Diplotype: "Genotype", ADR: "Adverse reaction" };
// Allele-defining variants (PharmVar / CPIC allele definitions), used only to annotate what the patient carries.
const KNOWN = {
  rs4244285: ["*2", "681G>A, splicing defect: no function"],
  rs4986893: ["*3", "636G>A, premature stop: no function"],
  rs12248560: ["*17", "-806C>T, more transcription: increased function"],
  rs12769205: ["", "intronic variant on the *2 haplotype"],
  rs3758581: ["", "I331V, on most CYP2C19 haplotypes (the GRCh38 base is the rare allele)"],
  rs3892097: ["*4", "1846G>A, splicing defect: no function"],
  rs35742686: ["*3", "2549delA, frameshift: no function"],
  rs5030655: ["*6", "1707delT, frameshift: no function"],
  rs1065852: ["*10", "100C>T (P34S), core variant of *10, also on *4"],
  rs28371725: ["*41", "2988G>A, reduced splicing: decreased function"],
  rs16947: ["*2", "2850C>T (R296C), on *2 and *41"],
  rs28371706: ["*17", "1023C>T (T107I): decreased function"],
  rs1135840: ["", "4180G>C (S486T), common on *2, *4, *10, *41"],
};
const POPULATIONS = {
  ACB: "African Caribbean in Barbados", ASW: "African Ancestry in SW USA", ESN: "Esan in Nigeria",
  GWD: "Gambian in Western Division", LWK: "Luhya in Webuye, Kenya", MSL: "Mende in Sierra Leone",
  YRI: "Yoruba in Ibadan, Nigeria", CLM: "Colombian in Medellín", MXL: "Mexican Ancestry in Los Angeles",
  PEL: "Peruvian in Lima", PUR: "Puerto Rican in Puerto Rico", CDX: "Chinese Dai in Xishuangbanna",
  CHB: "Han Chinese in Beijing", CHS: "Southern Han Chinese", JPT: "Japanese in Tokyo",
  KHV: "Kinh in Ho Chi Minh City", CEU: "Utah residents, N. & W. European ancestry", FIN: "Finnish in Finland",
  GBR: "British in England and Scotland", IBS: "Iberian in Spain", TSI: "Toscani in Italy",
  BEB: "Bengali in Bangladesh", GIH: "Gujarati Indian in Houston", ITU: "Indian Telugu in the UK",
  PJL: "Punjabi in Lahore, Pakistan", STU: "Sri Lankan Tamil in the UK",
};
const SUPERPOP = { AFR: "African", AMR: "Admixed American", EAS: "East Asian", EUR: "European", SAS: "South Asian" };
// Example genomes for the start page (calls from docs/evaluation.md; NA12878 is a GeT-RM reference sample).
const EXAMPLES = [
  { id: "NA12878", why: "CYP2D6 *3/*4, poor metabolizer. A GeT-RM reference genome with a known CYP2D6 genotype." },
  { id: "HG01583", why: "CYP2C19 *2/*2, poor metabolizer: clopidogrel cannot be activated." },
  { id: "HG01879", why: "CYP2C19 *17/*17, ultrarapid metabolizer: the opposite end of the scale." },
  { id: "HG00096", why: "Intermediate metabolizer for both genes, a common real-world profile." },
];

// ------------------------------------------------------------------ state & helpers
const S = { health: null, samples: [], byId: {}, result: null, view: null, cy: null, mode: "patient",
            path: null, walk: null, flow: null, explanations: {}, filter: new Set(["avoid", "review", "adjust", "standard"]), query: "" };
const $ = (id) => document.getElementById(id);
const MOTION = !matchMedia("(prefers-reduced-motion: reduce)").matches; // honour the OS setting: no layout/flow animation
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-US");
const badge = (a, extra = "") => `<span class="badge ${a}"><span class="ic">${ACTIONS[a].icon}</span>${esc(ACTIONS[a].label)}${extra}</span>`;
const pubmed = (pmid) => `<a href="https://pubmed.ncbi.nlm.nih.gov/${esc(pmid)}/" target="_blank" rel="noopener">PMID ${esc(pmid)}</a>`;
const conditionText = (c) => Object.entries(c).sort().map(([g, p]) => `${g} ${p}`).join(" + ");
const popLabel = (p) => (p && p.trim() !== "general" ? p.trim() : "");
const truncate = (t, n) => (t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t);
const popName = (code) => POPULATIONS[code] || code;

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), 7000);
}
function busy(title, sub, timed) {
  clearInterval(busy.timer);
  if (!title) { $("busy").hidden = true; return; }
  $("busy").hidden = false; $("busy-title").textContent = title; $("busy-sub").textContent = sub || "";
  if (timed) { const t0 = Date.now(); busy.timer = setInterval(() => ($("busy-sub").textContent = `${sub} · ${Math.round((Date.now() - t0) / 1000)} s`), 500); }
}

// ------------------------------------------------------------------ init
async function init() {
  wireSearch(); wireManual(); wireSteps(); wireGraphControls(); wireTooltips();
  renderLanding();
  api("/health").then(renderHealth).catch(() => renderHealth(null));
  api("/kg/stats").then((st) => { S.kg = st; renderLanding(); }).catch(() => {});
  try {
    S.samples = await api("/samples");
    S.byId = Object.fromEntries(S.samples.map((s) => [s.sample_id, s]));
    renderLanding();
  } catch (e) { toast(`Backend not reachable: ${e.message}`); }

  const q = new URLSearchParams(location.search); // deep links: ?sample=NA12878&step=graph&drug=amitriptyline[&walk=2]
  if (q.get("sample")) {
    await run({ sample_id: q.get("sample").toUpperCase() }, q.get("step"));
    const rec = q.get("drug") && S.result?.recommendations.find((r) => r.drug === q.get("drug"));
    if (rec && q.get("step") === "graph") {
      await openPath(rec, 0);
      if (q.get("walk")) { walkStart(); for (let i = 1; i < Number(q.get("walk")); i++) walkGo(1); } // e.g. &walk=3
    }
    else if (rec) {
      openRec(rec.drug);
      if (q.get("explain")) document.querySelector(`.rec[data-drug="${CSS.escape(rec.drug)}"] [data-llm]`)?.click(); // &explain=1
    }
  }
}

function renderHealth(h) {
  S.health = h;
  const chip = (state, text, title) => `<span class="chip" title="${esc(title)}"><span class="dot ${state}"></span>${esc(text)}</span>`;
  $("status").innerHTML = !h ? chip("bad", "Backend offline", "API not reachable") :
    chip(h.neo4j ? "ok" : "bad", "Graph", "Neo4j knowledge graph") +
    chip(h.pharmcat_jar ? "ok" : "bad", "PharmCAT", "Genotype caller") +
    chip(h.llm ? "ok" : "", h.llm ? h.llm_model : "LLM off", h.llm ? `Local LLM at ${h.llm_url}` : "Optional: explanations fall back to graph text");
}

// ------------------------------------------------------------------ patient search & manual entry
function wireSearch() {
  const input = $("patient-search"), box = $("search-results");
  let active = 0, items = [];
  const draw = () => {
    const q = input.value.trim().toUpperCase();
    if (!q) { box.hidden = true; return; }
    items = S.samples.filter((s) => s.sample_id.includes(q) || s.population === q || s.superpopulation === q)
      .sort((a, b) => (b.profile_cached - a.profile_cached) || a.sample_id.localeCompare(b.sample_id)).slice(0, 8);
    active = 0;
    box.innerHTML = items.map((s, i) => `<div class="result ${i === 0 ? "active" : ""}" data-id="${esc(s.sample_id)}">
        <span class="id">${esc(s.sample_id)}</span><span class="pop">${esc(popName(s.population))} · ${esc(s.superpopulation)}</span>
        ${s.profile_cached ? '<span class="tag">genotyped</span>' : ""}</div>`).join("") ||
      `<div class="result"><span class="pop">No sample matches “${esc(input.value)}”</span></div>`;
    box.hidden = false;
    box.querySelectorAll("[data-id]").forEach((el) => el.onmousedown = () => pick(el.dataset.id));
  };
  const pick = (id) => { box.hidden = true; input.value = ""; input.blur(); run({ sample_id: id }); };
  input.oninput = draw;
  input.onfocus = draw;
  input.onblur = () => setTimeout(() => (box.hidden = true), 120);
  input.onkeydown = (e) => {
    const rows = box.querySelectorAll("[data-id]");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); active = (active + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % Math.max(rows.length, 1);
      rows.forEach((r, i) => r.classList.toggle("active", i === active));
    } else if (e.key === "Enter" && items[active]) pick(items[active].sample_id);
    else if (e.key === "Escape") { input.blur(); }
  };
}

function wireManual() {
  const open = () => { $("manual-modal").hidden = false; };
  $("manual-btn").onclick = open;
  $("manual-cancel").onclick = () => ($("manual-modal").hidden = true);
  $("manual-modal").onclick = (e) => { if (e.target.id === "manual-modal") $("manual-modal").hidden = true; };
  for (const g of GENES) {
    api(`/phenotypes/${g}`).then((opts) => {
      $(`ph-${g}`).innerHTML = `<option value="">not tested</option>` +
        opts.map((o) => `<option ${o === "Normal Metabolizer" ? "selected" : ""}>${esc(o)}</option>`).join("");
    }).catch(() => {});
  }
  $("as-CYP2D6").innerHTML += [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 3]
    .map((v) => `<option value="${v}">${v.toFixed(2)}</option>`).join("");
  $("manual-run").onclick = () => {
    const phenotypes = {};
    for (const g of GENES) if ($(`ph-${g}`).value) phenotypes[g] = $(`ph-${g}`).value;
    if (!Object.keys(phenotypes).length) return toast("Select at least one phenotype.");
    const as = $("as-CYP2D6").value;
    $("manual-modal").hidden = true;
    run({ phenotypes, activity_scores: as !== "" && phenotypes.CYP2D6 ? { CYP2D6: Number(as) } : null });
  };
}

// ------------------------------------------------------------------ run the pipeline
async function run(request, step) {
  const s = request.sample_id && S.byId[request.sample_id];
  if (request.sample_id && S.samples.length && !s) return toast(`Unknown sample ${request.sample_id}`);
  if (s && !s.profile_cached) busy(`Genotyping ${request.sample_id}`, "bcftools region extraction → PharmCAT → knowledge graph", true);
  else busy(request.sample_id ? `Loading ${request.sample_id}` : "Querying the knowledge graph", "");
  try {
    S.result = await api("/recommend", { method: "POST", body: JSON.stringify(request) });
    if (s) s.profile_cached = true;
    S.explanations = {}; S.path = null; S.graphFor = null;
    $("landing").hidden = true;
    renderStrip(); renderGenome(); renderGenotype(); renderRecs(); renderMethod();
    $("stepper").hidden = false; $("step-nav").hidden = false;
    document.querySelectorAll(".stepper button").forEach((b) => (b.disabled = !available().includes(b.dataset.step)));
    show(available().includes(step) ? step : available()[0]);
  } catch (e) { toast(e.message); } finally { busy(null); }
}
const available = () => (S.result?.profile ? STEPS : STEPS.filter((s) => s !== "genome" && s !== "genotype"));

function show(step) {
  if (!S.result) return;
  S.view = step;
  const order = available(), ix = order.indexOf(step);
  document.querySelectorAll(".stepper button").forEach((b) => {
    b.classList.toggle("active", b.dataset.step === step);
    b.classList.toggle("done", order.indexOf(b.dataset.step) > -1 && order.indexOf(b.dataset.step) < ix);
  });
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${step}`));
  const prev = order[ix - 1], next = order[ix + 1];
  $("prev-step").hidden = !prev; $("prev-step").textContent = prev ? `← ${STEP_NAME[prev]}` : "";
  $("next-step").hidden = !next; $("next-step").textContent = next ? `Next: ${STEP_NAME[next]} →` : "";
  $("prev-step").onclick = () => prev && show(prev);
  $("next-step").onclick = () => next && show(next);
  if (step === "graph" && !S.revealOnly) { if (S.graphFor !== resultKey() || !S.cy) drawPatientGraph(); else { S.cy.resize(); startFlow(); } }
  else stopFlow();
  document.getElementById(`view-${step}`).classList.remove("fade-in");
  void document.getElementById(`view-${step}`).offsetWidth;
  document.getElementById(`view-${step}`).classList.add("fade-in");
  syncUrl();
  window.scrollTo({ top: 0 });
}
const resultKey = () => S.result.sample_id || JSON.stringify(S.result.patient_phenotypes);
function syncUrl() {
  if (!S.result?.sample_id) return;
  const q = new URLSearchParams({ sample: S.result.sample_id, step: S.view });
  if (S.view === "graph" && S.mode === "path" && S.path) q.set("drug", S.path.rec.drug);
  history.replaceState(null, "", `?${q}`);
}

function wireSteps() {
  document.querySelectorAll(".stepper button").forEach((b) => (b.onclick = () => show(b.dataset.step)));
  document.addEventListener("keydown", (e) => {
    if (!S.result || /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName) || !$("manual-modal").hidden) return;
    if (S.walk && S.view === "graph") {
      if (e.key === "ArrowRight") { walkGo(1); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { walkGo(-1); e.preventDefault(); }
      else if (e.key === "Escape") walkStop();
      return;
    }
    const order = available(), ix = order.indexOf(S.view);
    if (e.key === "ArrowRight" && order[ix + 1]) show(order[ix + 1]);
    if (e.key === "ArrowLeft" && order[ix - 1]) show(order[ix - 1]);
  });
}

// ------------------------------------------------------------------ landing
function renderLanding() {
  const kg = S.kg?.nodes;
  const tiles = kg ? [["Recommendation", "CPIC recommendations"], ["Drug", "drugs"], ["Gene", "genes"], ["Publication", "publications"], ["ADR", "adverse reactions"]]
    .map(([k, l]) => `<div class="kg-tile"><div class="n">${fmt(kg[k] || 0)}</div><div class="k">${l}</div></div>`).join("") +
    `<div class="kg-tile"><div class="n">${fmt(Object.values(S.kg.relationships).reduce((a, b) => a + b, 0))}</div><div class="k">relationships</div></div>` : "";
  $("landing").innerHTML = `
    <div class="hero">
      <h1>From a genome to a prescribing decision</h1>
      <p>Pick a person from the 1000 Genomes Project. The pipeline reads their CYP2C19 and CYP2D6 genes from the
        whole-genome sequence, works out how fast they metabolize drugs, and looks up what the CPIC clinical guidelines
        recommend. Every result links back to its evidence.</p>
    </div>
    <div class="pipeline">
      ${[["Genome", "The two gene regions are cut from the 30× whole-genome VCF.", "bcftools · GRCh38"],
         ["Genotype", "Variants are matched to star alleles; their functions give a metabolizer phenotype.", "PharmCAT 3.4"],
         ["Knowledge graph", "Only CPIC rules whose full gene condition fits this person are retrieved.", "Neo4j · CPIC, HGNC, SIDER"],
         ["Recommendation", "Each drug gets an action, an evidence level and its PubMed sources.", "deterministic ranking"],
         ["Explanation", "A local LLM may rephrase the evidence; a checker rejects anything not in the graph.", "optional · Ollama"]]
        .map(([h, p, t], i) => `<div class="stage"><div class="ix">${i + 1}</div><h3>${h}</h3><p>${p}</p><div class="tool">${t}</div></div>`).join("")}
    </div>
    <div class="section-title">Start with an example genome</div>
    <div class="examples">
      ${EXAMPLES.map((x) => { const s = S.byId[x.id];
        return `<button class="example" data-id="${x.id}"><div class="id">${x.id}</div>
          <div class="pop">${s ? `${esc(popName(s.population))} · ${esc(SUPERPOP[s.superpopulation] || s.superpopulation)}` : "&nbsp;"}</div>
          <div class="why">${esc(x.why)}</div><div class="go">Analyse genome →</div></button>`; }).join("")}
    </div>
    <div class="landing-foot">or search any of ${fmt(S.samples.length || 3202)} genomes above, or
      <button class="btn ghost small" id="landing-manual">enter phenotypes manually</button></div>
    ${tiles ? `<div class="section-title" style="margin-top:34px">Knowledge graph (live from Neo4j)</div><div class="kg-tiles">${tiles}</div>` : ""}`;
  $("landing").querySelectorAll(".example").forEach((b) => (b.onclick = () => run({ sample_id: b.dataset.id })));
  $("landing-manual").onclick = () => ($("manual-modal").hidden = false);
}

// ------------------------------------------------------------------ patient strip
function renderStrip() {
  const r = S.result, p = r.profile, d = p?.demographics || {};
  const counts = Object.fromEntries(ACTION_ORDER.map((a) => [a, r.recommendations.filter((x) => x.action === a).length]));
  $("patient-strip").innerHTML = `
    <div class="pt-id">
      <div class="pt-avatar">${esc(p ? d.superpopulation : "Rx")}</div>
      <div><div class="pt-name">${esc(r.sample_id || "Manual phenotypes")}</div>
        <div class="pt-meta">${p ? `${esc(popName(d.population))} · ${esc(SUPERPOP[d.superpopulation] || d.superpopulation)} · ${esc(d.sex)}` : "No genome: phenotypes entered directly"}</div></div>
    </div>
    <div class="pt-genes">${Object.entries(r.patient_phenotypes).map(([g, ph]) => `
      <div class="gene-chip"><div class="g">${g}</div>
        <div><span class="d">${esc(r.patient_diplotypes?.[g] || "")}</span> <span class="p">${esc(ph)}</span></div></div>`).join("")}</div>
    <div class="pt-actions">${["avoid", "review", "adjust", "standard"].map((a) => badge(a, ` <span class="n">${counts[a]}</span>`)).join("")}</div>`;
  $("patient-strip").hidden = false;
}

// ------------------------------------------------------------------ step 1: genome
function renderGenome() {
  const p = S.result.profile;
  if (!p) return;
  const d = p.demographics;
  let html = `<div class="view-head"><h2>Where the variants are</h2>
    <p>${esc(p.sample_id)}'s whole genome was sequenced at 30× coverage and aligned to GRCh38. Only the two pharmacogene
    regions are read. PharmCAT checks every position that defines a known star allele; the variants this person carries
    are marked below (filled = both copies, hollow = one copy).</p></div>
    <div class="facts">
      <div class="fact"><div class="k">Population</div><div class="v">${esc(popName(d.population))}</div></div>
      <div class="fact"><div class="k">Ancestry</div><div class="v">${esc(SUPERPOP[d.superpopulation] || d.superpopulation)}</div></div>
      <div class="fact"><div class="k">Sex</div><div class="v">${esc(d.sex)}</div></div>
      <div class="fact"><div class="k">Data</div><div class="v">1000 Genomes, 30× WGS</div></div>
      <div class="fact"><div class="k">Reference</div><div class="v">GRCh38</div></div>
    </div><div class="grid2">`;
  for (const g of GENES) {
    const ev = p.genes[g]?.matcher_evidence;
    if (!ev) continue;
    html += `<div class="card"><div class="card-head"><h3>${g}</h3><span class="tag">${esc(ev.chromosome)} · ${GENE_INFO[g].strand} strand</span></div>
      <div class="card-sub">${ev.positions_examined} allele-defining positions checked · ${ev.missing_positions} missing ·
        <b>${ev.variants_carried.length}</b> carry a variant</div>
      ${ev.variants_carried.length ? geneTrack(g, ev.variants_carried) : `<p class="muted">Reference at every defining position.</p>`}
      <table><tr><th>Variant</th><th>Position</th><th>Genotype</th><th>What it is</th></tr>
      ${ev.variants_carried.map((v) => { const k = KNOWN[v.rsid];
        return `<tr><td><a href="https://www.ncbi.nlm.nih.gov/snp/${esc(v.rsid)}" target="_blank" rel="noopener">${esc(v.rsid)}</a></td>
          <td class="mono">${fmt(v.position)}</td><td class="mono">${esc(v.genotype)} <span class="muted">${v.zygosity === "homozygous" ? "both copies" : "one copy"}</span></td>
          <td>${k ? `${k[0] ? `<span class="star">${g}${esc(k[0])}</span> · ` : ""}${esc(k[1])}` : '<span class="muted">—</span>'}</td></tr>`; }).join("")}
      </table></div>`;
  }
  html += `</div>`;
  if (p.vcf_preprocessing?.missing_positions_filled_as_reference)
    html += `<p class="note">The cohort VCF only lists sites where at least one of 3,202 people has a variant. Allele-defining positions
      missing from it are read as reference before PharmCAT runs; without this step CYP2D6 could not be resolved for 7 of 10 test genomes.</p>`;
  $("view-genome").innerHTML = html;
}

// Callout-style track: gene body on a genomic axis, one marker per carried variant, labels spread to avoid overlap.
function geneTrack(gene, variants) {
  const info = GENE_INFO[gene], W = 640, pad = 12;
  let lo = info.start, hi = info.end;
  for (const v of variants) { lo = Math.min(lo, v.position); hi = Math.max(hi, v.position); }
  const span = hi - lo; lo -= span * 0.05; hi += span * 0.05;
  const X = (pos) => pad + ((pos - lo) / (hi - lo)) * (W - 2 * pad);
  const items = variants.map((v) => {
    const k = KNOWN[v.rsid], text = k && k[0] ? `${k[0]} · ${v.rsid}` : v.rsid;
    return { v, mx: X(v.position), text, known: !!(k && k[0]), w: text.length * 6.3 + 12 };
  }).sort((a, b) => a.mx - b.mx);
  const total = items.reduce((s, it) => s + it.w, 0);
  const rows = total > W - 20 ? 2 : 1;
  for (let r = 0; r < rows; r++) { // spread labels in each row: forward sweep, then pull back inside the width
    const row = items.filter((_, i) => i % rows === r);
    let right = -Infinity;
    for (const it of row) { it.lx = Math.max(it.mx, right + it.w / 2); right = it.lx + it.w / 2; it.row = r; }
    let left = W;
    for (const it of [...row].reverse()) { it.lx = Math.min(it.lx, left - it.w / 2); left = it.lx - it.w / 2; }
    for (const it of row) it.lx = Math.max(it.lx, it.w / 2);
  }
  const base = (r) => 14 + r * 18, elbow = 14 + rows * 18 + 2, my = elbow + 24, axis = my + 22, H = axis + 30;
  const bx1 = X(info.start), bx2 = X(info.end);
  const marks = items.map((it) => {
    const tip = `<b>${esc(it.v.rsid)}</b> · ${esc(info.chrom)}:${fmt(it.v.position)}<br>genotype ${esc(it.v.genotype)} (${it.v.zygosity})` +
      (KNOWN[it.v.rsid] ? `<br>${esc(KNOWN[it.v.rsid][1])}` : "");
    return `<g data-tip="${esc(tip)}">
      <path class="stem" fill="none" d="M${it.lx},${base(it.row) + 4} V${elbow} L${it.mx},${my - 7}"/>
      <line class="stem" x1="${it.mx}" y1="${my + 7}" x2="${it.mx}" y2="${axis}"/>
      <circle class="mk ${it.v.zygosity === "homozygous" ? "hom" : "het"}" cx="${it.mx}" cy="${my}" r="6"/>
      <text class="lab ${it.known ? "known" : ""}" x="${it.lx}" y="${base(it.row)}" text-anchor="middle">${esc(it.text)}</text>
      <rect x="${Math.min(it.lx, it.mx) - 8}" y="${base(it.row) - 12}" width="${Math.abs(it.lx - it.mx) + 16}" height="${my - base(it.row) + 20}" fill="transparent"/></g>`;
  }).join("");
  return `<div class="track-legend">
      <span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="#2a78d6" stroke="#2a78d6" stroke-width="1.5"/></svg>both copies</span>
      <span><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="#fff" stroke="#2a78d6" stroke-width="1.5"/></svg>one copy</span>
      <span class="muted">labels in bold define a star allele</span></div>
    <svg class="track" viewBox="0 0 ${W} ${H}" role="img" aria-label="${gene} variants on the genomic axis">
      <line class="axis" x1="${pad}" y1="${axis}" x2="${W - pad}" y2="${axis}"/>
      <rect class="body" x="${bx1}" y="${axis - 6}" width="${Math.max(bx2 - bx1, 4)}" height="12" rx="6"/>
      <text class="body-label" x="${(bx1 + bx2) / 2}" y="${axis + 22}" text-anchor="middle">${gene} gene</text>
      <text class="tick" x="${pad}" y="${axis + 22}">${fmt(Math.round(lo))}</text>
      <text class="tick" x="${W - pad}" y="${axis + 22}" text-anchor="end">${fmt(Math.round(hi))}</text>
      ${marks}
    </svg>`;
}

// ------------------------------------------------------------------ step 2: genotype
const SCALES = {
  CYP2D6: [["PM", "Poor", "score 0"], ["IM", "Intermediate", "0.25 – 1.0"], ["NM", "Normal", "1.25 – 2.25"], ["UM", "Ultrarapid", "above 2.25"]],
  CYP2C19: [["PM", "Poor", "no + no function"], ["IM", "Intermediate", "one no-function allele"], ["NM", "Normal", "normal + normal"],
            ["RM", "Rapid", "normal + increased"], ["UM", "Ultrarapid", "increased + increased"]],
};
const phenoKey = (ph) => (/ultrarapid/i.test(ph) ? "UM" : /rapid/i.test(ph) ? "RM" : /normal/i.test(ph) ? "NM" : /intermediate/i.test(ph) ? "IM" : /poor/i.test(ph) ? "PM" : null);

function renderGenotype() {
  const p = S.result.profile;
  if (!p) return;
  let html = `<div class="view-head"><h2>From alleles to a metabolizer phenotype</h2>
    <p>Everyone has two copies of each gene. PharmCAT names the version on each copy (a star allele) from the variants found;
    CPIC assigns each allele a function, and the pair decides how fast the enzyme works. That phenotype is what the knowledge graph is queried with.</p></div><div class="grid2">`;
  for (const g of GENES) {
    const c = p.genes[g];
    if (!c) continue;
    const sa = c.structural_assessment || {};
    const key = phenoKey(c.phenotype);
    const h = [c.haplotype_1 || {}, c.haplotype_2 || {}];
    const vals = h.map((x) => (x.activity != null && x.activity !== "" ? Number(x.activity) : null));
    const conf = { high: "standard", moderate: "adjust", low: "avoid" }[sa.confidence_level] || "none";
    html += `<div class="card"><div class="card-head"><h3>${g}</h3>
        <span class="badge ${conf}"><span class="ic">${{ standard: "✓", adjust: "!", avoid: "✕", none: "–" }[conf]}</span>call confidence: ${esc(sa.confidence_level || "?")}</span></div>`;
    if (c.ambiguous_call) {
      html += `<p class="note">PharmCAT could not settle on one diplotype: ${c.diplotype_candidates.length} candidates fit
        (${Object.entries(c.phenotype_candidates).map(([k, n]) => `${esc(k)} ×${n}`).join(", ")}). Reported as <b>Indeterminate</b>.</p>`;
    } else {
      html += `<div class="alleles">${h.map((x, i) => `<div class="allele"><span class="copy">Copy ${i + 1}</span>
          <span class="name">${esc(x.name)}</span><span class="fn">${esc(x.function || "function unknown")}</span>
          ${vals[i] != null ? `<span class="val"><span class="bar"><i style="width:${Math.min(vals[i], 1.5) / 1.5 * 100}%"></i></span>activity ${vals[i]}</span>` : "<span></span>"}
        </div>`).join("")}</div>`;
      if (vals.every((v) => v != null))
        html += `<div class="sum">Activity score <b>${vals[0]} + ${vals[1]} = ${c.activity_score ?? vals[0] + vals[1]}</b></div>`;
    }
    html += `<div class="muted" style="font-size:12.5px">CPIC phenotype${g === "CYP2D6" ? " (from the activity score)" : " (from the allele functions)"}</div>
      <div class="scale">${SCALES[g].map(([k, name, sub]) => `<div class="${k === key ? "on" : ""}">${name}<small>${sub}</small></div>`).join("")}</div>
      ${!key ? `<p class="muted">Phenotype: ${esc(c.phenotype)}</p>` : ""}
      <ul class="caveats">${(sa.structural_limitations || []).concat(c.vus_annotations || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>`;
  }
  $("view-genotype").innerHTML = html + `</div>` + (S.result.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("");
}

// ------------------------------------------------------------------ step 3: knowledge graph
function colorsFor(type, action) {
  if (type === "Drug" && action) return [STATUS_TINT[action], STATUS[action], "#0b0b0b"];
  const [fill, line] = TYPE_COLOR[type] || ["#fff", "#c3c2b7"];
  return [fill, line, type === "Patient" ? "#ffffff" : type === "Publication" || type === "ADR" ? "#52514e" : "#0b0b0b"];
}
function N(id, label, type, data = {}) {
  const lines = String(label).split("\n");
  const longest = Math.max(...lines.map((l) => l.length));
  const small = type === "Publication" || type === "ADR";
  const [fill, line, ink] = colorsFor(type, data.action);
  return { group: "nodes", data: { ...data, id, label, type, fill, line, ink,
    w: type === "Patient" ? 70 : longest * (small ? 6.3 : 7.4) + 26, h: type === "Patient" ? 70 : lines.length * (small ? 14 : 16) + (small ? 12 : 16) } };
}
const E = (source, target, label = "", extra = {}) => ({ group: "edges", data: { id: `${source}→${target}:${label}`, source, target, label, ...extra } });

const CY_STYLE = [
  { selector: "node", style: {
      shape: "round-rectangle", width: "data(w)", height: "data(h)", "background-color": "data(fill)", "border-width": 1.5,
      "border-color": "data(line)", label: "data(label)", color: "data(ink)", "font-size": 12.5, "font-weight": 600,
      "text-valign": "center", "text-halign": "center", "text-wrap": "wrap", "font-family": "Segoe UI, system-ui, sans-serif",
      "transition-property": "opacity, border-width, underlay-opacity", "transition-duration": MOTION ? 0.2 : 0,
      "underlay-color": "#2a78d6", "underlay-padding": 7, "underlay-opacity": 0, "underlay-shape": "round-rectangle" } },
  { selector: 'node[type = "Patient"]', style: { shape: "ellipse", "font-size": 13, "font-weight": 700, "underlay-shape": "ellipse" } },
  { selector: 'node[type = "Publication"], node[type = "ADR"]', style: { "font-size": 11, "font-weight": 500 } },
  { selector: 'node[type = "Drug"]', style: { "border-width": 2 } },
  { selector: ":parent", style: {
      shape: "round-rectangle", "background-color": "data(fill)", "background-opacity": 0.55, "border-width": 0, padding: 18,
      label: "data(label)", "text-valign": "top", "text-halign": "center", "text-margin-y": -8, "font-size": 16,
      "font-weight": 700, color: "#0b0b0b", "underlay-opacity": 0 } },
  { selector: "edge", style: {
      width: 1.3, "line-color": "#cfcdc4", "target-arrow-color": "#cfcdc4", "target-arrow-shape": "triangle", "arrow-scale": 0.8,
      "curve-style": "bezier", label: "data(label)", "font-size": 10, color: "#898781", "text-rotation": "autorotate",
      "text-background-color": "#fcfcfb", "text-background-opacity": 1, "text-background-padding": 2,
      "transition-property": "opacity, line-color, width", "transition-duration": MOTION ? 0.2 : 0 } },
  { selector: "edge.taxi", style: { "curve-style": "taxi", "taxi-direction": "rightward", "taxi-turn": "38%", "taxi-turn-min-distance": 12 } },
  { selector: "edge[?chain]", style: { width: 2, "line-color": "#2a78d6", "target-arrow-color": "#2a78d6", "line-style": "dashed", "line-dash-pattern": [7, 5], color: "#1c5cab" } },
  { selector: "edge[?evidence]", style: { "line-color": "#e87ba4", "target-arrow-color": "#e87ba4", width: 1.6, color: "#b8467a" } },
  { selector: ".dim", style: { opacity: 0.13 } },
  { selector: "node.focus", style: { "underlay-opacity": 0.16 } },
  { selector: "node:selected", style: { "underlay-opacity": 0.24, "border-width": 2.5 } },
  { selector: "edge.hl", style: { width: 2.6, "line-color": "#2a78d6", "target-arrow-color": "#2a78d6", "z-index": 10 } },
];

function renderCy(elements, positions, origin) {
  stopFlow(); walkStop();
  if (S.cy) S.cy.destroy();
  const seen = new Set();
  elements = elements.filter((e) => !seen.has(e.data.id) && seen.add(e.data.id));
  for (const e of elements) if (e.group === "nodes" && e.data.type !== "Lane") e.position = { ...(MOTION ? origin : positions[e.data.id]) }; // lanes size to their children
  S.cy = cytoscape({ container: $("cy"), elements, style: CY_STYLE, minZoom: 0.15, maxZoom: 2.5, boxSelectionEnabled: false });
  S.cy.layout({ name: "preset", positions: (n) => positions[n.id()], animate: MOTION, animationDuration: 650,
                animationEasing: "ease-out-cubic", fit: true, padding: 46 }).run();
  const cy = S.cy;
  cy.on("mouseover", "node", (e) => {
    const n = e.target;
    if (n.isParent()) return;
    if (!S.walk) highlight(n.closedNeighborhood().union(n.ancestors()));
    showTip(nodeTip(n), e.originalEvent);
  });
  cy.on("mousemove", "node", (e) => moveTip(e.originalEvent));
  cy.on("mouseout", "node", () => { if (!S.walk) clearHighlight(); hideTip(); });
  cy.on("tap", "node", (e) => { if (!e.target.isParent()) inspect(e.target); });
  cy.on("dbltap", 'node[type = "Drug"]', (e) => { const rec = e.target.data("rec"); if (rec) openPath(rec, 0); });
  cy.on("tap", (e) => { if (e.target === cy) inspect(null); });
}
function highlight(eles) {
  const cy = S.cy;
  cy.batch(() => {
    cy.elements().addClass("dim").removeClass("focus hl");
    eles.removeClass("dim"); eles.nodes().addClass("focus");
    eles.edgesWith(eles).removeClass("dim").addClass("hl");
    eles.nodes().ancestors().removeClass("dim");
  });
}
const clearHighlight = () => S.cy && S.cy.batch(() => S.cy.elements().removeClass("dim focus hl"));

function wireGraphControls() {
  $("zoom-in").onclick = () => S.cy && S.cy.animate({ zoom: { level: S.cy.zoom() * 1.25, renderedPosition: { x: S.cy.width() / 2, y: S.cy.height() / 2 } }, duration: 200 });
  $("zoom-out").onclick = () => S.cy && S.cy.animate({ zoom: { level: S.cy.zoom() / 1.25, renderedPosition: { x: S.cy.width() / 2, y: S.cy.height() / 2 } }, duration: 200 });
  $("zoom-fit").onclick = () => S.cy && S.cy.animate({ fit: { padding: 46 }, duration: 300 });
  $("graph-mode").querySelectorAll("button").forEach((b) => (b.onclick = () => {
    if (b.dataset.mode === "patient") drawPatientGraph(); else if (S.path) openPath(S.path.rec, S.path.ix);
  }));
  $("walk-btn").onclick = walkStart;
  $("walk-prev").onclick = () => walkGo(-1);
  $("walk-next").onclick = () => walkGo(1);
  $("walk-stop").onclick = walkStop;
  window.addEventListener("resize", () => S.cy && S.view === "graph" && S.cy.resize());
}
function setMode(mode) {
  S.mode = mode;
  $("graph-mode").querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
    if (b.dataset.mode === "path") b.disabled = !S.path;
  });
  $("walk-btn").hidden = mode !== "path";
}

// Patient overview: patient -> genotype -> CPIC phenotype -> drugs, one lane per action.
function drawPatientGraph() {
  const r = S.result, els = [], pos = {};
  const genes = Object.keys(r.patient_phenotypes);
  els.push(N("patient", r.sample_id || "Patient", "Patient"));
  pos.patient = { x: 0, y: 0 };
  genes.forEach((g, i) => {
    const y = (i - (genes.length - 1) / 2) * 170, dip = r.patient_diplotypes?.[g];
    els.push(N(`g:${g}`, dip ? `${g}\n${dip}` : g, "Gene", { gene: g, dip }), N(`ph:${g}`, r.patient_phenotypes[g], "Phenotype", { gene: g }));
    els.push(E("patient", `g:${g}`), E(`g:${g}`, `ph:${g}`, "CPIC"));
    pos[`g:${g}`] = { x: 170, y }; pos[`ph:${g}`] = { x: 370, y };
  });
  // Lanes: pick rows-per-column so the drawing's shape matches the canvas (bigger, more legible nodes).
  const lanes = ["avoid", "review", "adjust", "standard"].map((a) => [a, r.recommendations.filter((rec) => rec.action === a)]).filter(([, l]) => l.length);
  const rowH = 46, colW = 150, laneGap = 56, x0 = 560;
  const lay = (maxRows) => {
    const p = {}, heads = {};
    let x = x0, top = 0;
    for (const [a, recs] of lanes) {
      const cols = Math.ceil(recs.length / maxRows), rows = Math.ceil(recs.length / cols), t = -((rows - 1) * rowH) / 2;
      top = Math.min(top, t);
      recs.forEach((rec, i) => (p[`d:${rec.drug}`] = { x: x + Math.floor(i / rows) * colW, y: t + (i % rows) * rowH }));
      heads[a] = x;
      x += cols * colW + laneGap;
    }
    return { p, w: x - laneGap + 90 + 60, h: Math.max(-2 * top + 90, 2 * 85 + 80) };
  };
  const cw = $("cy").clientWidth || 1000, ch = $("cy").clientHeight || 600;
  let best = null;
  for (let m = 4; m <= 16; m++) { const l = lay(m), z = Math.min(cw / l.w, ch / l.h); if (!best || z > best.z + 1e-3) best = { ...l, z }; }
  Object.assign(pos, best.p);
  for (const [a, recs] of lanes) {
    els.push({ group: "nodes", data: { id: `lane:${a}`, label: `${ACTIONS[a].icon}  ${ACTIONS[a].label} · ${recs.length}`, type: "Lane",
                                       fill: STATUS_TINT[a], line: STATUS_TINT[a], ink: "#0b0b0b", w: 1, h: 1 } });
    for (const rec of recs) {
      const id = `d:${rec.drug}`;
      const node = N(id, rec.drug, "Drug", { action: a, rec });
      node.data.parent = `lane:${a}`;
      els.push(node);
      for (const g of new Set(rec.evidence.flatMap((s) => s.genes))) if (r.patient_phenotypes[g]) els.push(E(`ph:${g}`, id, "", { cls: "taxi" }));
    }
  }
  renderCy(els, pos, { x: 0, y: 0 });
  S.cy.edges().filter((e) => e.data("cls") === "taxi").addClass("taxi");
  S.graphFor = resultKey();
  setMode("patient");
  const none = r.recommendations.filter((x) => x.action === "none").length;
  $("graph-title").textContent = `Everything CPIC says about ${r.sample_id || "this patient"}`;
  $("graph-sub").textContent = `Genotype → CPIC phenotype → each drug with a matching recommendation, grouped by action.` +
    (none ? ` ${none} drug(s) without a recommendation are hidden.` : "") + " Hover to trace, double-click a drug for its evidence path.";
  legend(["Patient", "Gene", "Phenotype"], true);
  inspect(null);
  syncUrl();
}

async function openPath(rec, ix = 0) {
  const src = rec.evidence[ix];
  const slow = setTimeout(() => busy("Loading evidence path", ""), 300); // no flash for fast responses
  try {
    const qs = S.result.sample_id ? `?sample_id=${encodeURIComponent(S.result.sample_id)}` : "";
    const g = await api(`/graph/${src.recommendation_id}${qs}`);
    if (S.view !== "graph") { S.revealOnly = true; show("graph"); S.revealOnly = false; } // container must be visible before drawing
    const pop = popLabel(src.population);
    const els = g.nodes.map((n) => {
      let label = n.label;
      if (n.type === "Recommendation") label = `CPIC recommendation\n${n.classification || ""}${pop ? " · " + pop : ""}`;
      if (n.type === "Drug") label = `${n.label}\n${ACTIONS[rec.action].label}`;
      return N(n.id, label, n.type, { ...n, action: n.type === "Drug" ? rec.action : undefined, rec: n.type === "Drug" ? rec : undefined });
    }).concat(g.edges.map((e) => E(e.source, e.target, ["CAUSES_ADR", "CITES"].includes(e.label) ? "" : e.label.replaceAll("_", " ").toLowerCase(),
      { chain: ["HAS_GENOTYPE", "RESULTS_IN_PHENOTYPE", "HAS_RECOMMENDATION", "RECOMMENDS", "HAS_PHENOTYPE"].includes(e.label), evidence: e.kind === "ASSOCIATED_WITH" })));
    S.path = { rec, ix, src, graph: g };
    renderCy(els, pathPositions(g.nodes), { x: 760, y: 0 });
    S.graphFor = resultKey();
    setMode("path");
    $("graph-title").textContent = `Why ${rec.drug}: ${ACTIONS[rec.action].label.toLowerCase()}`;
    $("graph-sub").textContent = `${conditionText(src.condition)}${pop ? ` (${pop})` : ""} → CPIC recommendation → ${rec.drug}, with its guideline, publications and known side effects.`;
    legend(Object.keys(TYPE_COLOR).filter((t) => t !== "Drug" && g.nodes.some((n) => n.type === t)), false, rec.action);
    inspect(S.cy.$(`[type = "Recommendation"]`)[0]);
    startFlow();
    syncUrl();
  } catch (e) { toast(e.message); } finally { clearTimeout(slow); busy(null); }
}

// Fixed reading order: patient → gene → genotype → phenotype → recommendation → drug; guideline + papers below the genes, side effects below the drug.
function pathPositions(nodes) {
  const pos = {};
  const genes = nodes.filter((n) => n.type === "Gene").map((n) => n.label);
  const by = (gene) => (genes.indexOf(gene) - (genes.length - 1) / 2) * 170;
  const col = { Patient: 0, Gene: 180, Diplotype: 360, Phenotype: 570, Recommendation: 820, Drug: 1040 };
  const pubs = nodes.filter((n) => n.type === "Publication"), adrs = nodes.filter((n) => n.type === "ADR");
  for (const n of nodes) {
    const gene = n.type === "Gene" ? n.label : n.type === "Phenotype" ? n.gene : n.id.startsWith("pdip:") ? n.id.slice(5) : null;
    if (n.type in col) pos[n.id] = { x: col[n.type], y: gene ? by(gene) : 0 };
    else if (n.type === "Guideline") pos[n.id] = { x: 560, y: 210 };
    else if (n.type === "Publication") pos[n.id] = { x: 560 + (pubs.indexOf(n) - (pubs.length - 1) / 2) * 140, y: 300 };
    else if (n.type === "ADR") pos[n.id] = { x: adrs.indexOf(n) % 2 ? 1130 : 950, y: 110 + Math.floor(adrs.indexOf(n) / 2) * 40 };
  }
  return pos;
}

// flowing dashes along the reasoning chain (patient → … → drug) on the evidence path
function startFlow() {
  stopFlow();
  if (!S.cy || S.mode !== "path" || !MOTION) return;
  const chain = S.cy.edges("[?chain]");
  let off = 0;
  const tick = () => { off = (off - 0.45) % 120; chain.style("line-dash-offset", off); S.flow = requestAnimationFrame(tick); };
  S.flow = requestAnimationFrame(tick);
}
function stopFlow() { if (S.flow) cancelAnimationFrame(S.flow); S.flow = null; }

function legend(types, lanes, drugAction) {
  let html = types.map((t) => { const [f, l] = TYPE_COLOR[t]; return `<span><span class="sw" style="background:${f};border-color:${l}"></span>${TYPE_NAME[t] || t}</span>`; }).join("");
  if (lanes) html += `<span class="muted">Lanes:</span>` + ["avoid", "review", "adjust", "standard"].map((a) => badge(a)).join("");
  else html += `<span><span class="sw" style="background:${STATUS_TINT[drugAction]};border-color:${STATUS[drugAction]}"></span>Drug (${ACTIONS[drugAction].label.toLowerCase()})</span>
               <span><span class="sw" style="background:#fff;border-color:#2a78d6;border-style:dashed"></span>reasoning chain</span>
               <span><span class="sw" style="background:#fff;border-color:#e87ba4"></span>gene–drug evidence level</span>`;
  $("legend").innerHTML = html;
}

// ---- inspector (right panel)
function inspect(n) {
  const el = $("inspector");
  if (n) { S.cy.$(":selected").unselect(); n.select(); }
  if (!n) {
    el.innerHTML = S.mode === "path" ? `<div class="empty-hint">Click any node to see its data, or press <b>▶ Walk through</b> to step through the reasoning.</div>` :
      `<div class="empty-hint"><b>How to read this graph</b><ol>
        <li>The patient's two genes, with the genotype PharmCAT called.</li>
        <li>The CPIC phenotype each genotype maps to.</li>
        <li>Every drug with a CPIC rule that matches the patient, grouped by what to do.</li></ol>
        <p style="margin-top:10px">Hover a node to highlight its connections. Click a drug for details, double-click for its full evidence path.</p></div>`;
    return;
  }
  const d = n.data(), t = d.type;
  const head = `<div class="type"><i style="background:${d.line}"></i>${esc(TYPE_NAME[t] || t)}</div><div class="title">${esc(String(d.label).split("\n")[0])}</div>`;
  let body = "";
  if (t === "Drug" && d.rec) {
    const rec = d.rec;
    body = `<div style="margin-bottom:10px">${badge(rec.action)} <span class="tag">CPIC level ${esc(rec.cpic_levels.join(", "))}</span></div>
      <div class="kv"><span class="k">Guideline</span><span>${esc(rec.guidelines.join("; "))}</span></div>
      <div class="src-list">${rec.evidence.map((s, i) => `<div class="src"><div class="ctx">${esc(conditionText(s.condition))}${popLabel(s.population) ? ` · ${esc(popLabel(s.population))}` : ""} · ${esc(s.classification)}</div>
        ${esc(s.recommendation)}<div style="margin-top:8px"><button class="btn ghost small" data-path="${i}">Trace evidence path →</button></div></div>`).join("")}</div>`;
  } else if (t === "Recommendation") {
    body = `<div class="kv"><span class="k">Strength</span><span>${esc(d.classification || "")}</span>
        <span class="k">Population</span><span>${esc(d.population || "general")}</span></div><div class="quote">${esc(d.text)}</div>`;
  } else if (t === "Gene") {
    body = `<div class="kv"><span class="k">HGNC</span><span class="mono">${esc(d.ident || "—")}</span>${d.dip ? `<span class="k">Genotype</span><span>${esc(d.dip)}</span>` : ""}</div>`;
  } else if (t === "Phenotype") {
    body = `<p class="muted">CPIC metabolizer phenotype for ${esc(d.gene)}. Recommendations are attached to phenotypes, not to raw variants.</p>`;
  } else if (t === "Diplotype") {
    body = `<p class="muted">This patient's ${esc(d.id.replace("pdip:", ""))} genotype as called by PharmCAT.</p>`;
  } else if (t === "Guideline") {
    body = d.url ? `<p><a href="${esc(d.url)}" target="_blank" rel="noopener">Open the CPIC guideline ↗</a></p>` : "";
  } else if (t === "Publication") {
    body = `<p>${esc(d.title || "")}${d.year ? ` (${esc(d.year)})` : ""}</p><p style="margin-top:8px">${pubmed(d.id.replace("pmid:", ""))}</p>`;
  } else if (t === "ADR") {
    body = `<p class="muted">Reported side effect of this drug in SIDER. Shown for context; not part of the CPIC recommendation.</p>`;
  } else if (t === "Patient") {
    body = `<p class="muted">${S.result.profile ? esc(popName(S.result.profile.demographics.population)) : "Manually entered phenotypes"}</p>`;
  }
  el.innerHTML = head + body;
  el.querySelectorAll("[data-path]").forEach((b) => (b.onclick = () => openPath(d.rec, Number(b.dataset.path))));
}

function nodeTip(n) {
  const d = n.data(), t = d.type;
  const label = String(d.label).split("\n")[0];
  let extra = "";
  if (t === "Drug" && d.rec) extra = `<br>${esc(ACTIONS[d.rec.action].label)} · CPIC ${esc(d.rec.cpic_levels.join(", "))}<br>${esc(truncate(d.rec.evidence[0].recommendation, 140))}`;
  else if (t === "Recommendation") extra = `<br>${esc(truncate(d.text || "", 160))}`;
  else if (t === "Publication") extra = `<br>${esc(truncate(d.title || "", 140))}`;
  else if (t === "Gene" && d.dip) extra = `<br>genotype ${esc(d.dip)}`;
  return `<div class="t">${esc(TYPE_NAME[t] || t)}</div><b>${esc(label)}</b>${extra}`;
}

// ---- guided walkthrough of one evidence path
function walkSteps() {
  const { graph: g, rec, src } = S.path;
  const nodes = (type) => g.nodes.filter((n) => n.type === type);
  const steps = [], sid = S.result.sample_id;
  const rid = nodes("Recommendation")[0]?.id, did = nodes("Drug")[0]?.id;
  for (const gene of nodes("Gene")) {
    const dip = g.nodes.find((n) => n.id === `pdip:${gene.label}`), ph = nodes("Phenotype").find((n) => n.gene === gene.label);
    if (dip && sid) steps.push({ ids: ["patient", dip.id, gene.id], text: `${sid} carries ${gene.label} ${dip.label}: two star alleles called by PharmCAT from the variants in step 1.` });
    if (ph) steps.push({ ids: [dip ? dip.id : gene.id, ph.id], text: `CPIC maps ${gene.label}${dip ? " " + dip.label : ""} to the phenotype “${ph.label}”.` });
  }
  const phIds = nodes("Phenotype").map((n) => n.id);
  steps.push({ ids: [...phIds, rid], text: `A CPIC rule applies only if every gene in it matches: ${conditionText(src.condition)}${popLabel(src.population) ? ` (${popLabel(src.population)})` : ""}. Strength: ${src.classification}.` });
  steps.push({ ids: [rid, did], text: `It concerns ${rec.drug} → ${ACTIONS[rec.action].label}: “${truncate(src.recommendation, 170)}”` });
  const gl = nodes("Guideline")[0];
  if (gl) steps.push({ ids: [rid, gl.id, ...nodes("Publication").map((n) => n.id)], text: `Source: ${gl.label}, ${nodes("Publication").length} publication(s). Gene–drug evidence level: CPIC ${rec.cpic_levels.join(", ")}.` });
  if (nodes("ADR").length) steps.push({ ids: [did, ...nodes("ADR").map((n) => n.id)], text: `Known side effects of ${rec.drug} from SIDER, shown for context only.` });
  return steps;
}
function walkStart() { if (!S.path) return; S.walk = { steps: walkSteps(), i: -1 }; $("walk").hidden = false; walkGo(1); }
function walkGo(d) {
  if (!S.walk) return;
  const w = S.walk;
  w.i = Math.max(0, Math.min(w.steps.length - 1, w.i + d));
  const step = w.steps[w.i];
  const eles = S.cy.collection(step.ids.filter(Boolean).map((id) => S.cy.getElementById(id)));
  highlight(eles);
  frame(eles, 1.15, 90);
  $("walk-count").textContent = `${w.i + 1} / ${w.steps.length}`;
  $("walk-text").textContent = step.text;
  $("walk-prev").disabled = w.i === 0;
  $("walk-next").textContent = w.i === w.steps.length - 1 ? "Done" : "→";
  $("walk-next").onclick = w.i === w.steps.length - 1 ? walkStop : () => walkGo(1);
}
// fit `eles` into the canvas above a reserved bottom band, never zooming past maxZoom
function frame(eles, maxZoom, reserve) {
  const cy = S.cy, bb = eles.boundingBox(), W = cy.width(), H = cy.height() - reserve, pad = 60;
  const zoom = Math.min(maxZoom, (W - 2 * pad) / Math.max(bb.w, 1), (H - 2 * pad) / Math.max(bb.h, 1));
  const pan = { x: W / 2 - zoom * (bb.x1 + bb.w / 2), y: H / 2 - zoom * (bb.y1 + bb.h / 2) };
  if (MOTION) cy.animate({ zoom, pan, duration: 550, easing: "ease-in-out-cubic" }); else cy.viewport({ zoom, pan });
}
function walkStop() {
  if (!S.walk) return;
  S.walk = null; $("walk").hidden = true; clearHighlight();
  if (S.cy) MOTION ? S.cy.animate({ fit: { padding: 46 }, duration: 400 }) : S.cy.fit(undefined, 46);
}

// ---- tooltips (graph nodes + svg marks)
function showTip(html, ev) { const t = $("tooltip"); t.innerHTML = html; t.hidden = false; moveTip(ev); }
function moveTip(ev) {
  if (!ev) return;
  const t = $("tooltip"), pad = 14;
  const x = Math.min(ev.clientX + pad, window.innerWidth - t.offsetWidth - 8), y = Math.min(ev.clientY + pad, window.innerHeight - t.offsetHeight - 8);
  t.style.left = `${x}px`; t.style.top = `${y}px`;
}
function hideTip() { $("tooltip").hidden = true; }
function wireTooltips() {
  document.addEventListener("mouseover", (e) => { const el = e.target.closest?.("[data-tip]"); if (el) showTip(el.dataset.tip, e); });
  document.addEventListener("mousemove", (e) => { if (e.target.closest?.("[data-tip]")) moveTip(e); });
  document.addEventListener("mouseout", (e) => { if (e.target.closest?.("[data-tip]")) hideTip(); });
}

// ------------------------------------------------------------------ step 4: recommendations
function renderRecs() {
  const r = S.result;
  const counts = Object.fromEntries(ACTION_ORDER.map((a) => [a, r.recommendations.filter((x) => x.action === a).length]));
  let html = `<div class="view-head"><h2>What CPIC recommends for ${esc(r.sample_id || "this patient")}</h2>
    <p>Only recommendations whose full gene condition matches this patient are listed${r.activity_scores?.CYP2D6 != null ? ` (CYP2D6 activity score ${r.activity_scores.CYP2D6} included)` : ""}.
    The action is read from CPIC's own wording; each entry carries its evidence level and sources. Most important first.</p></div>
    <div class="recs-bar">${ACTION_ORDER.map((a) => `<button class="filter ${S.filter.has(a) ? "on" : ""}" data-a="${a}" title="${esc(ACTIONS[a].desc)}">${badge(a, ` <span class="n">${counts[a]}</span>`)}</button>`).join("")}
      <input id="rec-search" placeholder="Find a drug…" value="${esc(S.query)}"></div><div id="rec-groups"></div>`;
  $("view-recs").innerHTML = html;
  $("view-recs").querySelectorAll(".filter").forEach((b) => (b.onclick = () => {
    S.filter.has(b.dataset.a) ? S.filter.delete(b.dataset.a) : S.filter.add(b.dataset.a);
    b.classList.toggle("on"); renderRecGroups();
  }));
  $("rec-search").oninput = (e) => { S.query = e.target.value; renderRecGroups(); };
  renderRecGroups();
}

function renderRecGroups() {
  const r = S.result, q = S.query.trim().toLowerCase();
  let html = "";
  for (const a of ACTION_ORDER) {
    if (!S.filter.has(a)) continue;
    const recs = r.recommendations.filter((x) => x.action === a && (!q || x.drug.includes(q)));
    if (!recs.length) continue;
    html += `<div class="group"><div class="group-head">${badge(a, ` <span class="n">${recs.length}</span>`)}<p>${esc(ACTIONS[a].desc)}</p></div>
      ${recs.map((rec) => `<div class="rec" data-drug="${esc(rec.drug)}">
        <div class="rec-row"><span class="chev">›</span>
          <span><div class="drug">${esc(rec.drug)}</div><div class="genes">${esc([...new Set(rec.evidence.flatMap((s) => s.genes))].join(" + "))}</div></span>
          <span class="tag">CPIC ${esc(rec.cpic_levels.join(", "))}</span>
          <span class="first">${esc(rec.evidence[0].recommendation)}</span></div></div>`).join("")}</div>`;
  }
  $("rec-groups").innerHTML = html || `<p class="muted">No drugs match.</p>`;
  $("rec-groups").querySelectorAll(".rec-row").forEach((row) => (row.onclick = () => toggleRec(row.parentElement)));
}
function openRec(drug) {
  const el = document.querySelector(`.rec[data-drug="${CSS.escape(drug)}"]`);
  if (el && !el.classList.contains("open")) toggleRec(el);
  el?.scrollIntoView({ block: "center" });
}
function toggleRec(el) {
  const open = el.classList.toggle("open");
  el.querySelector(".rec-detail")?.remove();
  if (!open) return;
  const rec = S.result.recommendations.find((x) => x.drug === el.dataset.drug);
  const det = document.createElement("div");
  det.className = "rec-detail";
  det.innerHTML = `
    <div class="block"><h4>CPIC recommendation${rec.evidence.length > 1 ? `s (${rec.evidence.length} patient groups)` : ""}</h4>
      ${rec.evidence.map((s, i) => {
        let impl = "";
        try { impl = Object.entries(JSON.parse(s.implications || "{}")).map(([g, t]) => `<div><b>${esc(g)}:</b> ${esc(t)}</div>`).join(""); } catch { /* not JSON */ }
        return `<div class="source"><div class="ctx">${badge(s.action)}<span class="tag">${esc(conditionText(s.condition))}</span>
            ${popLabel(s.population) ? `<span class="tag">${esc(popLabel(s.population))}</span>` : ""}<span class="tag">${esc(s.classification)}</span><span class="tag">CPIC ${esc(s.cpic_level)}</span></div>
          <div class="text">${esc(s.recommendation)}</div>${impl ? `<div class="impl">${impl}</div>` : ""}
          ${(s.warnings || []).map((w) => `<div class="warn">Plausibility check: ${esc(w)}</div>`).join("")}
          <div class="actions"><button class="btn ghost small" data-path="${i}">Trace evidence path →</button></div></div>`;
      }).join("")}</div>
    <div class="block"><h4>Evidence</h4><div style="margin-bottom:6px">${esc(rec.guidelines.join("; "))}</div>
      <div class="pmids">${rec.citations.map((c) => pubmed(c.replace("PMID:", ""))).join("")}</div></div>
    <div class="block"><h4>Explanation</h4>
      <div class="explain graph"><div class="src-lbl">Summary from the graph</div>${esc(rec.explanation.text)}</div>
      <div class="llm-out"></div>
      <div class="gen-row">
        <button class="btn primary small" data-llm ${S.health?.llm ? "" : "disabled"}>Generate detailed explanation</button>
        <span class="muted">${S.health?.llm ? `Written by ${esc(S.health.llm_model)} from this patient's evidence, then checked against it. Takes a few seconds.`
          : "The local LLM is offline; start Ollama to enable this."}</span>
      </div></div>`;
  el.appendChild(det);
  det.querySelectorAll("[data-path]").forEach((b) => (b.onclick = () => openPath(rec, Number(b.dataset.path))));
  const out = det.querySelector(".llm-out"), row = det.querySelector(".gen-row");
  const cached = S.explanations[rec.drug];
  const short = det.querySelector(".explain.graph");
  if (cached) { out.innerHTML = explanationHtml(cached); row.hidden = true; short.hidden = true; } // detailed text includes it
  det.querySelector("[data-llm]").onclick = async (ev) => {
    const btn = ev.currentTarget, t0 = Date.now();
    btn.disabled = true;
    const tick = () => (out.innerHTML = `<div class="xp working"><div class="spinner"></div><div>
        <div class="xp-title">Writing with ${esc(S.health.llm_model)}… ${Math.round((Date.now() - t0) / 1000)} s</div>
        <div class="muted">reads only this patient's CPIC evidence → writes the explanation → checks every PMID, level, drug, allele, dose and phenotype it states</div></div></div>`);
    tick();
    const timer = setInterval(tick, 1000);
    try {
      S.explanations[rec.drug] = await api("/explain", { method: "POST", body: JSON.stringify({
        phenotypes: S.result.patient_phenotypes, activity_scores: S.result.activity_scores, drug: rec.drug,
        sample_id: S.result.sample_id || null, detail: "detailed" }) });
      out.innerHTML = explanationHtml(S.explanations[rec.drug]);
      row.hidden = true; short.hidden = true;
    } catch (e) { out.innerHTML = ""; toast(e.message); } finally { clearInterval(timer); btn.disabled = false; }
  };
}

const SOURCE_TAG = {
  llm: ["llm", "AI-written · checked"],
  pharmcat: ["pharmcat", "From the PharmCAT call"],
  cpic: ["cpic", "CPIC text, verbatim"],
};
function sectionsHtml(sections) {
  return sections.map((sec) => {
    const [cls, label] = SOURCE_TAG[sec.source] || ["cpic", sec.source];
    const lines = String(sec.text).split("\n").filter(Boolean);
    const body = lines.length > 1 ? `<ul>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : `<p>${esc(lines[0] || "")}</p>`;
    return `<div class="xp-sec"><div class="xp-sec-head"><h5>${esc(sec.title)}</h5><span class="src-tag ${cls}">${label}</span></div>${body}</div>`;
  }).join("");
}
function explanationHtml(ex) {
  const rej = ex.rejected_llm_output;
  const meta = [ex.model, ex.seconds != null ? `${ex.seconds} s` : null,
    ex.attempts > 1 && ex.source === "llm" ? "first draft corrected after the check" : null].filter(Boolean).join(" · ");
  if (ex.source === "llm") {
    const fixed = ex.corrected?.length ? `<details class="xp-fix"><summary>What the check caught in the first draft</summary>
        <ul>${ex.corrected[0].problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></details>` : "";
    return `<div class="xp"><div class="xp-head"><span class="badge standard"><span class="ic">✓</span>Detailed explanation · passed the evidence check</span>
        <span class="muted">${esc(meta)}</span></div>${sectionsHtml(ex.sections || [{ title: "Explanation", text: ex.text, source: "llm" }])}${fixed}
      <p class="xp-foot">The automatic check confirms every PMID, CPIC level, drug name, phenotype, star allele, zygosity claim and
        dose in the AI-written sections against this patient's evidence. It cannot verify every sentence of reasoning, so read
        them alongside the CPIC text. Sections tagged “CPIC text” and “PharmCAT call” are not generated.</p></div>`;
  }
  if (rej && typeof rej === "object")
    return `<div class="xp rejected"><div class="xp-head"><span class="badge adjust"><span class="ic">!</span>The model's text did not pass the evidence check</span>
        <span class="muted">${esc(meta)}</span></div>
      <p class="xp-note">Showing the same sections built only from the graph and the PharmCAT call. What the checker rejected:</p>
      <ul class="xp-problems">${rej.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
      ${ex.sections ? sectionsHtml(ex.sections) : ""}
      <details class="xp-fix"><summary>Show the rejected text</summary><p class="muted">${esc(rej.text)}</p></details></div>`;
  return `<div class="xp rejected"><div class="xp-head"><span class="badge none"><span class="ic">–</span>LLM unavailable</span></div>
    <p class="xp-note">${esc(rej || "")}</p>${ex.sections ? sectionsHtml(ex.sections) : ""}</div>`;
}

// ------------------------------------------------------------------ step 5: method
function renderMethod() {
  const kg = S.kg;
  $("view-method").innerHTML = `<div class="view-head"><h2>How a recommendation is produced</h2>
    <p>Every step is deterministic and traceable, except the optional LLM paraphrase, which is checked against the graph before it is shown.</p></div>
    <div class="method-grid">
      <div class="card method"><ol>
        <li><b>Genome → genotype.</b> bcftools cuts the CYP2C19 and CYP2D6 regions from the 1000 Genomes 30× GRCh38 VCF; allele-defining positions
          absent from the cohort VCF are read as reference; PharmCAT 3.4.0 calls the star-allele diplotype and activity score.</li>
        <li><b>Genotype → phenotype.</b> CPIC allele functions give the metabolizer phenotype (CYP2D6 via the activity score).</li>
        <li><b>Phenotype → evidence.</b> Neo4j returns CPIC recommendations whose full condition matches the patient: multi-gene rules
          (e.g. CYP2C19 + CYP2D6 for tricyclic antidepressants), CYP2D6 activity-score splits, and separate patient populations.</li>
        <li><b>Evidence → action.</b> The action is classified from CPIC's wording and cross-checked by pharmacology rules
          (prodrug activation vs. drug clearance); contradictions are flagged as “review”, never silently dropped.</li>
        <li><b>Action → explanation.</b> A local LLM may rephrase the evidence. Text citing a PMID or CPIC level not in the graph,
          naming an unrelated drug or stating a wrong phenotype is rejected. The LLM never decides.</li></ol></div>
      <div class="card method"><h3>Limitations</h3><ul>
        <li>Short-read WGS cannot see CYP2D6 copy-number changes (*5 deletion, duplications); calls assume two gene copies.</li>
        <li>A variant removed by the 1000 Genomes QC filters would be read as reference.</li>
        <li>Only genetics is used: co-medication (phenoconversion), age, kidney/liver function and indication are not modelled.</li>
        <li>Research prototype, not a clinical decision tool.</li></ul>
        ${kg ? `<h3 style="margin-top:16px">Knowledge graph</h3><p class="muted" style="margin-top:4px">${fmt(kg.nodes.Recommendation)} CPIC recommendations,
          ${fmt(kg.nodes.Drug)} drugs, ${fmt(kg.nodes.Gene)} genes, ${fmt(kg.nodes.Publication)} publications, ${fmt(kg.nodes.ADR)} adverse reactions, validated against the live CPIC API.</p>` : ""}
      </div></div>`;
}

init();
