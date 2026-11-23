"""Protein graph pages of demo v2: Conditions, Network, Timeline (+ the shared abstract popover).

Each page takes a small context object from app/v2.py (cached query runner, colours, protein picker, ...) so this
module does not import the Streamlit script itself. Locations are the GO terms as claimed; the optional grouping uses
the GO Consortium's goslim_agr. All text from the data is escaped before it goes into HTML.
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


# --- full abstract ------------------------------------------------------------------------------------
def abstract_body(ctx, pmid, sentences=()):
    """The full text the LLM read (abstracts graph) with the claim's sentence(s) highlighted, plus links."""
    pmid = str(pmid)
    rows = ctx.cached("abstract", pmid)[0]
    links = [f"[PubMed]({PUBMED}{pmid}/)", f"[Europe PMC](https://europepmc.org/article/MED/{pmid})"]
    if rows and rows[0].get("doi"):
        links.append(f"[DOI](https://doi.org/{rows[0]['doi']})")
    if not rows:
        st.write("No text stored for this paper. " + " · ".join(links))
        return
    r = rows[0]
    text = esc(clean(r["abstract"]))
    for sent in sorted({clean(x) for x in sentences if x}, key=len, reverse=True):
        text = text.replace(esc(sent), f"<mark>{esc(sent)}</mark>")
    st.markdown(f"**{esc(r['title'])}** · {esc(r.get('year', '?'))} · *{esc(r.get('journal', ''))}* · PMID {pmid}")
    st.markdown(f"<div style='max-width:760px;font-size:0.92em;line-height:1.5'>{text}</div>", unsafe_allow_html=True)
    st.caption("The text the model read (PubTator title + abstract); the claim's sentence is highlighted. "
               + " · ".join(links))


def abstract_popover(ctx, pmid, sentences=(), key=""):
    """'Abstract' button that opens abstract_body."""
    with st.popover("Abstract", type="tertiary", icon=":material/article:", key=f"abs_{key}_{pmid}"):
        abstract_body(ctx, pmid, sentences)


# --- Conditions page ---------------------------------------------------------------------------------
NONE = "no condition stated"


def conditions_page(ctx, slim_toggle):
    acc, opts, pres = ctx.picker("Protein", "condprot")
    _title(ctx, acc, opts, "locations by condition")
    st.caption("The protein in the middle; each edge points to a location the papers place it at, labelled with the "
               "condition the sentence states (treatment, stress, mutation, disease …, as the model wrote it). A plain "
               "edge = no condition stated. Edge width = papers, colour = verdict of that location; red dashed = the "
               "papers say NOT there under that condition. Hover an edge for details; pick a row below for the "
               "sentences and abstracts.")
    group = slim_toggle()
    lit, goa, res = _protein_data(ctx, acc)
    m_res = ctx.cached("protein_mentions", acc)
    info = {x["term"]: x for x in lit if local(x["polarity"]) == "Present"}
    info_abs = {x["term"]: x for x in lit if local(x["polarity"]) == "Absent"}
    label = {x["term"]: x["label"] for x in lit}
    slim_res = ctx.cached("slims", tuple(sorted(label))) if group else ({}, "", 0.0)
    places = (lambda t: slim_res[0].get(t) or ["(no slim term)"]) if group else (lambda t: [label.get(t, local(t))])
    # one claim -> its conditions (or NONE); edges keyed by (place, polarity, condition)
    claims = {}
    for r in m_res[0]:
        c = claims.setdefault(r["m"], {**r, "conds": set()})
        if r.get("condition"):
            c["conds"].add(r["condition"])
    edges = defaultdict(lambda: {"papers": set(), "examples": [], "terms": set()})
    for c in claims.values():
        pol = local(c["polarity"])
        for place in places(c["term"]):
            for cond in (c["conds"] or {NONE}):
                e = edges[(place, pol, cond)]
                e["terms"].add(c["term"])
                if c["paper"] not in e["papers"]:
                    e["papers"].add(c["paper"])
                    e["examples"].append(c)
    if not edges:
        st.info("No claims for this protein.")
        return
    per_place = defaultdict(set)
    for (place, pol, cond), e in edges.items():
        per_place[place] |= e["papers"]
    c1, c2, c3 = st.columns(3)
    n_places = c1.slider("Locations (most papers first)", 1, max(2, len(per_place)), min(10, len(per_place)), key=f"cp_{acc}_{group}")
    k = c2.slider("Conditions per location (most papers first)", 0, 10, 3, key=f"ck_{acc}")
    show_none = c3.toggle("Edge for 'no condition stated'", value=True, key=f"cn_{acc}")
    keep = set(sorted(per_place, key=lambda pl: -len(per_place[pl]))[:n_places])

    def verdict_of(place, pol):
        src = info if pol == "Present" else info_abs
        vs = [src[t] for t in src if place in places(t)]
        return local(max(vs, key=lambda x: int(x["nPapers"]))["verdict"]) if vs else ""

    shown = []
    for place in keep:
        for pol in ("Present", "Absent"):
            items = [(cond, e) for (pl, po, cond), e in edges.items() if pl == place and po == pol]
            base = [(c, e) for c, e in items if c == NONE]
            conds = sorted([(c, e) for c, e in items if c != NONE], key=lambda ce: (-len(ce[1]["papers"]), ce[0]))
            sel = (base if show_none else []) + conds[:k]
            if pol == "Absent" and not sel and items:
                sel = sorted(items, key=lambda ce: -len(ce[1]["papers"]))[:1]
            shown += [(place, pol, c, e) for c, e in sel]
    net = Network(height="660px", width="100%", directed=True, bgcolor=SURF, cdn_resources="in_line")
    sym = opts[acc]["symbol"]
    net.add_node(acc, label=sym, shape="box", color={"background": INK, "border": INK}, font={"color": SURF, "size": 22},
                 title=f"{sym} ({acc})", mass=4)
    top = max([len(per_place[pl]) for pl in keep] or [1])
    for place in keep:
        v = verdict_of(place, "Present")
        n = len(per_place[place])
        net.add_node("place:" + place, label=place, shape="dot", size=10 + 22 * math.sqrt(n / top),
                     color={"background": ctx.COLOR.get(v, EMPTY), "border": INK2},
                     font={"size": 15, "color": INK, "strokeWidth": 4, "strokeColor": SURF},
                     title=f"{place}: {n} papers" + (f" · {v}" if v else ""))
    count = defaultdict(int)
    for place, pol, cond, e in shown:
        i = count[place]
        count[place] += 1
        n = len(e["papers"])
        absent = pol == "Absent"
        col = "#b3261e" if absent else ctx.COLOR.get(verdict_of(place, pol), MUTED)
        txt = ("NOT · " if absent else "") + ("" if cond == NONE else (cond[:34] + ("…" if len(cond) > 34 else "")))
        net.add_edge(acc, "place:" + place, width=1 + 1.5 * math.log1p(n), color=col, dashes=absent,
                     label=(f"{txt} ({n})" if txt else f"({n})") if n >= 2 or len(shown) <= 12 else None,
                     font={"size": 11, "color": INK2, "strokeWidth": 4, "strokeColor": SURF},
                     smooth={"type": "curvedCW" if i % 2 else "curvedCCW", "roundness": 0.08 + 0.12 * ((i + 1) // 2)},
                     title=f"{sym} {'NOT ' if absent else ''}at {place}" + (f" under: {cond}" if cond != NONE else ", no condition stated")
                           + f"\n{n} papers · GO terms: " + ", ".join(sorted(label.get(t, '') for t in e["terms"])))
    net.set_options(PHYSICS)
    components.html(net.generate_html(notebook=False), height=680)
    st.markdown(verdict_legend(ctx.COLOR, extra="<span><span style='display:inline-block;width:18px;border-top:2px dashed "
                                                 "#b3261e;margin-right:5px;vertical-align:middle'></span>NOT under "
                                                 "this condition</span>"), unsafe_allow_html=True)
    st.caption(f"{len(keep)} of {len(per_place)} locations, {len(shown)} edges (labels on edges with ≥ 2 papers when "
               "there are many; hover any edge). Conditions are the model's own words, "
               "not merged or cleaned yet; a sentence with several conditions adds an edge for each."
               + (" Grouped by GO slim: a term under several slim terms counts for each." if group else ""))
    tab = pd.DataFrame([{"location": place, "claim": "NOT" if pol == "Absent" else "present", "condition": cond,
                         "papers": len(e["papers"])} for (place, pol, cond), e in edges.items() if place in keep]
                       ).sort_values(["papers", "location"], ascending=[False, True]).reset_index(drop=True)
    left, right = st.columns([2, 3])
    with left:
        ev = st.dataframe(tab, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"cond_{acc}_{group}", height=420)
        st.caption(f"All {len(tab)} (location, condition) pairs of the locations shown. Select one for its sentences.")
    with right:
        r = tab.iloc[ev.selection.rows[0] if ev and ev.selection.rows else 0]
        e = edges[(r["location"], "Absent" if r["claim"] == "NOT" else "Present", r["condition"])]
        st.markdown(f"**{esc(sym)} {'NOT ' if r['claim'] == 'NOT' else ''}at {esc(r['location'])}** · "
                    f"{esc(r['condition'])} · {len(e['papers'])} papers", unsafe_allow_html=True)
        for i, x in enumerate(sorted(e["examples"], key=lambda x: -(int(x["year"]) if x.get("year") else 0))[:8]):
            pm = local(x["paper"])
            st.markdown(f"<div style='border-left:3px solid {LINE};padding:2px 0 2px 10px;margin:6px 0 0;font-size:0.92em'>"
                        f"{esc(clean(x['sentence']))}<br><small><a href='{PUBMED}{pm}/' target='_blank'>PMID {pm}</a> · "
                        f"{esc(str(x.get('year') or '?'))} · {esc(label.get(x['term'], ''))}"
                        + (f" · condition: {esc('; '.join(sorted(x['conds'])))}" if x["conds"] else "")
                        + "</small></div>", unsafe_allow_html=True)
            abstract_popover(ctx, pm, [x["sentence"]], key=f"cond{i}")
    ctx.sparql(m_res, *res, *([slim_res] if group else []), pres)


# --- Network page ------------------------------------------------------------------------------------
def _paper_groups(papers, authors):
    """Union-find over papers: same group when they share an ORCID or >= 2 author name keys."""
    parent = {p: p for p in papers}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    ids = defaultdict(set)
    for a in authors:
        if a["paper"] in parent:
            ids[a["paper"]].add("key:" + a["key"])   # the person (OpenAlex author, reasoner-merged by ORCID)
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
            c["ev"].add((g["evidence"], g.get("evGroup", "")))
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
                               + "\n".join(f"{EV.LABEL.get(gr, gr)}: " + ", ".join(cs) for gr, cs in groups.items())
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
        grp = EV.groups_of([(g["evidence"], g.get("evGroup", ""))])
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
