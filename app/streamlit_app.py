"""locx demo (SPEC M11): live SPARQL against Fuseki. Every panel shows the exact query it ran.

  make demo        # 127.0.0.1:8501 (Buse: SSH tunnel, laptop port 8502)
"""
import html
import re
from collections import defaultdict

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

import data as D

st.set_page_config(page_title="locx — protein localization claims", layout="wide")

# verdict colours: dataviz reference palette, categorical slots in fixed order (always shown with the name)
COLOR = dict(zip(D.VERDICTS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]))
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"


@st.cache_data(ttl=3600, show_spinner=False)
def cached(fn_name, *args):
    rows, q, secs = getattr(D, fn_name)(*args)
    return rows, q, secs


def show_query(q, secs, rows):
    with st.expander(f"SPARQL ({len(rows)} rows, {secs:.2f} s)"):
        st.code(q, language="sparql")


def vname(iri):
    return D.local(iri) if iri else ""


def style_verdict(df, col="verdict"):
    def f(v):
        c = COLOR.get(v)
        return f"background-color: {c}33" if c else ""
    return df.style.map(f, subset=[col])


def mark(sentence, terms):
    """Escape the sentence (external text) and highlight the protein / location mentions."""
    out = html.escape(sentence)
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        out = re.sub(f"(?i)({re.escape(html.escape(t))})", r"<mark>\1</mark>", out)
    return out


def open_assertion(key):
    st.session_state["assertion"] = key
    st.switch_page(PAGES["detail"])


def assertion_picker(df, label, key_col="key"):
    opts = df[key_col].tolist()
    if not opts:
        return
    labels = dict(zip(opts, (f"{r['symbol']} — {r['location']} ({r['polarity']})" for _, r in df.iterrows())))
    c1, c2 = st.columns([4, 1])
    choice = c1.selectbox(label, opts, format_func=labels.get, key=f"pick_{label}")
    c2.write("")
    if c2.button("Open assertion", key=f"btn_{label}"):
        open_assertion(choice)


# --- pages -----------------------------------------------------------------------------------------
def overview():
    st.title("locx — protein localization claims from PubMed abstracts")
    st.caption("Claims extracted by a local LLM, grounded to UniProt and GO, stored with provenance in Apache Jena "
               "Fuseki, and compared with GOA. All numbers below are live SPARQL results.")
    run, q1, s1 = cached("run_info")
    cnt, q2, s2 = cached("run_counts")
    ver, q3, s3 = cached("verdict_distribution")
    r, c = run[0], cnt[0]
    vd = {vname(x["verdict"]): int(x["assertions"]) for x in ver}
    m = st.columns(4)
    m[0].metric("Claims (mentions)", f"{int(c['mentions']):,}")
    m[1].metric("Valid claims", f"{int(c['valid']):,}", f"{int(c['valid']) / int(c['mentions']):.1%} valid", delta_color="off")
    m[2].metric("Assertions", f"{sum(vd.values()):,}")
    m[3].metric("Papers with claims", f"{int(c['papers']):,}")
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Verdicts against GOA")
        df = pd.DataFrame([{"verdict": v, "assertions": vd.get(v, 0)} for v in D.VERDICTS if vd.get(v)])
        chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=36).encode(
            x=alt.X("verdict:N", sort=D.VERDICTS, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("assertions:Q", title="assertions"),
            color=alt.Color("verdict:N", scale=alt.Scale(domain=list(COLOR), range=list(COLOR.values())), legend=None),
            tooltip=["verdict", alt.Tooltip("assertions:Q", format=",")])
        text = chart.mark_text(dy=-8, color="#52514e").encode(text=alt.Text("assertions:Q", format=","), color=alt.value("#52514e"))
        st.altair_chart(chart + text, width="stretch")
        show_query(q3, s3, ver)
    with right:
        st.subheader("Extraction run (PROV-O)")
        st.markdown(f"- **Run:** `{D.local(r['run'])}`\n- **Model:** {r['model']}\n- **Served by:** {r['servedBy']}\n"
                    f"- **Prompt:** {r['promptVersion']} (sha256 `{r['promptSha'][:16]}…`), schema v{r['schema']}, "
                    f"temperature {r['temperature']}\n- **Started / ended:** {r['started']} / {r.get('ended', '–')}")
        show_query(q1, s1, run)
        show_query(q2, s2, cnt)
    st.subheader("Knowledge graph")
    gs, q4, s4 = cached("graph_sizes")
    st.dataframe(pd.DataFrame([{"named graph": g["graph"], "triples": int(g["triples"])} for g in gs]),
                 hide_index=True, width="stretch", column_config={"triples": st.column_config.NumberColumn(format="%d")})
    show_query(q4, s4, gs)


def protein_explorer():
    st.title("Protein explorer")
    plist, qp, sp = cached("proteins")
    opts = {D.local(p["protein"]): p for p in plist}
    default = st.session_state.get("protein", next((a for a, p in opts.items() if p["symbol"] == "TP53"), next(iter(opts))))
    acc = st.selectbox("Protein (type a gene symbol)", list(opts), index=list(opts).index(default) if default in opts else 0,
                       format_func=lambda a: f"{opts[a]['symbol']} — {opts[a].get('name', '')} ({a}; {opts[a]['assertions']} assertions)")
    st.session_state["protein"] = acc
    lit, ql, sl = cached("protein_literature", acc)
    goa, qg, sg = cached("protein_goa", acc)
    curated = defaultdict(lambda: {"qualifiers": set(), "evidence": set(), "not": False, "pmids": set(), "label": ""})
    for g in goa:
        cdat = curated[g["term"]]
        cdat["label"] = g["label"]
        cdat["qualifiers"].add(g["qualifier"])
        cdat["evidence"].add(g["evidence"])
        cdat["not"] |= g["negated"] == "true"
        if g.get("source"):
            cdat["pmids"].add(D.local(g["source"]))
    rows, seen = [], set()
    for x in lit:
        t = x["term"]
        seen.add(t)
        cd = curated.get(t)
        rows.append({"key": D.local(x["a"]), "location": x["label"], "polarity": vname(x["polarity"]).lower(),
                     "verdict": vname(x["verdict"]), "papers": int(x["nPapers"]), "author groups": int(x["nGroups"]),
                     "finding / background": f"{x['nFinding']} / {x['nBackground']}",
                     "years": f"{x.get('yearFirst', '?')}–{x.get('yearLast', '?')}",
                     "context": "yes" if x.get("context") == "true" else "",
                     "GOA on this term": (("NOT " if cd["not"] else "") + ", ".join(sorted(cd["evidence"]))) if cd else "–",
                     "symbol": opts[acc]["symbol"]})
    st.subheader("Literature side (assertions) with the curated side on the same GO term")
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(style_verdict(df.drop(columns=["key", "symbol"])), hide_index=True, width="stretch")
        assertion_picker(df, "Open an assertion")
    else:
        st.info("No assertions for this protein.")
    show_query(ql, sl, lit)
    st.subheader("Curated side (GOA cellular component)")
    cur = [{"location": v["label"], "qualifier": ", ".join(sorted(v["qualifiers"])), "NOT": "NOT" if v["not"] else "",
            "evidence": ", ".join(sorted(v["evidence"])), "source PMIDs": ", ".join(sorted(v["pmids"], key=int)[:8])
            + (" …" if len(v["pmids"]) > 8 else ""), "in literature": "yes" if t in seen else ""}
           for t, v in sorted(curated.items(), key=lambda kv: kv[1]["label"])]
    st.dataframe(pd.DataFrame(cur), hide_index=True, width="stretch")
    show_query(qg, sg, goa)
    show_query(qp, sp, plist)


def assertion_detail():
    st.title("Assertion detail")
    key = st.session_state.get("assertion")
    if not key:
        st.info("Open an assertion from the Protein explorer, Curation gaps or Conflicts page.")
        return
    info, qa, sa = cached("assertion", key)
    if not info:
        st.warning(f"Assertion {key} not found.")
        return
    a = info[0]
    verdict = vname(a["verdict"])
    st.markdown(f"### {a['symbol']} — {a['label']} ({vname(a['polarity']).lower()})")
    st.markdown(f"<span style='background:{COLOR.get(verdict, '#ccc')}33;padding:2px 8px;border-radius:4px'>"
                f"verdict: <b>{verdict}</b></span> &nbsp; {a['nPapers']} papers · {a['nGroups']} independent author groups · "
                f"finding {a['nFinding']} / background {a['nBackground']} / hedged {a['nHedged']} · "
                f"{a.get('yearFirst', '?')}–{a.get('yearLast', '?')}"
                + (" · context-dependent" if a.get("context") == "true" else "")
                + (" · a supporting paper is also cited by GOA" if a.get("sameAsGOA") == "true" else ""),
                unsafe_allow_html=True)
    show_query(qa, sa, info)
    goa, qg, sg = cached("assertion_goa", key)
    st.subheader("Curated side (GOA rows behind the verdict)")
    if goa:
        st.dataframe(pd.DataFrame([{"GO term": g["label"], "qualifier": ("NOT " if g["negated"] == "true" else "") + g["qualifier"],
                                    "evidence": g["evidence"], "source": D.local(g["source"]) if g.get("source") else "",
                                    "assigned by": g.get("assignedBy", "")} for g in goa]).drop_duplicates(),
                     hide_index=True, width="stretch")
    else:
        st.write("GOA has nothing in this term's lineage for this protein." if verdict == "Novel" else "No GOA rows linked.")
    show_query(qg, sg, goa)

    def mentions_panel(k, title):
        ms, qm, sm = cached("assertion_mentions", k)
        au, qau, sau = cached("assertion_authors", k)
        authors = defaultdict(list)
        for x in au:
            p = x["person"]
            name = html.escape(x["name"])
            authors[x["paper"]].append(f"<a href='{p}' target='_blank'>{name}</a>" if p.startswith("https://orcid.org/") else name)
        by_m = {}
        for x in ms:
            m = by_m.setdefault(x["m"], {**x, "conditions": set(), "flags": set(), "pm": set(), "lm": set()})
            m["conditions"].add(x.get("condition"))
            m["flags"].add(x.get("flag"))
            m["pm"].add(x.get("proteinMention"))
            m["lm"].add(x.get("locationMention"))
        st.subheader(f"{title} ({len(by_m)} mentions)")
        for m in sorted(by_m.values(), key=lambda m: (m.get("year", "0"), m["paper"]), reverse=True):
            pmid = D.local(m["paper"])
            st.markdown(f"<div style='border-left:3px solid #c3c2b7;padding-left:10px;margin:10px 0'>"
                        f"<div>{mark(m['sentence'], m['pm'] | m['lm'])} <small>[{m['sentenceId']}]</small></div>"
                        f"<small><a href='{PUBMED}{pmid}/' target='_blank'>PMID {pmid}</a> · <i>{html.escape(m['title'])}</i> "
                        f"{html.escape(m.get('journal', ''))} ({m.get('year', '?')}) · cited {m.get('citations', '?')}×<br>"
                        f"{', '.join(authors.get(m['paper'], [])[:8])}{' et al.' if len(authors.get(m['paper'], [])) > 8 else ''}<br>"
                        f"{vname(m['sourceType']).lower()}, {vname(m['certainty']).lower()} · method: {m['method']} · "
                        f"organism: {m['organism']}{' · cell type: ' + html.escape(m['cellType']) if m.get('cellType') else ''}"
                        f"{' · condition: ' + html.escape('; '.join(sorted(c for c in m['conditions'] if c))) if any(m['conditions']) else ''}"
                        f" · author group: <code>{html.escape(D.local(m.get('group', '') or '–'))}</code>"
                        f"{' · warnings: ' + ', '.join(sorted(f for f in m['flags'] if f)) if any(m['flags']) else ''}"
                        f"</small></div>", unsafe_allow_html=True)
        show_query(qm, sm, ms)
        show_query(qau, sau, au)
    opp = D.opposite(key)
    opp_info = cached("assertion", opp)[0]
    if opp_info:
        c1, c2 = st.columns(2)
        with c1:
            mentions_panel(key, "Supporting mentions")
        with c2:
            mentions_panel(opp, f"Opposing mentions ({vname(opp_info[0]['polarity']).lower()})")
    else:
        mentions_panel(key, "Supporting mentions")


def curation_gaps():
    st.title("Curation gaps")
    st.caption("Novel and refinement assertions: claims that GOA does not have yet, ranked by the number of independent "
               "author groups, then papers reporting them as a finding. Caveat: top entries can be gene-normalization "
               "errors (e.g. TAZ → TAFAZZIN); open the assertion to check the sentences.")
    n = st.slider("Minimum independent author groups", 1, 10, 2)
    rows, q, s = cached("curation_gaps", n)
    df = pd.DataFrame([{"key": D.local(x["a"]), "symbol": x["symbol"], "location": x["label"],
                        "polarity": vname(x["polarity"]).lower(), "verdict": vname(x["verdict"]),
                        "author groups": int(x["nGroups"]), "finding papers": int(x["nFinding"]), "papers": int(x["nPapers"]),
                        "years": f"{x.get('yearFirst', '?')}–{x.get('yearLast', '?')}",
                        "context": "yes" if x.get("context") == "true" else ""} for x in rows])
    st.write(f"{len(df)} assertions with ≥ {n} author groups.")
    if len(df):
        st.dataframe(style_verdict(df.drop(columns=["key"])), hide_index=True, width="stretch")
        assertion_picker(df, "Open a curation gap")
    show_query(q, s, rows)


def conflicts():
    st.title("Conflicts")
    st.caption("Assertions that contradict GOA (present vs a GOA NOT row, or absent vs a GOA annotation). Most are "
               "context-dependent (translocation, disease, treatment), which the pipeline cannot resolve yet.")
    rows, q, s = cached("conflicts")
    only_ctx = st.checkbox("Only context-free conflicts (no condition stated)", value=False)
    df = pd.DataFrame([{"key": D.local(x["a"]), "symbol": x["symbol"], "location": x["label"],
                        "polarity": vname(x["polarity"]).lower(), "author groups": int(x["nGroups"]),
                        "papers": int(x["nPapers"]), "context": "yes" if x.get("context") == "true" else "",
                        "GOA side": x["goa"]} for x in rows])
    if only_ctx and len(df):
        df = df[df["context"] == ""]
    st.write(f"{len(df)} conflicting assertions.")
    if len(df):
        st.dataframe(df.drop(columns=["key"]), hide_index=True, width="stretch")
        assertion_picker(df, "Open a conflict")
    show_query(q, s, rows)


def errors():
    st.title("Errors (invalid claims by validator flag)")
    st.caption("Invalid claims are kept as mentions without an assertion, so the validator can be inspected.")
    flags, qf, sf = cached("error_flags")
    st.dataframe(pd.DataFrame([{"flag": f["flag"], "invalid mentions": int(f["mentions"])} for f in flags]),
                 hide_index=True, width="stretch")
    show_query(qf, sf, flags)
    choice = st.selectbox("Show mentions with flag", [f["flag"] for f in flags if f["flag"] in D.FLAGS])
    if choice:
        rows, q, s = cached("errors", choice)
        st.dataframe(pd.DataFrame([{"PMID": f"{PUBMED}{D.local(x['paper'])}/", "protein": x["symbol"],
                                    "location": x.get("label") or f"OTHER: {x.get('otherText', '')}",
                                    "polarity": vname(x["polarity"]).lower(), "sentence": f"[{x['sentenceId']}] {x['sentence']}"}
                                   for x in rows]),
                     hide_index=True, width="stretch",
                     column_config={"PMID": st.column_config.LinkColumn(display_text=r"https://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/")})
        show_query(q, s, rows)


def graph_neighborhood():
    st.title("Graph neighborhood")
    st.caption("The selected protein with its literature assertions (coloured by verdict), its GOA annotations (grey) and "
               "the GO is_a / part_of hierarchy around those terms. Drag nodes, scroll to zoom, hover for details.")
    plist, qp, sp = cached("proteins")
    opts = {D.local(p["protein"]): p for p in plist}
    default = st.session_state.get("protein", next((a for a, p in opts.items() if p["symbol"] == "TP53"), next(iter(opts))))
    acc = st.selectbox("Protein (type a gene symbol)", list(opts), index=list(opts).index(default) if default in opts else 0,
                       format_func=lambda a: f"{opts[a]['symbol']} — {opts[a].get('name', '')} ({a})", key="graph_protein")
    st.session_state["protein"] = acc
    c1, c2, c3, c4 = st.columns(4)
    steps = c1.slider("GO hierarchy: steps up", 0, 3, 1)
    show_goa = c2.checkbox("Show GOA annotations", value=True)
    show_papers = c3.checkbox("Show supporting papers", value=False)
    per_term = c4.slider("Papers per term (most cited)", 1, 10, 3, disabled=not show_papers)

    symbol = opts[acc]["symbol"]
    lit, ql, sl = cached("protein_literature", acc)
    goa, qg, sg = cached("protein_goa", acc) if show_goa else ([], "", 0.0)
    net = Network(height="660px", width="100%", directed=True, bgcolor="#fcfcfb", cdn_resources="in_line")
    net.add_node(acc, label=symbol, shape="box", color={"background": "#0b0b0b", "border": "#0b0b0b"},
                 font={"color": "#fcfcfb", "size": 22}, title=f"{symbol} ({acc}) — {opts[acc].get('name', '')}")
    terms = {}

    def term_node(t, label, level):
        if t in terms:
            terms[t] = min(terms[t], level)
            return
        terms[t] = level
        direct = level == 0
        net.add_node(t, label=label, shape="dot", size=16 if direct else 9,
                     color={"background": "#f0efec" if direct else "#e4e3df", "border": "#52514e" if direct else "#c3c2b7"},
                     font={"size": 15 if direct else 12, "color": "#0b0b0b" if direct else "#52514e"},
                     title=f"{label} ({D.local(t).replace('_', ':')})")
    few = len(lit) <= 12
    for x in lit:
        t, v = x["term"], vname(x["verdict"])
        term_node(t, x["label"], 0)
        absent = vname(x["polarity"]) == "Absent"
        net.add_edge(acc, t, color=COLOR.get(v, "#999999"), width=1.5 + min(int(x["nPapers"]), 12) * 0.5,
                     dashes=absent, smooth={"type": "curvedCCW", "roundness": 0.45 if absent else 0.18}, label=(v + (" (absent)" if absent else "")) if few else None,
                     font={"size": 11, "color": "#52514e", "strokeWidth": 3, "strokeColor": "#fcfcfb"},
                     title=f"literature: {symbol} {'NOT ' if absent else ''}in {x['label']}\nverdict {v} · {x['nPapers']} papers · "
                           f"{x['nGroups']} author groups · {x.get('yearFirst', '?')}–{x.get('yearLast', '?')}")
    curated = defaultdict(lambda: {"ev": set(), "not": False, "q": set(), "label": ""})
    for g in goa:
        c = curated[g["term"]]
        c["label"], c["not"] = g["label"], c["not"] or g["negated"] == "true"
        c["ev"].add(g["evidence"])
        c["q"].add(g["qualifier"])
    for t, c in curated.items():
        term_node(t, c["label"], 0)
        net.add_edge(acc, t, color="#52514e" if c["not"] else "#a8a7a1", width=1.5, dashes=[6, 4] if c["not"] else False,
                     smooth={"type": "curvedCW", "roundness": 0.18}, label="NOT" if c["not"] else None,
                     font={"size": 11, "color": "#52514e", "strokeWidth": 3, "strokeColor": "#fcfcfb"},
                     title=f"GOA: {'NOT ' if c['not'] else ''}{', '.join(sorted(c['q']))} {c['label']}\nevidence {', '.join(sorted(c['ev']))}")
    hier_rows, hq, hs = [], "", 0.0
    frontier = [t for t, lvl in terms.items()]
    for level in range(1, steps + 1):
        rows, hq, s_ = cached("go_parents", tuple(sorted(frontier)))
        hs += s_
        hier_rows += rows
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
    papers = []
    if show_papers:
        rows, qpp, spp = cached("neighborhood_papers", acc)
        by_term = defaultdict(list)
        for r in rows:
            by_term[r["term"]].append(r)
        for t, rs in by_term.items():
            for r in sorted(rs, key=lambda r: -int(r.get("citations", 0)))[:per_term]:
                pid = r["paper"]
                if pid not in net.get_nodes():
                    net.add_node(pid, label=f"PMID {D.local(pid)}", shape="square", size=7,
                                 color={"background": "#fcfcfb", "border": "#8b8a85"}, font={"size": 10, "color": "#52514e"},
                                 title=f"{r['title']} ({r.get('year', '?')}), cited {r.get('citations', '?')}×")
                net.add_edge(pid, t, color="#d9d8d3", width=1, dashes=[2, 3], arrows={"to": {"enabled": False}},
                             title="supports this location claim")
                papers.append(r)
    net.set_options("""{
      "physics": {"barnesHut": {"gravitationalConstant": -9000, "springLength": 150, "springConstant": 0.03,
                                "avoidOverlap": 0.3}, "stabilization": {"iterations": 250}},
      "interaction": {"hover": true, "tooltipDelay": 120},
      "edges": {"arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}, "smooth": {"type": "continuous"}}
    }""")
    components.html(net.generate_html(notebook=False), height=680)
    legend = " &nbsp; ".join(f"<span style='display:inline-block;width:22px;height:4px;background:{COLOR[v]};"
                             f"vertical-align:middle'></span> {v}" for v in D.VERDICTS[:5])
    st.markdown(f"<small><b>Literature edges</b> (width = papers; dashed = absent): {legend}<br>"
                "<span style='display:inline-block;width:22px;height:4px;background:#a8a7a1;vertical-align:middle'></span> "
                "GOA annotation &nbsp; <b>NOT</b> = dashed dark grey GOA edge &nbsp; "
                "<span style='display:inline-block;width:22px;height:2px;background:#c3c2b7;vertical-align:middle'></span> "
                "GO hierarchy (solid is_a, dashed part_of) &nbsp; ▫ paper</small>", unsafe_allow_html=True)
    st.write(f"{len(terms)} GO terms ({sum(1 for v in terms.values() if v == 0)} annotated or claimed), "
             f"{len(lit)} literature assertions, {len(curated)} GOA terms, {len({p['paper'] for p in papers})} papers shown.")
    if lit:
        df = pd.DataFrame([{"key": D.local(x["a"]), "symbol": symbol, "location": x["label"],
                            "polarity": vname(x["polarity"]).lower()} for x in lit])
        assertion_picker(df, "Open an assertion from this graph")
    show_query(ql, sl, lit)
    if show_goa:
        show_query(qg, sg, goa)
    if hq:
        show_query(hq, hs, hier_rows)
    if show_papers:
        show_query(qpp, spp, papers)


PAGES = {
    "overview": st.Page(overview, title="Overview", default=True),
    "protein": st.Page(protein_explorer, title="Protein explorer"),
    "detail": st.Page(assertion_detail, title="Assertion detail"),
    "graph": st.Page(graph_neighborhood, title="Graph neighborhood"),
    "gaps": st.Page(curation_gaps, title="Curation gaps"),
    "conflicts": st.Page(conflicts, title="Conflicts"),
    "errors": st.Page(errors, title="Errors"),
}
if "_test_page" in st.session_state:   # used by app/check_demo.py (AppTest cannot switch to function pages)
    globals()[st.session_state["_test_page"]]()
else:
    st.navigation(list(PAGES.values())).run()
