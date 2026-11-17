"""Protein graph pages of demo v2: Translocations, Network, Timeline.

Each page takes a small context object from app/v2.py (cached query runner, colours, protein picker, ...) so this
module does not import the Streamlit script itself. All locations are the GO terms as claimed (no roll-up to broad
compartments). All text from the data is escaped before it goes into HTML.
"""
import html
import math
import re
from collections import Counter, defaultdict

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

import data as D
import evidence_ui as EV

esc = html.escape
INK, INK2, MUTED, LINE, SURF, EMPTY = "#0b0b0b", "#52514e", "#8b8a85", "#d0cfca", "#fcfcfb", "#f0efec"
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"
TAG = re.compile(r"</?(sub|sup|i|b|em|strong)>", re.I)
PHYSICS = """{
  "physics": {"barnesHut": {"gravitationalConstant": -9000, "springLength": 150, "springConstant": 0.03,
                            "avoidOverlap": 0.3}, "stabilization": {"iterations": 250}},
  "interaction": {"hover": true, "tooltipDelay": 120},
  "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}, "smooth": {"type": "continuous"}}
}"""


def clean(text):
    """Abstract sentences keep simple HTML tags from Europe PMC (e.g. <sub>); drop them for display."""
    return TAG.sub("", text or "")


def local(iri):
    return D.local(iri) if iri else ""


def _protein_data(ctx, acc):
    lit_res = ctx.cached("protein_literature", acc)
    goa_res = ctx.cached("protein_goa", acc)
    return lit_res[0], goa_res[0], [lit_res, goa_res]


def _title(ctx, acc, opts, what):
    p = opts[acc]
    st.markdown(f"## {esc(p['symbol'])} · {what} <span style='font-weight:400;color:{MUTED};font-size:0.6em'>"
                f"{esc(p.get('name', ''))} · {acc}</span>", unsafe_allow_html=True)


def verdict_legend(colors, extra=""):
    return ("<div style='display:flex;flex-wrap:wrap;gap:4px 14px;font-size:0.85em;color:#52514e'>" + "".join(
        f"<span><span style='display:inline-block;width:10px;height:10px;border-radius:2px;background:{colors[v]};"
        f"margin-right:5px'></span>{v}</span>" for v in D.VERDICTS[:5]) + extra + "</div>")


# --- Translocations page -----------------------------------------------------------------------------
BASELINE = re.compile(r"\b(basal|baseline|rest(ing)?|unstimulated|non-?stimulated|untreated|control|normal|steady[- ]state|"
                      r"fed|nutrient[- ]rich|quiescent|physiological|homeostatic|unstressed|wild[- ]type|wt)\b", re.I)


def translocations(mrows, lineage):
    """Movements between GO terms: (from, to, directed) -> {"papers", "conditions" Counter, "examples"}.

    A paper counts when it places the protein at one GO term with no condition (or a baseline one: basal, untreated,
    control, fed ...) and at another term under a stated condition: an arrow from the baseline term to the condition's
    term. If a paper has only condition-specific terms, two terms under different conditions get an undirected edge.
    Terms on each other's lineage (nucleus / nucleoplasm, is_a or part_of) are the same place and never form an edge."""
    same = {(a, b) for a, b in lineage} | {(b, a) for a, b in lineage}
    per = defaultdict(lambda: {"base": set(), "cond": defaultdict(set), "sent": {}})
    claims = {}
    for r in mrows:
        if local(r["polarity"]) != "Present":
            continue
        c = claims.setdefault(r["m"], {**r, "conds": set()})
        if r.get("condition"):
            c["conds"].add(r["condition"])
    for c in claims.values():
        p = per[c["paper"]]
        real = {x for x in c["conds"] if not BASELINE.search(x)}
        if real:
            p["cond"][c["term"]] |= real
            p["sent"][c["term"]] = c["sentence"]
        else:
            p["base"].add(c["term"])
            p["sent"].setdefault(c["term"], c["sentence"])
        p["year"] = c.get("year")
    edges = defaultdict(lambda: {"papers": set(), "conditions": Counter(), "examples": []})
    for paper, p in per.items():
        found = []
        for t, conds in p["cond"].items():
            if any(t == b or (t, b) in same for b in p["base"]):
                continue             # also at (or within) a baseline place: no movement
            found += [(s, t, True, conds) for s in p["base"]]
        if not p["base"]:
            ts = sorted(p["cond"])
            for i in range(len(ts)):
                for j in range(i + 1, len(ts)):
                    if (ts[i], ts[j]) not in same and p["cond"][ts[i]] != p["cond"][ts[j]]:
                        found.append((ts[i], ts[j], False, p["cond"][ts[i]] | p["cond"][ts[j]]))
        for s, t, directed, conds in found:
            e = edges[(s, t, directed)]
            if paper not in e["papers"]:
                e["papers"].add(paper)
                e["conditions"].update(conds)
                e["examples"].append({"paper": paper, "year": p.get("year"), "conditions": sorted(conds),
                                      "from": clean(p["sent"].get(s, "")), "to": clean(p["sent"].get(t, ""))})
    return edges


def translocations_page(ctx):
    acc, opts, pres = ctx.picker("Protein", "transprot")
    _title(ctx, acc, opts, "translocations")
    lit, goa, res = _protein_data(ctx, acc)
    m_res = ctx.cached("protein_mentions", acc)
    lin_res = ctx.cached("term_lineage", tuple(sorted({x["term"] for x in lit})))
    edges = translocations(m_res[0], [(r["term"], r["ancestor"]) for r in lin_res[0]])
    st.caption("Movements between locations that the papers describe, on the GO terms as stated. A paper counts when it "
               "places the protein at one location with no condition (or a baseline one: basal, untreated, control, fed …) "
               "and at another location under a stated condition (treatment, stress, mutation, disease …): the arrow goes "
               "from the baseline place to the condition's place. Dashed = both places only under different conditions. "
               "Locations on each other's GO lineage (e.g. nucleus and nucleoplasm) are the same place. Built "
               "automatically from the claims: a heuristic, not a curated pathway.")
    if not edges:
        st.info("No paper places this protein at two different locations under different conditions.")
        ctx.sparql(m_res, lin_res, *res)
        return
    ranked = sorted(edges.items(), key=lambda kv: (-len(kv[1]["papers"]), kv[0]))
    num = {k: i for i, (k, _) in enumerate(ranked, 1)}
    label = {x["term"]: x["label"] for x in lit}
    present = {x["term"]: x for x in lit if local(x["polarity"]) == "Present"}
    c1, c2, _ = st.columns([1.3, 1.3, 2])
    max_n = max(len(e["papers"]) for _, e in ranked)
    min_p = c1.slider("Min. papers per arrow", 1, max(2, min(max_n, 20)), 1 if max_n < 5 else 2, key=f"tmin_{acc}")
    max_e = c2.slider("Max. arrows", 5, 60, 25, key=f"tmax_{acc}")
    shown = [(k, e) for k, e in ranked if len(e["papers"]) >= min_p][:max_e]

    net = Network(height="620px", width="100%", directed=True, bgcolor=SURF, cdn_resources="in_line")
    nodes = {t for (s, t2, _), _ in shown for t in (s, t2)}
    top = max([int(present[t]["nPapers"]) for t in nodes if t in present] or [1])
    for t in nodes:
        x = present.get(t)
        v = local(x["verdict"]) if x else ""
        n = int(x["nPapers"]) if x else 0
        net.add_node(t, label=label.get(t, local(t)), shape="dot", size=10 + 26 * math.sqrt(n / top),
                     color={"background": ctx.COLOR.get(v, EMPTY), "border": INK2},
                     font={"size": 15, "color": INK, "strokeWidth": 4, "strokeColor": SURF},
                     title=f"{label.get(t, '')} ({local(t).replace('_', ':')})\n"
                           + (f"{v} · {n} papers · {x['nGroups']} author groups" if x else "no present claim"))
    for (s, t, directed), e in shown:
        n = len(e["papers"])
        net.add_edge(s, t, width=1 + 1.6 * math.log1p(n), color=INK, dashes=not directed, label=str(num[(s, t, directed)]),
                     arrows={"to": {"enabled": True}, "from": {"enabled": not directed}},
                     font={"size": 13, "color": INK, "strokeWidth": 5, "strokeColor": SURF, "bold": True},
                     smooth={"type": "curvedCW", "roundness": 0.15} if directed else {"type": "curvedCCW", "roundness": 0.4},
                     title=f"#{num[(s, t, directed)]} {label.get(s, '')} {'→' if directed else '↔'} {label.get(t, '')}: "
                           f"{n} papers\nconditions: " + "; ".join(f"{c} ({k})" for c, k in e["conditions"].most_common(8)))
    net.set_options(PHYSICS)
    left, right = st.columns([3, 2])
    with left:
        components.html(net.generate_html(notebook=False), height=640)
        st.markdown(verdict_legend(ctx.COLOR), unsafe_allow_html=True)
        st.caption(f"{len(shown)} of {len(edges)} movements shown (most papers first). Node colour = verdict of the "
                   "protein at that location, size = papers; arrow width = papers; the number is the row in the table. "
                   "Hover an arrow for its conditions; drag nodes to rearrange.")
    with right:
        tab = pd.DataFrame([{"#": num[(s, t, d)], "from": label.get(s, ""), "to": label.get(t, ""),
                             "kind": "move" if d else "both, different conditions", "papers": len(e["papers"]),
                             "top conditions": "; ".join(f"{c} ({k})" for c, k in e["conditions"].most_common(4))}
                            for (s, t, d), e in ranked])
        ev = st.dataframe(tab, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"trans_{acc}", height=min(38 + 35 * len(tab), 420))
        pick = ev.selection.rows[0] if ev and ev.selection.rows else 0
        (s, t, d), e = ranked[pick]
        st.markdown(f"**#{num[(s, t, d)]} {esc(label.get(s, ''))} {'→' if d else '↔'} {esc(label.get(t, ''))}**: "
                    f"{len(e['papers'])} papers (select a row for another movement)")
        for x in sorted(e["examples"], key=lambda x: -(int(x["year"]) if x.get("year") else 0))[:8]:
            pm = local(x["paper"])
            sents = [x["to"]] if x["to"] == x["from"] or not x["from"] else [x["from"], x["to"]]
            st.markdown(f"<div style='border-left:3px solid {LINE};padding:2px 0 2px 10px;margin:6px 0;font-size:0.92em'>"
                        + "<br>".join(esc(z) for z in sents)
                        + f"<br><small><a href='{PUBMED}{pm}/' target='_blank'>PMID {pm}</a> · {esc(str(x.get('year') or '?'))}"
                          f" · condition: {esc('; '.join(x['conditions']))}</small></div>", unsafe_allow_html=True)
    ctx.sparql(m_res, lin_res, *res, pres)


# --- Network page ------------------------------------------------------------------------------------
def _paper_groups(papers, authors):
    """Union-find over papers: same group when they share an ORCID or >= 2 author name keys (SPEC M8 rule)."""
    parent = {p: p for p in papers}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    ids = defaultdict(set)
    for a in authors:
        if a["paper"] in parent:
            ids[a["paper"]].add("key:" + a["key"])
            if a["person"].startswith("https://orcid.org/"):
                ids[a["paper"]].add("orcid:" + a["person"])
    ps = list(parent)
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            shared = ids[ps[i]] & ids[ps[j]]
            if any(x.startswith("orcid:") for x in shared) or sum(x.startswith("key:") for x in shared) >= 2:
                parent[find(ps[i])] = find(ps[j])
    groups = defaultdict(list)
    for p in ps:
        groups[find(p)].append(p)
    return list(groups.values())


def network_page(ctx):
    acc, opts, pres = ctx.picker("Protein", "netprot")
    _title(ctx, acc, opts, "network")
    st.caption("The protein, its literature assertions (edges coloured by verdict, width = papers) and its GOA "
               "annotations (grey edges, darker = stronger evidence), on the GO is_a / part_of hierarchy. Optional: the "
               "supporting papers, clustered by independent author group, and other proteins at the same locations. "
               "Drag nodes, scroll to zoom, hover for details.")
    c1, c2, c3, c4 = st.columns(4)
    n_terms = len(ctx.cached("protein_literature", acc)[0]) + len({g["term"] for g in ctx.cached("protein_goa", acc)[0]})
    steps = c1.slider("GO hierarchy: steps up", 0, 3, 1 if n_terms <= 25 else 0, key=f"steps_{acc}",
                      help="off by default for proteins with many locations, to keep the graph readable")
    show_goa = c2.toggle("GOA annotations", value=True)
    show_papers = c3.toggle("Supporting papers + author groups", value=False)
    per_term = c4.slider("Papers per location (most cited)", 1, 10, 4, disabled=not show_papers)
    lit, goa, res = _protein_data(ctx, acc)
    symbol = opts[acc]["symbol"]
    pres_terms = sorted({(x["term"], x["label"]) for x in lit if local(x["polarity"]) == "Present"}, key=lambda t: t[1])
    expand = st.multiselect("Show other proteins at these locations (top 6 each, from all assertions)",
                            [t for t, _ in pres_terms], format_func=dict(pres_terms).get, key=f"expand_{acc}")

    net = Network(height="680px", width="100%", directed=True, bgcolor=SURF, cdn_resources="in_line")
    net.add_node(acc, label=symbol, shape="box", color={"background": INK, "border": INK},
                 font={"color": SURF, "size": 22}, title=f"{symbol} ({acc}) · {opts[acc].get('name', '')}")
    terms = {}

    def term_node(t, label, level):
        if t in terms:
            terms[t] = min(terms[t], level)
            return
        terms[t] = level
        direct = level == 0
        net.add_node(t, label=label, shape="dot", size=16 if direct else 9,
                     color={"background": EMPTY if direct else "#e4e3df", "border": INK2 if direct else "#c3c2b7"},
                     font={"size": 15 if direct else 12, "color": INK if direct else INK2},
                     title=f"{label} ({local(t).replace('_', ':')})")
    few = len(lit) <= 14
    for x in lit:
        t, v = x["term"], local(x["verdict"])
        term_node(t, x["label"], 0)
        absent = local(x["polarity"]) == "Absent"
        evg = x.get("evidence")
        net.add_edge(acc, t, color=ctx.COLOR.get(v, "#999999"), width=1.5 + min(int(x["nPapers"]), 30) * 0.3,
                     dashes=absent, smooth={"type": "curvedCCW", "roundness": 0.45 if absent else 0.18},
                     label=(v + (" (absent)" if absent else "")) if few else None,
                     font={"size": 11, "color": INK2, "strokeWidth": 3, "strokeColor": SURF},
                     title=f"papers: {symbol} {'NOT ' if absent else ''}in {x['label']}\nverdict {v} · {x['nPapers']} papers · "
                           f"{x['nGroups']} author groups · {x.get('yearFirst', '?')}–{x.get('yearLast', '?')}"
                           + (f"\nGOA evidence behind the verdict: {EV.LABEL.get(evg, evg)}" if evg else ""))
    if show_goa:
        curated = defaultdict(lambda: {"ev": set(), "not": False, "q": set(), "label": "", "by": set()})
        for g in goa:
            c = curated[g["term"]]
            c["label"], c["not"] = g["label"], c["not"] or g["negated"] == "true"
            c["ev"].add(g["evidence"])
            c["q"].add(g["qualifier"])
            if g.get("assignedBy"):
                c["by"].add(g["assignedBy"])
        for t, c in curated.items():
            term_node(t, c["label"], 0)
            groups = EV.groups_of(c["ev"])
            best = next(iter(groups), None)
            col = "#b3261e" if c["not"] else EV.EV_COLOR.get(best, MUTED)
            net.add_edge(acc, t, color=col, width=1.2 + (6 - EV.GROUPS.index(best)) * 0.45 if best in EV.GROUPS else 1.2,
                         dashes=[6, 4] if c["not"] else False, smooth={"type": "curvedCW", "roundness": 0.18},
                         label="NOT" if c["not"] else None,
                         font={"size": 11, "color": INK2, "strokeWidth": 3, "strokeColor": SURF},
                         title=f"GOA: {'NOT ' if c['not'] else ''}{', '.join(sorted(c['q']))} {c['label']}\n"
                               + "\n".join(f"{EV.LABEL.get(gr, gr)}: " + ", ".join(f"{cd} ({EV.code_title([cd]).split(': ', 1)[-1]})"
                                                                               for cd in cs) for gr, cs in groups.items())
                               + (f"\nby {', '.join(sorted(c['by']))}" if c["by"] else ""))
    hier, hq = [], ("", 0.0)
    frontier = list(terms)
    for level in range(1, steps + 1):
        rows, q, s_ = ctx.cached("go_parents", tuple(sorted(frontier)))
        hq = (q, hq[1] + s_)
        hier += rows
        new = []
        for r in rows:
            if r["parent"] not in terms:
                new.append(r["parent"])
            term_node(r["parent"], r["parentLabel"], level)
            net.add_edge(r["child"], r["parent"], color="#c3c2b7", width=1, dashes=r["relation"] == "part_of",
                         arrows={"to": {"enabled": True, "scaleFactor": 0.4}}, title=r["relation"])
        frontier = new
        if not frontier:
            break
    extra = []
    if show_papers:
        m_res = ctx.cached("protein_mentions", acc)
        a_res = ctx.cached("protein_authors", acc)
        extra += [m_res, a_res]
        by_term = defaultdict(dict)
        for r in m_res[0]:
            if local(r["polarity"]) == "Present":
                by_term[r["term"]][r["paper"]] = r
        chosen = {}
        for t, ps in by_term.items():
            for p, r in sorted(ps.items(), key=lambda kv: -int(kv[1].get("citations") or 0))[:per_term]:
                chosen.setdefault(p, {"r": r, "terms": set()})["terms"].add(t)
        groups = _paper_groups(list(chosen), a_res[0])
        names = defaultdict(list)
        for a in a_res[0]:
            if a["paper"] in chosen:
                names[a["paper"]].append(a["name"])
        for gi, ps in enumerate(sorted(groups, key=len, reverse=True), 1):
            hub = f"group:{gi}"
            if len(ps) > 1:
                shared = Counter(n for p in ps for n in set(names[p]))
                link = [n for n, k in shared.most_common(4) if k >= 2]
                net.add_node(hub, label=f"group {gi}", shape="diamond", size=10,
                             color={"background": "#e4e3df", "border": INK2}, font={"size": 11, "color": INK2},
                             title=f"Independent author group {gi}: {len(ps)} papers" + (f"\nlinked by {', '.join(link)}" if link else ""))
            for p in ps:
                r = chosen[p]["r"]
                net.add_node(p, label=f"PMID {local(p)}", shape="square", size=7,
                             color={"background": SURF, "border": MUTED}, font={"size": 10, "color": INK2},
                             title=f"{r['title']} ({r.get('year', '?')}), cited {r.get('citations', '?')}×\n"
                                   f"{', '.join(names[p][:3])}{' et al.' if len(names[p]) > 3 else ''}")
                for t in chosen[p]["terms"]:
                    net.add_edge(p, t, color="#d9d8d3", width=1, dashes=[2, 3], arrows={"to": {"enabled": False}},
                                 title="supports this location claim")
                if len(ps) > 1:
                    net.add_edge(p, hub, color="#c3c2b7", width=1, arrows={"to": {"enabled": False}}, title="same author group")
    if expand:
        df = ctx.assertions()[0]
        for t in expand:
            near = df[(df["term"] == t) & (df["polarity"] == "present") & (df["acc"] != acc)].nlargest(6, "nPapers")
            for _, r in near.iterrows():
                nid = "prot:" + r["acc"]
                if nid not in net.get_nodes():
                    net.add_node(nid, label=r["symbol"], shape="box", color={"background": EMPTY, "border": INK2},
                                 font={"size": 13, "color": INK}, title=f"{r['symbol']} ({r['acc']})")
                net.add_edge(nid, t, color=ctx.COLOR.get(r["verdict"], MUTED), width=1 + min(int(r["nPapers"]), 30) * 0.15,
                             title=f"{r['symbol']} in {r['label']}: {r['verdict']}, {r['nPapers']} papers, {r['nGroups']} groups")
    net.set_options(PHYSICS)
    components.html(net.generate_html(notebook=False), height=700)
    st.markdown(verdict_legend(ctx.COLOR), unsafe_allow_html=True)
    st.markdown(EV.legend_html(), unsafe_allow_html=True)
    st.caption("Coloured edge = literature assertion (dashed = absent). Grey edge = GOA annotation, shaded by its strongest "
               "evidence (red dashed = NOT). Thin grey arrows = GO hierarchy (dashed = part_of). ◇ = independent author "
               "group, ▫ = paper, light box = another protein at the same location.")
    ctx.sparql(*res, *extra, *([(hier, hq[0], hq[1])] if hq[0] else []))


# --- Timeline page -----------------------------------------------------------------------------------
def timeline_page(ctx):
    acc, opts, pres = ctx.picker("Protein", "timeprot")
    _title(ctx, acc, opts, "timeline")
    lit, goa, res = _protein_data(ctx, acc)
    yr_res = ctx.cached("protein_years", acc)
    st.caption("When papers reported each location (dots, size = papers that year, colour = verdict) and when GOA "
               "annotations for the same GO term were dated (diamonds, shaded by evidence). GOA's date is when the "
               "annotation was last made or reviewed, not necessarily when it was first curated, so a diamond after the "
               "dots does not prove the curators were late. Discovery papers are from 2015–2026; silver papers (abstracts GOA "
               "cites) can be older.")
    info = {local(x["a"]): x for x in lit}
    rows = []
    for r in yr_res[0]:
        x = info.get(local(r["a"]))
        if not x or local(x["polarity"]) != "Present":
            continue
        rows.append({"location": x["label"], "year": int(r["year"]), "papers": int(r["papers"]),
                     "verdict": local(x["verdict"]), "source": "papers"})
    goa_rows = []
    for g in goa:
        if g["negated"] == "true" or not g.get("date"):
            continue
        grp = EV.groups_of([g["evidence"]])
        best = next(iter(grp))
        y, m, d = (int(v) for v in g["date"][:10].split("-"))
        goa_rows.append({"location": g["label"], "date": y + (m - 1) / 12 + (d - 1) / 365, "evidence": EV.LABEL.get(best, best),
                         "code": g["evidence"], "by": g.get("assignedBy", ""), "when": g["date"][:10]})
    if not rows and not goa_rows:
        st.info("Nothing to show.")
        return
    lit_df, goa_df = pd.DataFrame(rows), pd.DataFrame(goa_rows)
    if not goa_df.empty:   # one diamond per (location, date, evidence group)
        goa_df = goa_df.groupby(["location", "when", "date", "evidence"], as_index=False).agg(
            codes=("code", lambda s: ", ".join(sorted(set(s)))), by=("by", lambda s: ", ".join(sorted(set(s) - {""}))))
    only_lit = st.toggle("Only locations the papers report", value=True, key=f"tl_only_{acc}")
    locs = list(dict.fromkeys(lit_df.sort_values("year")["location"])) if not lit_df.empty else []
    if not only_lit and not goa_df.empty:
        locs += [l for l in dict.fromkeys(goa_df.sort_values("date")["location"]) if l not in locs]
    if not goa_df.empty:
        goa_df = goa_df[goa_df["location"].isin(locs)]
    y0 = int(min([lit_df["year"].min() if not lit_df.empty else 2026] + ([goa_df["date"].min()] if not goa_df.empty else [])))
    x = alt.X("x:Q", title=None, scale=alt.Scale(domain=[y0 - 0.5, 2026.9]), axis=alt.Axis(format="d", tickMinStep=1))
    y = alt.Y("location:N", sort=locs, title=None, axis=alt.Axis(labelLimit=240))
    layers = []
    if not lit_df.empty:
        layers.append(alt.Chart(lit_df).transform_calculate(x="datum.year").mark_circle(opacity=0.85, stroke=SURF, strokeWidth=1).encode(
            x=x, y=y, size=alt.Size("papers:Q", scale=alt.Scale(range=[30, 600]), legend=alt.Legend(title="papers/year")),
            color=alt.Color("verdict:N", scale=alt.Scale(domain=[v for v in D.VERDICTS if v in set(lit_df["verdict"])],
                                                         range=[ctx.COLOR[v] for v in D.VERDICTS if v in set(lit_df["verdict"])]),
                            legend=alt.Legend(title="verdict")),
            tooltip=["location", "year", "papers", "verdict"]))
    if not goa_df.empty:
        layers.append(alt.Chart(goa_df).transform_calculate(x="datum.date").mark_point(
            shape="diamond", filled=True, size=110, stroke=SURF, strokeWidth=1).encode(
            x=x, y=y, color=alt.Color("evidence:N", scale=alt.Scale(domain=[EV.LABEL[g] for g in EV.GROUPS],
                                                                   range=[EV.EV_COLOR[g] for g in EV.GROUPS]),
                                      legend=alt.Legend(title="GOA evidence", symbolType="diamond", symbolSize=110)),
            tooltip=["location", alt.Tooltip("when:N", title="GOA date"), "evidence", "codes", "by"]))
    chart = alt.layer(*layers).resolve_scale(color="independent").properties(height=max(160, 26 * len(locs)))
    st.altair_chart(chart, width="stretch")
    # first paper vs GOA dates on the same term
    if not lit_df.empty:
        first = lit_df.groupby("location")["year"].min()
        tab = []
        for loc, fy in first.items():
            g = goa_df[goa_df["location"] == loc] if not goa_df.empty else pd.DataFrame()
            tab.append({"location": loc, "first paper (corpus)": int(fy),
                        "papers": int(lit_df[lit_df["location"] == loc]["papers"].sum()),
                        "earliest GOA date": g["when"].min() if len(g) else "",
                        "GOA evidence": ", ".join(sorted(set(g["evidence"]))) if len(g) else "none (same term)"})
        st.dataframe(pd.DataFrame(tab).sort_values("papers", ascending=False), hide_index=True, width="stretch")
    ctx.sparql(*res, yr_res, pres)
