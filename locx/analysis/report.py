"""M10: reports/progress_stats.md (+ reports/fig_*.png) from the scripts' outputs and live Fuseki queries.

  python -m locx.analysis.report [--run-id ID]

Every number comes from a file under reports/ or data/, or from a query in queries/. The only
hand-written text is reports/worked_examples_notes.json: the reviewer's notes on the picked worked
examples (e.g. a known normalization error), merged in verbatim.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401

from locx import evidence  # noqa: E402
from locx.config import CFG, DATA, INTERIM, QUERIES, REPORTS  # noqa: E402
from locx.io import read_jsonl  # noqa: E402
from locx.kg import fuseki  # noqa: E402
from locx.kg.ttl import LOCX  # noqa: E402
from locx import ontology as O  # noqa: E402

RUNS = DATA / "runs"
G = CFG["graphs"]
VERDICTS = ["Consistent", "Refinement", "Novel", "Conflicting", "Uninformative", "Error"]
# reference palette (dataviz skill), light mode
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def J(name):
    return json.loads((REPORTS / name).read_text())


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


# --- figures ---------------------------------------------------------------------------------------
def style(ax, title, ylabel=None):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=11, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, color=INK, fontsize=14, loc="left", pad=12)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=11)


def label_bars(ax, bars, fmt):
    for b in bars:
        ax.annotate(fmt(b.get_height()), (b.get_x() + b.get_width() / 2, b.get_height()),
                    xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color=INK, fontsize=10)


def figures(verdicts, claims, stats_rows, silver):
    files = []
    # 1. verdict distribution
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    vs = [v for v in VERDICTS if verdicts["verdicts"][v]]
    bars = ax.bar(vs, [verdicts["verdicts"][v] for v in vs], width=0.55, color=BLUE)
    label_bars(ax, bars, lambda h: f"{int(h):,}")
    style(ax, f"Verdicts of {verdicts['assertions']:,} assertions against GOA", "assertions")
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_verdicts.png")
    files.append("fig_verdicts.png")
    plt.close(fig)

    # 2. valid claims per publication year, by tier (two series, stacked)
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.jsonl")}
    by = {t: Counter() for t in ("silver", "discovery")}
    for c in claims:
        y = papers[c["pmid"]].get("year")
        if y:
            for t in by:
                if t in c["tiers"]:
                    by[t][int(y)] += 1
    years = list(range(min(min(v) for v in by.values() if v), max(max(v) for v in by.values() if v) + 1))
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    s = [by["silver"][y] for y in years]
    d = [by["discovery"][y] for y in years]
    ax.bar(years, s, width=0.8, color=BLUE, label="silver (GOA-cited)", edgecolor=SURFACE, linewidth=1)
    ax.bar(years, d, width=0.8, bottom=s, color=ORANGE, label=f"discovery ({CFG['corpus']['discovery_years'][0]}–{CFG['corpus']['discovery_years'][1]})", edgecolor=SURFACE, linewidth=1)
    style(ax, "Valid claims per publication year", "valid claims")
    ax.legend(frameon=False, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_claims_per_year.png")
    files.append("fig_claims_per_year.png")
    plt.close(fig)

    # 3. independent author groups behind novel assertions
    ng = Counter(min(int(r["n_groups"]), 5) for r in stats_rows if r["verdict"] == "Novel")
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
    xs = ["1", "2", "3", "4", "5+"]
    bars = ax.bar(xs, [ng[i] for i in range(1, 6)], width=0.55, color=BLUE)
    label_bars(ax, bars, lambda h: f"{int(h):,}")
    style(ax, "Novel assertions by number of independent author groups", "novel assertions")
    ax.set_xlabel("author groups supporting the assertion", color=INK2, fontsize=11)
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_novel_groups.png")
    files.append("fig_novel_groups.png")
    plt.close(fig)

    # 4. silver recall: ceiling vs LLM vs co-occurrence (exact, ±1 step)
    names = ["Ceiling\n(term in abstract)", "LLM\n(valid claims)", "Co-occurrence\nbaseline"]
    ex = [silver["coverage"]["exact"], silver["llm"]["recall_exact"], silver["cooccurrence_baseline"]["recall_exact"]]
    hi = [silver["coverage"]["hierarchical"], silver["llm"]["recall_hierarchical"],
          silver["cooccurrence_baseline"]["recall_hierarchical"]]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    x = range(len(names))
    b1 = ax.bar([i - 0.15 for i in x], ex, width=0.28, color=BLUE, label="exact GO term", edgecolor=SURFACE, linewidth=1)
    b2 = ax.bar([i + 0.15 for i in x], hi, width=0.28, color=ORANGE, label="±1 is_a/part_of step", edgecolor=SURFACE, linewidth=1)
    label_bars(ax, list(b1) + list(b2), lambda h: pct(h, 0))
    ax.set_xticks(list(x), names)
    ax.set_ylim(0, max(hi) * 1.25)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    style(ax, f"Recall of {silver['expected_pairs']:,} GOA pairs from silver abstracts", "recall")
    ax.legend(frameon=False, labelcolor=INK2, loc="upper right")
    fig.tight_layout()
    fig.savefig(REPORTS / "fig_recall.png")
    files.append("fig_recall.png")
    plt.close(fig)
    return files


# --- next steps (not built; updated with what the full run showed) ------------------------------
NEXT_STEPS = [
    "**Full-text articles** (open-access PMC / Europe PMC, BioC): GOA curators read full texts, so abstracts cap silver "
    "recall (ceiling in §6); section-aware chunking (results, figure legends) and longer contexts.",
    "**Author disambiguation beyond OpenAlex**: author groups now join papers that share an OpenAlex person (or an "
    "ORCID); OpenAlex itself sometimes splits one person or merges two, so check common names against institutions "
    "(ROR) and co-authors.",
    "**Grounded contexts (a second pass over the round-1 outputs)**: the conditions and cell types the model wrote "
    "are free text (`locx:FreeTextContext`), while GOA states its contexts as an RO relation plus a term "
    "(`locx:GOAContext`, e.g. *part of* CL neuron). A second pass, without re-running extraction, would ground "
    "each distinct context text: a dictionary proposes candidate terms from GO biological process, CL, Cellosaurus, "
    "UBERON and ChEBI, and the local model, shown the sentence, picks a candidate ID (it never writes one), the "
    "relation, and whether the text is a context at all (e.g. 'phosphorylated' is a protein state, not a "
    "condition). The result becomes the same context parts GOA uses, recorded as its own activity. A second model "
    "would judge a sample to measure the quality. Then claims and GOA rows with the same location can be compared "
    "under the same context, and context-dependent conflicts (§5) told apart from real ones.",
    "**Remaining name errors**: viral and other non-human proteins with human gene symbols (HIV-1 Tat → TAT), and "
    "triggers credited with the movement they cause (TNF → NF-κB); extend the synonym layer with an organism / "
    "'not a human protein' reading and a 'who moves' check.",
    "**Evidence-aware curation suggestions**: rank the upgrade candidates (literature support for GOA rows without "
    "experimental evidence) and conflicts with weak GOA evidence for curators; export them with their "
    "provenance.",
    "**Qualifier-aware verdicts**: GOA's 'NOT is_active_in' is not 'NOT located_in' (e.g. nuclear PD-L1); only "
    "NOT located_in rows should make a conflict, others a softer flag.",
    "**Organism-aware evidence**: use the per-claim organism field to mark claims from animal studies as weaker, "
    "orthology-like evidence for the human protein (like GOA's ISO code); check the field against PubTator's "
    "species annotations first, since nothing verifies it yet and about half of the claims state no organism.",
    "**Better grounding of free-text locations**: some OTHER texts the validator cannot ground have GO terms "
    "(e.g. primary cilia, basal body, intermembrane space, invadopodia; `other_ungrounded_top` in "
    "`reports/validation_<run>.json`); handle plurals and variants, add missing synonyms, and re-validate to win "
    "these claims back.",
    "**Validator-in-the-loop repair** (multi-round), and its effect on precision.",
    "**A second model** (e.g. Qwen3.6-35B-A3B or Gemma 4 E4B) on the same corpus; agreement as a confidence signal.",
    "**Human Protein Atlas** as a second reference; **orthology mapping** for mouse / rat studies.",
    "**Abstract-level claims** (protein and location in different sentences), compared with sentence-level claims.",
    "**Demo speed**: fetch the all-assertions table as TSV and warm the cache on start (first-load times in `reports/demo_check.json`).",
]


# --- worked examples --------------------------------------------------------------------------------
def worked_examples(run_id, claims, stats, papers, notes):
    run_graph = G["run_prefix"] + run_id
    mention_iri = {r["cid"]: r["m"] for r in fuseki.select(
        f"PREFIX locx: <{LOCX}> SELECT ?m ?cid WHERE {{ GRAPH <{run_graph}> {{ ?m locx:claimId ?cid }} }}")}
    by_a = defaultdict(list)
    for c in claims:
        by_a[f"{c['protein']['uniprot']}_{c['location']['go_id'].replace(':', '_')}_{c['polarity']}"].append(c)
    ok = lambda c: (c["source_type"] == "finding" and not {"protein_coref", "location_coref", "too_generic"} & set(c["flags"]))  # noqa: E731
    q_ex = (QUERIES / "worked_example.rq").read_text()
    q_goa = (QUERIES / "goa_for_protein.rq").read_text()
    out, picked = [], []
    for v in VERDICTS:
        ranked = sorted((s for s in stats if s["verdict"] == v),
                        key=lambda s: (-int(s["n_groups"]), -int(s["n_papers"]), s["assertion"]))
        seen, chosen = set(), []
        for s in ranked:
            if s["uniprot"] in seen:
                continue
            cs = sorted((c for c in by_a[s["assertion"]] if ok(c)), key=lambda c: int(c["pmid"]))
            if cs:
                chosen.append((s, cs[0]))
                seen.add(s["uniprot"])
            if len(chosen) == 3:
                break
        if not chosen:
            continue
        out += [f"### {v}", ""]
        for s, c in chosen:
            m = mention_iri[c["claim_id"]]
            rows = fuseki.select(q_ex.replace("%RUN_GRAPH%", run_graph).replace("%MENTION%", m)
                                 .replace("%ASSERTION%", f"{LOCX}assertion/{s['assertion']}"))
            r0 = rows[0]
            p = papers[c["pmid"]]
            authors = [a["name"] for a in p.get("authors") or [] if a.get("name")]
            auth = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            out.append(f"**{s['symbol']} — {s['location']} ({s['polarity']})** · {s['n_papers']} paper(s), "
                       f"{s['n_groups']} author group(s){' · context-dependent' if s['context'] == 'True' else ''}")
            out.append("")
            out.append(f"> {r0['sentence']}")
            out.append(">")
            out.append(f"> — {auth} ({r0.get('year', '?')}). *{r0['title']}* {r0.get('journal', '')}. "
                       f"PMID [{c['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{c['pmid']}/); "
                       f"method: {c['method']}; organism: {c['organism']}"
                       + (f"; condition: {'; '.join(c['conditions'])}" if c["conditions"] else ""))
            out.append("")
            goa = [r for r in rows if r.get("evidence")]
            if goa:
                agg = defaultdict(set)
                for r in goa:
                    key = (r["goaLabel"], r["qualifier"], r["negated"] == "true")
                    agg[key].add(r["evidence"] + (f" PMID {r['source'].rsplit('/', 1)[-1]}" if r.get("source") else ""))
                out.append("GOA side: " + "; ".join(
                    f"{'NOT ' if neg else ''}{q} *{lab}* [{', '.join(sorted(evs)[:4])}{' …' if len(evs) > 4 else ''}]"
                    for (lab, q, neg), evs in sorted(agg.items()))
                    + (f". Strongest evidence behind the verdict: **{evidence.GROUP_LABEL[s['goa_evidence']]}**"
                       if s.get("goa_evidence") in evidence.GROUP_LABEL else ""))
            else:
                g = fuseki.select(q_goa.replace("%PROTEIN%", f"http://purl.uniprot.org/uniprot/{s['uniprot']}"))
                out.append("GOA side: nothing in this term's lineage; GOA has for this protein: "
                           + ("; ".join(f"{r['label']} [{r['evidence']}]" for r in g[:8]) + (" …" if len(g) > 8 else "")
                              if g else "no CC annotation"))
            note = notes.get(c["claim_id"])
            if note:
                out.append("")
                out.append(f"*Reviewer note (Claude Opus 5.5):* {note}")
            out.append("")
            picked.append({"verdict": v, "claim_id": c["claim_id"], "assertion": s["assertion"], "pmid": c["pmid"],
                           "symbol": s["symbol"], "location": s["location"], "sentence": c["sentence_text"]})
    (REPORTS / "worked_examples_picked.json").write_text(json.dumps(picked, indent=2))
    return out


# --- runs / GPU hours --------------------------------------------------------------------------------
def runs_table():
    rows, total = [], 0.0
    for d in sorted(RUNS.iterdir()):
        if not (d / "run.json").exists():
            continue
        m = json.loads((d / "run.json").read_text())
        hours = gpu_h = req = 0
        for s in m.get("sessions", []):
            h = (datetime.fromisoformat(s["ended"]) - datetime.fromisoformat(s["started"])).total_seconds() / 3600
            hours += h
            gpu_h += h * len(s.get("endpoints") or [m["endpoint"]])
            req += s.get("requests", 0)
        total += gpu_h
        purpose = ("prompt tuning (sample)" if m.get("sample") else
                   "dev (prompt review)" if m["tiers"] == ["dev"] else
                   "expanded corpus" if "expanded" in m.get("input", "") else "MVP full run")
        status = "finished" if m.get("ended") else "running / incomplete"
        rows.append([f"`{m['run_id']}`", purpose, m["prompt_version"], req, f"{hours:.2f}", f"{gpu_h:.2f}", status])
    return rows, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=CFG["extract"]["main_run"])
    a = ap.parse_args()
    rid = a.run_id
    kg, corpus, cand = J("kg_stats.json"), J("corpus_stats.json"), J("candidates_stats.json")
    ext, peval = J(f"extract_{rid}.json"), J(f"prompt_eval_{rid}.json")
    val, rdf, ver = J(f"validation_{rid}.json"), J("rdf_stats.json"), J("verdicts.json")
    silver, prec = J("silver_eval.json"), J("precision.json")
    notes_path = REPORTS / "worked_examples_notes.json"
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else {}
    claims_all = list(read_jsonl(RUNS / rid / "claims_final.jsonl"))
    claims = [c for c in claims_all if c["valid"]]
    with open(REPORTS / "assertion_stats.tsv") as f:
        stats = list(csv.DictReader(f, delimiter="\t"))
    for s in stats:
        s["assertion"] = f"{s['uniprot']}_{s['go_id'].replace(':', '_')}_{s['polarity']}"
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.jsonl")}
    cands = {r["pmid"] for r in read_jsonl(INTERIM / "candidates.jsonl")}
    raw = {}
    for r in read_jsonl(RUNS / rid / "raw.jsonl"):
        if r["pmid"] in cands:
            raw[r["pmid"]] = r
    rc = [cl for r in raw.values() if r["status"] == "ok" for cl in r["claims"]]
    graphs = {g: fuseki.count(g) for g in [G["ontology"], G["go"], G["eco"], G["ro"], G["uniprot_locations"], G["uniprot_core"],
                                            G["goa"], G["uniprot"], G["papers"], G["abstracts"], G["assertions"],
                                            G["run_prefix"] + rid, G["support"], G["verdicts"], G["inferred"]]}
    fig_files = figures(ver, claims, stats, silver)

    md = [f"# locx progress statistics", "",
          f"Generated {datetime.now():%Y-%m-%d %H:%M} by `make report` from `reports/*.json` and live SPARQL queries. "
          f"Run `{rid}` (prompt {json.loads((RUNS / rid / 'run.json').read_text())['prompt_version']}, "
          f"{json.loads((RUNS / rid / 'run.json').read_text())['model']}).", ""]

    md += ["## 1. Knowledge graph", ""]
    kind = {G["ontology"]: "our ontology", G["go"]: "ontology (official release)", G["eco"]: "ontology (official release)",
            G["ro"]: "ontology (official release)", G["uniprot_locations"]: "vocabulary (UniProt, as published)",
            G["uniprot_core"]: "ontology (UniProt core, as published)",
            G["support"]: "derived (support process)", G["verdicts"]: "derived (verdict process)",
            G["inferred"]: "derived (OWL 2 RL reasoner)"}
    md += table(["named graph", "kind", "triples"], [[f"`{g}`", kind.get(g, "data"), f"{n:,}"] for g, n in graphs.items()])
    gc, ga, gu = kg["go_cc"], kg["goa_human_cc"], kg["uniprot_human"]
    rel = kg.get("releases", {})
    md += ["", f"GO {gc['go_data_version']}: {gc['cc_terms']:,} CC terms ({gc['is_a_edges']:,} is_a, {gc['part_of_edges']:,} part_of; "
           f"{gc['non_human_terms']} non-human). GOA human: {ga['cc_rows']:,} CC rows, {ga['not_rows']} NOT rows, "
           f"{ga['proteins']:,} proteins, {ga['distinct_pmids']:,} cited PMIDs. UniProt human Swiss-Prot (UniProt RDF, `up:` "
           f"vocabulary): {gu['proteins']:,} proteins, {gu['proteins_with_location_annotation']:,} with a subcellular location "
           f"annotation. Official releases loaded unmodified: {', '.join(f'`{v}`' for v in rel.values() if v)}. "
           f"GOA evidence as ECO terms, relations as RO terms; {ga.get('context_parts', 0):,} GOA context parts "
           f"(relation + term) parsed. GO CC dictionary: {gc['dictionary_texts']:,} surface texts.", ""]
    if (REPORTS / "kg_schema.json").exists():      # make schema (scripts/kg_schema.py, kg_schema_fig.py)
        sch = json.loads((REPORTS / "kg_schema.json").read_text())
        home, extra = {}, defaultdict(list)
        for g in sch["graphs"]:
            for c in g["classes"]:
                if c["typed_here"]:
                    home[c["class"]] = (g["name"], c["example_subject"], len(c["fields"]))
                elif c["fields"]:
                    extra[c["class"]].append(f"{len(c['fields'])} in {g['name']}")
        md += ["**Schema** (read from the live data; every field with type and example in `kg_schema.md`; "
               "figures `fig_kg_papers.png`, `fig_kg_claims.png`, `fig_kg_curation.png`, `fig_kg_uniprot.png`, "
               "`fig_kg_schema.png`):", ""]
        md += table(["class", "typed in", "fields", "example IRI"],
                    [[f"`{c}`", g, f"{n}" + (" + " + ", ".join(extra[c]) if extra[c] else ""), f"`{ex}`"]
                     for c, (g, ex, n) in home.items()])
        md += [""]
    if (REPORTS / "ontology.json").exists():       # make check-ontology (scripts/check_ontology.py)
        on = json.loads((REPORTS / "ontology.json").read_text())
        sm, hr = on["sample"], on.get("hermit") or {}
        g = O.graph()
        n_cls = sum(1 for s_ in g.subjects(O.expand("rdf:type"), O.expand("owl:Class")) if str(s_).startswith(str(O.LOCX)))
        n_ind = sum(1 for _ in g.subjects(O.expand("rdf:type"), O.expand("owl:NamedIndividual")))
        md += [f"**Ontology** (`ontology/locx.owl.ttl`, OWL 2, hand-maintained, the source of truth for the code; "
               f"version {on['version']}): {n_cls} locx classes, {n_ind} named individuals (the values of the value sets: one OWL "
               f"class with its individuals each). Coverage: {'every' if on['coverage_ok'] else 'NOT every'} class and predicate in "
               f"our data graphs is declared; outside IDs checked: {len(on['outside_ids']['checked'])}, problems "
               f"{len(on['outside_ids']['problems'])}. HermiT ({hr.get('imports', 'not run')}): "
               f"{'consistent' if hr.get('consistent') else 'NOT consistent' if hr else 'not run'}, "
               f"{len(hr.get('unsatisfiable_classes') or [])} unsatisfiable classes. Protégé sample {sm['symbol']} "
               f"({sm['triples']:,} triples): {sm['triples_checked']:,} checked against domains, ranges, functional "
               f"properties and disjoint classes, {sum(sm['problems'].values())} problems.", ""]
    if (REPORTS / "reasoning.json").exists():      # make reason (scripts/reason.py)
        rs = json.loads((REPORTS / "reasoning.json").read_text())
        md += [f"**Reasoning** ({rs['reasoner']}): {rs['inferred_graph_triples']:,} inferred triples in "
               f"`urn:locx:graph:inferred`; consistency checks over all data ("
               + ", ".join(f"{k.replace('reason_', '').replace('_', ' ')} {v['violations']}" for k, v in rs["consistency"].items())
               + f"): {'consistent' if rs['consistent'] else 'NOT consistent'}.", ""]

    md += ["## 2. Corpus", ""]
    rows = []
    with_claim = Counter(t for r in raw.values() if r["status"] == "ok" and r["claims"] for t in r["tiers"])
    with_valid = Counter(t for p in {c["pmid"] for c in claims} for t in papers[p]["tiers"])
    for t in ("dev", "silver", "discovery"):
        pt, ct = corpus["per_tier"][t], cand["per_tier"][t]
        rows.append([t, pt["selected"], pt["kept"], ct["kept"],
                     with_claim[t] if t != "dev" else "–", with_valid[t] if t != "dev" else "–",
                     pct(pt["share_with_orcid"], 0)])
    md += table(["tier", "selected", "with abstract + PubTator", "kept by prefilter", "≥1 claim", "≥1 valid claim", "with ORCID"], rows)
    cc = CFG["corpus"]
    y0, y1 = cc["discovery_years"]
    query = "localization terms" + (" AND protein*" if cc.get("discovery_protein_filter", True) else " (no protein* filter)")
    scope = (f"every Europe PMC hit per year {y0}–{y1}" if cc["discovery_cap"] == 0 else
             f"{cc['discovery_cap']:,} papers, {cc['discovery_cap'] // (y1 - y0 + 1):,} per year {y0}–{y1}, top Europe PMC relevance")
    md += ["", f"Discovery: {scope}, query {query}, kept if ≥1 human Swiss-Prot gene. Gene mentions: {cand['gene_mentions']['human']:,} human, "
           f"{cand['gene_mentions']['non_human']:,} non-human ({pct(cand['gene_mentions']['share_non_human'], 0)}, no orthology mapping). "
           "The dev tier was used for prompt review only.", ""]

    md += ["## 3. Extraction", ""]
    tp = ext.get("throughput_this_session", {})
    md += [f"{ext['abstracts']:,} abstracts, error rate {pct(ext['error_rate'], 2)}, bad JSON {pct(ext['bad_json_rate'], 2)} "
           f"({ext['truncated_max_tokens']} hit max_tokens). {len(rc):,} raw claims "
           f"({len(rc) / sum(1 for r in raw.values() if r['status'] == 'ok'):.2f} per abstract): "
           f"finding {sum(c['source_type'] == 'finding' for c in rc):,}, background {sum(c['source_type'] == 'background' for c in rc):,}; "
           f"hedged {sum(c['certainty'] == 'hedged' for c in rc):,}; absent {sum(c['polarity'] == 'absent' for c in rc):,}; "
           f"OTHER location {sum(c['location'] == 'OTHER' for c in rc):,}. "
           f"Throughput {tp.get('abstracts_per_s', '?')} abstracts/s in the last session "
           f"({len(json.loads((RUNS / rid / 'run.json').read_text())['sessions'][-1].get('endpoints') or [1])} GPU(s), "
           f"concurrency {CFG['llm']['concurrency']} per GPU); "
           f"tokens per abstract: prompt {ext['tokens']['prompt_mean']:,}, completion {ext['tokens']['completion_mean']}.", ""]
    md += table(["tier", "abstracts", "claims", "claims / abstract", "≥1 claim"],
                [[t, v["abstracts"], f"{v['claims']:,}", v["claims_per_abstract"], pct(v["share_with_claim"], 0)]
                 for t, v in ext["per_tier"].items()])
    v1d, v2d = J("prompt_eval_gemma4-31b_20261116-1636.json"), J("prompt_eval_gemma4-31b_20261116-1649.json")
    v1s, v2s = J("prompt_eval_gemma4-31b_20261116-1645.json"), J("prompt_eval_gemma4-31b_20261116-1651.json")
    md += ["", "Prompt v1 → v2 (automatic checks, `locx/extract/check.py`; dev = 116 abstracts, silver = fixed sample of 200):", ""]
    md += table(["check", "v1 dev", "v2 dev", "v1 silver", "v2 silver"], [
        ["'absent' with only a reduction cue", v1d["absent_reduction_only"], v2d["absent_reduction_only"],
         v1s["absent_reduction_only"], v2s["absent_reduction_only"]],
        ["method not stated although the abstract names one", pct(v1d["finding_method_not_stated_but_abstract_names_one"], 0),
         pct(v2d["finding_method_not_stated_but_abstract_names_one"], 0),
         pct(v1s["finding_method_not_stated_but_abstract_names_one"], 0), pct(v2s["finding_method_not_stated_but_abstract_names_one"], 0)],
        ["organism not stated although a non-human species is named", pct(v1d["finding_organism_not_stated_but_nonhuman_word"], 0),
         pct(v2d["finding_organism_not_stated_but_nonhuman_word"], 0),
         pct(v1s["finding_organism_not_stated_but_nonhuman_word"], 0), pct(v2s["finding_organism_not_stated_but_nonhuman_word"], 0)],
        ["silver recall vs GOA (lineage match)", "–", "–", pct(v1s["silver"]["recall"]), pct(v2s["silver"]["recall"])]])

    md += ["", "## 4. Validation", ""]
    t = val["totals"]
    flag_rows = [[k[5:], f"{v:,}", "invalid" if k[5:] in ("protein_not_in_sentence", "location_not_in_sentence", "other_ungrounded") else "warning / info"]
                 for k, v in sorted(t.items()) if k.startswith("flag_")]
    flag_rows += [[f, f"{rdf['quality_flags'].get(f, 0):,}", "invalid (SHACL)" if f == "impossible_location" else "warning (SHACL)"]
                  for f in ("impossible_location", "too_generic")]
    md += [f"{t['claims_raw']:,} raw claims → {t['claims']:,} after merging duplicates; {t.get('abstracts_bad_json', 0)} abstracts with bad JSON.", ""]
    md += table(["flag", "claims", "effect"], flag_rows)
    md += ["", f"**Valid claims: {rdf['valid']:,} of {rdf['claims']:,} ({pct(rdf['share_valid'])})**; "
           + ", ".join(f"{k} {pct(v['share_valid'])}" for k, v in rdf["per_tier"].items())
           + f". SHACL gate shapes conform: {rdf['gate_conforms']}. Repair loop: not built (Later).", ""]

    md += ["## 5. Verdicts", ""]
    md += table(["verdict", "assertions", "share", "silver", "discovery"],
                [[v, f"{ver['verdicts'][v]:,}", pct(ver["verdicts_share"][v]), ver["per_tier"]["silver"][v],
                  ver["per_tier"]["discovery"][v]] for v in VERDICTS])
    ev = ver["goa_evidence_behind_verdict"]
    md += ["", f"{ver['assertions']:,} assertions (unique protein + GO term + polarity). GOA rows behind the verdict include "
           f"experimental evidence for {ev['Consistent'].get('experimental', 0):,} of {sum(ev['Consistent'].values()):,} consistent, "
           f"{ev['Refinement'].get('experimental', 0)} of {sum(ev['Refinement'].values())} refinement and "
           f"{ev['Conflicting'].get('experimental', 0)} of {sum(ev['Conflicting'].values())} conflicting assertions. "
           f"Context-dependent (a supporting mention states a condition): {ver['context_dependent']:,}. "
           f"Supported by a paper that GOA itself cites: {ver['curated_from_same_paper']:,}.", ""]
    sup = ver.get("support_by_verdict")
    if sup:
        bins = ["1", "2", "3", "4", "5+"]
        md += ["**Support by independent author groups.** Number of assertions per verdict backed by 1, 2, … author "
               "groups; finding = at least one paper states it as its own result; hedged = hedged in every paper:", ""]
        md += table(["verdict", "assertions"] + [f"{b} group{'s' if b != '1' else ''}" for b in bins]
                    + ["≥2 groups", "mean groups", "median papers", "finding", "hedged"],
                    [[v, f"{d['assertions']:,}"] + [f"{d['by_n_groups'].get(b, 0):,}" for b in bins]
                     + [pct(d["share_2plus_groups"]), f"{d['mean_groups']:.2f}", f"{d['median_papers']:g}",
                        pct(d["share_with_finding"]), pct(d["share_hedged_in_all_papers"])] for v, d in sup.items()])
        md += [""]
    eg = ver.get("goa_evidence_group_behind_verdict")
    if eg:
        md += ["**Strength of the GOA evidence behind the verdict.** Each GOA row carries a GO evidence code; codes are "
               "grouped by strength (`locx/evidence.py`) and each assertion is labelled with the strongest group among the "
               "GOA rows behind its verdict:", ""]
        md += table(["verdict"] + [evidence.GROUP_LABEL[g] for g, _, _ in evidence.GROUPS],
                    [[v] + [f"{eg[v].get(g, 0):,}" for g, _, _ in evidence.GROUPS] for v in eg])
        up = ver["upgrade_candidates"]
        md += ["", f"**Upgrade candidates:** {sum(up.values()):,} assertions ({up['Consistent']:,} consistent, "
               f"{up['Refinement']:,} refinement) where papers report a location that GOA has only from an author "
               "statement, a curator inference, a computational method or an automatic (electronic) annotation; the "
               "literature could give these annotations experimental support. "
               f"**Conflicts:** {ver['conflicting_with_experimental_goa']:,} of {ver['verdicts']['Conflicting']:,} "
               "conflicting assertions contradict a GOA row with experimental evidence; the rest contradict weaker "
               "evidence, where GOA may be the side to revisit.", ""]
    md += ["Caveats: the synonym layer (prompt v3) fixes most PubTator normalization errors on ambiguous symbols (TAZ, "
           "p27, Drp1, COX-2 …; `reports/synonym_stats.md`), but some remain among the top novel assertions: names of "
           "viral proteins mapped to human genes (HIV-1 Tat → TAT, tyrosine aminotransferase) and a trigger credited "
           "with the movement it causes (TNF-induced NF-κB nuclear translocation read as TNF in the nucleus). "
           "Conflicting is mostly absent-polarity claims (translocation / disease context) against GOA nucleus "
           "annotations. Author groups are approximate (no disambiguation without ORCID; very common name keys can "
           "chain unrelated labs into one group).", ""]

    md += ["## 6. Evaluation", ""]
    L, B = silver["llm"], silver["cooccurrence_baseline"]
    md += [f"Silver recall: {silver['expected_pairs']:,} expected GOA pairs (low-throughput experimental evidence; "
           f"{silver['removed_protein_not_candidate']:,} removed because the protein is not a candidate).", ""]
    md += table(["", "recall exact", "recall ±1 step", "pairs produced", "agreement with GOA (exact / ±1)"], [
        ["ceiling (protein and term are candidates)", pct(silver["coverage"]["exact"]), pct(silver["coverage"]["hierarchical"]), "", ""],
        ["**LLM**", f"**{pct(L['recall_exact'])}**", f"**{pct(L['recall_hierarchical'])}**", f"{L['pairs']:,}",
         f"{pct(L['goa_agreement_exact'])} / {pct(L['goa_agreement_hierarchical'])}"],
        ["co-occurrence baseline", pct(B["recall_exact"]), pct(B["recall_hierarchical"]), f"{B['pairs']:,}",
         f"{pct(B['goa_agreement_exact'])} / {pct(B['goa_agreement_hierarchical'])}"]])
    pa = prec["all"]
    sj = prec.get("second_judge")
    mvp = J("precision_mvp/precision.json") if (REPORTS / "precision_mvp" / "precision.json").exists() else None
    bv = prec.get("by_verdict", {})
    md += ["", f"Precision (judged by {', '.join(prec['judges'])}; rubric `reports/precision_rubric.md`; random valid "
           f"claims of run `{rid}`, stratified by tier): **{pa['correct']}/{pa['n']} = {pct(pa['precision'])}** "
           f"(95% Wilson {pct(pa['wilson95'][0])}–{pct(pa['wilson95'][1])}); discovery {pct(prec['discovery']['precision'])} "
           f"(n = {prec['discovery']['n']}), silver {pct(prec['silver']['precision'])} (n = {prec['silver']['n']}). "
           "By verdict: " + ", ".join(f"{v} {x['correct']}/{x['n']}" for v, x in bv.items()) + ". Errors: "
           + ", ".join(f"{k} {v}" for k, v in prec["error_types"].items()) + "."
           + (f" A second judge re-judged a random {sj['n']} blind: agreement {pct(sj['agreement'])}, Cohen's kappa "
              f"{sj['cohen_kappa']:.2f}." if sj else "")
           + (f" (MVP sheet, {mvp['all']['n']} claims: {pct(mvp['all']['precision'])}, `reports/precision_mvp/`.)" if mvp else "")
           + " All judges are the same LLM family that helped design the pipeline, not independent human annotators; "
           "mouse / rat studies of a protein's human counterpart count as correct (organism is not judged).",
           "", f"*{silver['caveat']}*", ""]

    md += ["## 7. Runs and GPU hours", ""]
    rr, total = runs_table()
    md += table(["run", "purpose", "prompt", "requests", "wall h", "GPU h", "status"], rr)
    md += ["", f"Total GPU hours of finished sessions: **{total:.2f}** (RTX A6000; vLLM {json.loads((RUNS / rid / 'run.json').read_text())['vllm_version']}).", ""]

    fig_files += [f for f in ("fig_kg_papers.png", "fig_kg_claims.png", "fig_kg_curation.png", "fig_kg_uniprot.png",
                              "fig_kg_schema.png") if (REPORTS / f).exists()]   # make schema
    md += ["## 8. Figures", ""] + [f"![{f}]({f})" for f in fig_files] + [""]
    md += ["## 9. Worked examples (3 per verdict)", "",
           "Picked by a fixed rule: valid 'finding' mentions without coreference warnings, strongest support first "
           "(author groups, then papers), three different proteins per verdict. Known errors are noted, not skipped.", ""]
    md += worked_examples(rid, claims, stats, papers, notes)
    md += ["## 10. Next steps (not built)", ""] + [f"- {x}" for x in NEXT_STEPS] + [""]
    (REPORTS / "progress_stats.md").write_text("\n".join(md) + "\n")
    print(f"[report] reports/progress_stats.md ({len(md)} lines), figures: {', '.join(fig_files)}")


if __name__ == "__main__":
    main()
