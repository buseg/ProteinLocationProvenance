"""locx demo v2: where are human proteins in the cell, and how do we know?

Pages around one question: Home (pipeline funnel + highlights); per protein: Profile (literature and the curated
side in one table, evidence inline), Conditions, Network, Timeline (app/graphs.py) and Provenance
(author groups → papers → claims → assertion → GOA, with the extraction run); Explore (filter every assertion);
Quality. GOA evidence codes are grouped by strength everywhere (locx/evidence.py, app/evidence_ui.py).
Live SPARQL against Fuseki; every query is in queries/ and shown with the sidebar toggle.

  make demo   # streamlit run app/v2.py on 127.0.0.1:8501
"""
import html
import re
from collections import defaultdict
from types import SimpleNamespace

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import data as D
import evidence_ui as EV
import graphs as G
import provenance_view as P

st.set_page_config(page_title="locx — protein localization claims", layout="wide", initial_sidebar_state="collapsed")

# verdict colours: dataviz reference palette, categorical slots in fixed order (always shown with the name)
COLOR = dict(zip(D.VERDICTS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]))
COLOR["GOA only"] = "#a8a7a1"
VERDICT_HELP = {
    "Consistent": "GOA has the same location, or a more specific one, for this protein",
    "Refinement": "the paper names a more specific location than GOA has",
    "Novel": "nothing in GOA along this location's lineage: a candidate curation gap",
    "Conflicting": "papers and GOA disagree (present vs NOT)",
    "Uninformative": "the location is too generic to compare",
    "Error": "no valid claim behind it (sanity check)",
    "GOA only": "curated in GOA, but no claim in our abstracts",
}
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"
UNIPROT = "https://www.uniprot.org/uniprotkb/"


# --- helpers -----------------------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def cached(fn_name, *args):
    return getattr(D, fn_name)(*args)


def sparql(*items):
    """Show the SPARQL behind a panel when the sidebar toggle is on. items: (rows, query, seconds) tuples."""
    if not st.session_state.get("show_sparql"):
        return
    for rows, q, secs in items:
        if q:
            with st.expander(f"SPARQL · {len(rows) if hasattr(rows, '__len__') else ''} rows · {secs:.2f} s"):
                st.code(q, language="sparql")


def vname(iri):
    return D.local(iri) if iri else ""


def chip(verdict, text=None):
    c = COLOR.get(verdict, "#8b8a85")
    return (f"<span style='background:{c};color:#fff;padding:1px 8px;border-radius:10px;font-size:0.85em'>"
            f"{html.escape(text or verdict)}</span>")


def mark(sentence, terms):
    out = html.escape(G.clean(sentence))
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        out = re.sub(f"(?i)({re.escape(html.escape(t))})", r"<mark>\1</mark>", out)
    return out


@st.cache_data(ttl=3600, show_spinner="Loading assertions …")
def assertions_df():
    rows, q, s = D.assertions_all()
    df = pd.DataFrame(rows)
    df["key"] = df["a"].map(D.local)
    df["acc"] = df["protein"].map(D.local)
    df["verdict"] = df["verdict"].map(vname)
    df["polarity"] = df["polarity"].map(lambda x: vname(x).lower())
    for c in ("nPapers", "nGroups", "nFinding"):
        df[c] = df[c].astype(int)
    for c in ("yearFirst", "yearLast"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["context"] = df.get("context", pd.Series(dtype=str)).eq("true")
    df["evidence"] = df.get("evidence", pd.Series(dtype=str)).fillna("")      # strongest GOA evidence group
    df["samePaper"] = df.get("samePaper", pd.Series(dtype=str)).eq("true")    # GOA cites a supporting paper
    return df, q, s


def open_assertion(key, acc, page="protein"):
    st.session_state["assertion"] = key
    st.session_state["protein"] = acc
    st.switch_page(PAGES[page])


def protein_options():
    plist, q, s = cached("proteins")
    return {D.local(p["protein"]): p for p in plist}, (plist, q, s)


def protein_picker(label, key):
    opts, res = protein_options()
    default = st.session_state.get("protein") or next((a for a, p in opts.items() if p["symbol"] == "TP53"), next(iter(opts)))
    keys = list(opts)
    acc = st.selectbox(label, keys, index=keys.index(default) if default in opts else 0, key=f"{key}_{default}",
                       format_func=lambda a: f"{opts[a]['symbol']} · {opts[a].get('name', '')} ({opts[a]['assertions']} assertions)")
    if acc != st.session_state.get("protein"):
        st.session_state["protein"] = acc
        st.session_state.pop("assertion", None)
    return acc, opts, res


def sidebar():
    with st.sidebar:
        st.markdown("### locx")
        st.caption("Protein localization claims from PubMed abstracts, with provenance, compared with GOA.")
        st.toggle("Show SPARQL queries", key="show_sparql")
        run = cached("run_info")[0]
        if run:
            r = run[0]
            st.caption(f"**Data:** run `{D.local(r['run'])}` · {r['model'].split('/')[-1]} on vLLM · prompt "
                       f"{r['promptVersion']} · temperature {r['temperature']}")


# --- Home --------------------------------------------------------------------------------------------
def home():
    st.title("Where are human proteins in the cell, and how do we know?")
    df, qa, sa = assertions_df()
    corpus = cached("corpus_size")
    cnt = cached("run_counts")
    run = cached("run_info")[0]
    n_papers = next(int(r["papers"]) for r in corpus[0] if r["tier"] == "silver_or_discovery")
    c = cnt[0][0]
    model = run[0]["model"].split("/")[-1] if run else "a local LLM"
    st.markdown(f"A local LLM (**{model}**) read PubMed abstracts and pulled out every sentence that places a human "
                "protein somewhere in the cell. Each claim is tied to UniProt and Gene Ontology, stored with its paper, "
                "sentence and authors as RDF, counted across **independent author groups**, and compared with what "
                "curators recorded in GOA.")

    # funnel
    stages = [("Abstracts read", n_papers, "silver + discovery tiers in the papers graph"),
              ("Abstracts with a claim", int(c["papers"]), "abstracts with at least one localization claim"),
              ("Claims", int(c["mentions"]), "one per (sentence, protein, location)"),
              ("Valid", int(c["valid"]), "grounded to UniProt + GO and passed validation (Python + SHACL)"),
              ("Assertions", len(df), "unique protein + location + present/absent, merged over papers")]
    cols = st.columns(len(stages))
    for col, (label, value, helptext) in zip(cols, stages):
        col.metric(label, f"{value:,}", help=helptext, border=True)

    # verdict split
    vc = df["verdict"].value_counts()
    vdf = pd.DataFrame([{"verdict": v, "assertions": int(vc.get(v, 0)), "share": vc.get(v, 0) / len(df),
                         "meaning": VERDICT_HELP[v]} for v in D.VERDICTS if vc.get(v, 0)])
    st.markdown("**How the assertions compare with GOA**")
    vdf["order"] = range(len(vdf))
    vdf["end"] = vdf["share"].cumsum()
    vdf["mid"] = vdf["end"] - vdf["share"] / 2
    vdf["text"] = [f"{v} {s:.0%}" if s >= 0.07 else "" for v, s in zip(vdf["verdict"], vdf["share"])]
    base = alt.Chart(vdf)
    bar = base.mark_bar(height=38).encode(
        x=alt.X("share:Q", stack="zero", axis=None, scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("verdict:N", scale=alt.Scale(domain=list(vdf["verdict"]), range=[COLOR[v] for v in vdf["verdict"]]),
                        legend=None),
        order=alt.Order("order:Q"),
        tooltip=["verdict", alt.Tooltip("assertions:Q", format=","), alt.Tooltip("share:Q", format=".0%"), "meaning"])
    txt = base.mark_text(color="white", fontSize=13, fontWeight="bold").encode(x="mid:Q", text="text:N")
    st.altair_chart((bar + txt).properties(height=44), width="stretch")
    st.markdown("<div style='display:flex;flex-wrap:wrap;gap:6px 18px;font-size:0.85em;color:#52514e'>" + "".join(
        f"<span title='{html.escape(VERDICT_HELP[v])}'><span style='display:inline-block;width:10px;height:10px;"
        f"border-radius:2px;background:{COLOR[v]};margin-right:5px'></span><b>{v}</b> {vc.get(v, 0):,} · "
        f"{html.escape(VERDICT_HELP[v])}</span>" for v in vdf["verdict"]) + "</div>", unsafe_allow_html=True)

    # search
    opts, _ = protein_options()
    sel = st.selectbox("Look up a protein", list(opts), index=None, placeholder="Type a gene symbol, e.g. TP53, TFEB, LMNA",
                       format_func=lambda a: f"{opts[a]['symbol']} · {opts[a].get('name', '')}")
    if sel:
        st.session_state["protein"] = sel
        st.session_state.pop("assertion", None)
        st.switch_page(PAGES["protein"])

    # highlights
    st.subheader("Worth a look")
    pres = df[df["polarity"] == "present"]
    novel = pres[pres["verdict"] == "Novel"].sort_values(["nGroups", "nFinding", "nPapers"], ascending=False).head(6)
    refine = pres[pres["verdict"] == "Refinement"].sort_values(["nGroups", "nPapers"], ascending=False).head(6)
    conflicting = df[(df["verdict"] == "Conflicting") & ~df["context"]]
    conf = conflicting[conflicting["evidence"] == "experimental"].sort_values(["nGroups", "nPapers"], ascending=False).head(6)
    conf_weak = conflicting[~conflicting["evidence"].isin(["experimental", "high_throughput", ""])].sort_values(
        ["nGroups", "nPapers"], ascending=False).head(6)
    weak = ~pres["evidence"].isin(["experimental", "high_throughput", ""])
    upgrade = pres[pres["verdict"].isin(["Consistent", "Refinement"]) & weak].sort_values(
        ["nGroups", "nFinding"], ascending=False).head(6)
    both = df[df["polarity"] == "present"].merge(df[df["polarity"] == "absent"], on=["acc", "term"], suffixes=("", "_abs"))
    both["score"] = both[["nPapers", "nPapers_abs"]].min(axis=1)
    disputed = both.sort_values(["score", "nPapers"], ascending=False).head(6)

    def card(col, title, caption, rows, fmt, key):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(caption)
            for i, (_, r) in enumerate(rows.iterrows()):
                label = fmt(r)
                if st.button(label if len(label) <= 70 else label[:68] + "…", key=f"{key}{i}", type="tertiary", help=label):
                    open_assertion(r["key"], r["acc"])

    c1, c2 = st.columns(2)
    card(c1, "New to GOA, reported by independent groups", "Novel: no GOA annotation along the location's lineage.",
         novel, lambda r: f"{r['symbol']} in {r['label']} · {r['nGroups']} groups, {r['nPapers']} papers", "nov")
    card(c2, "Papers disagree with each other", "Some papers say present, others say absent.",
         disputed, lambda r: f"{r['symbol']} in {r['label']} · {r['nPapers']} say yes, {r['nPapers_abs']} say no", "dis")
    c3, c4 = st.columns(2)
    card(c3, "More specific than GOA", "Refinement: GOA has only a broader location.",
         refine, lambda r: f"{r['symbol']} in {r['label']} · {r['nGroups']} groups, {r['nPapers']} papers", "ref")
    card(c4, "Contradicts experimental GOA, no condition stated", "Conflicting with a GOA annotation that has lab "
         "evidence, and no supporting sentence names a condition (treatment, disease, stimulus) that could explain it.",
         conf, lambda r: f"{r['symbol']} {'NOT ' if r['polarity'] == 'absent' else ''}in {r['label']} · "
                         f"{r['nGroups']} groups, {r['nPapers']} papers", "con")
    c5, c6 = st.columns(2)
    n_up = int((df["verdict"].isin(["Consistent", "Refinement"]) & ~df["evidence"].isin(["experimental", "high_throughput", ""])
                & (df["polarity"] == "present")).sum())
    card(c5, "Papers back curated locations that lack lab evidence in GOA",
         f"Consistent or Refinement, but GOA's best evidence is only an author statement, a computational inference or "
         f"an automatic (electronic) annotation: {n_up:,} candidates to upgrade with experimental literature.",
         upgrade, lambda r: f"{r['symbol']} in {r['label']} · GOA {EV.LABEL.get(r['evidence'], '').lower()} · "
                            f"{r['nGroups']} groups", "upg")
    card(c6, "Contradicts GOA where GOA's evidence is weak", "Conflicting with a GOA annotation that has no lab "
         "evidence (author statement, computational or electronic), no condition stated: GOA may be the one to fix.",
         conf_weak, lambda r: f"{r['symbol']} {'NOT ' if r['polarity'] == 'absent' else ''}in {r['label']} · "
                              f"GOA {EV.LABEL.get(r['evidence'], '').lower()} · {r['nPapers']} paper{'s' * (r['nPapers'] != 1)}", "cwk")
    syn = D.report("synonym_stats")
    if syn and run and run[0]["promptVersion"] == "v3":
        with st.container(border=True):
            st.markdown("**Ambiguous protein names the model resolved from context** (synonym layer)")
            st.caption(f"{syn['claims_on_ambiguous_names']:,} claims on ambiguous names; the model chose another protein "
                       f"than the tagger's in {syn['share_alternative']:.0%}. From reports/synonym_stats.json.")
            st.markdown(" · ".join(f"`{k}` ({v})" for k, v in list(syn["top_switches"].items())[:10]))
    sparql((df, qa, sa), corpus, cnt)


# --- Protein -----------------------------------------------------------------------------------------
NO_SLIM = "(no slim term)"


def slim_toggle():
    """Shared toggle: show GO terms as stated (default) or grouped by the GO Consortium's goslim_agr."""
    return st.toggle("Group by GO slim (goslim_agr)", key="group_slim",
                     help="Locations are the GO terms as the papers state them. On: also show the GO slim terms above "
                          "each one (goslim_agr, the GO Consortium's 16-term subset for human and model organisms; "
                          "a term can belong to several).")


def slim_text(slim, term):
    return ", ".join(slim.get(term, [])) or NO_SLIM


def ev_text(codes):
    """'Experimental (IDA, IPI); Electronic (IEA)': evidence groups, strongest first, with their codes."""
    return "; ".join(f"{EV.LABEL.get(g, g)} ({', '.join(c)})" for g, c in EV.groups_of(codes).items())


def goa_summary(goa):
    by = defaultdict(lambda: {"ev": set(), "not": False, "label": "", "src": set()})
    for g in goa:
        e = by[g["term"]]
        e["label"] = g["label"]
        e["ev"].add(g["evidence"])
        e["not"] |= g["negated"] == "true"
        if g.get("source"):
            e["src"].add(g["source"])
    return by


def protein_page():
    acc, opts, pres = protein_picker("Protein", "prot")
    p = opts[acc]
    lit_res = cached("protein_literature", acc)
    goa_res = cached("protein_goa", acc)
    yr_res = cached("protein_years", acc)
    lit, goa = lit_res[0], goa_res[0]
    curated = goa_summary(goa)
    group = slim_toggle()
    slim_res = cached("slims", tuple(sorted({x["term"] for x in lit} | set(curated)))) if group else ({}, "", 0.0)
    slim = slim_res[0]
    years = defaultdict(dict)
    for r in yr_res[0]:
        years[D.local(r["a"])][int(r["year"])] = int(r["papers"])
    all_years = [y for ys in years.values() for y in ys] or [2020]
    y0, y1 = min(all_years), max(all_years)

    st.markdown(f"## {p['symbol']} <span style='font-weight:400;color:#8b8a85;font-size:0.6em'>{html.escape(p.get('name', ''))} · "
                f"<a href='{UNIPROT}{acc}' target='_blank'>{acc}</a></span>", unsafe_allow_html=True)
    vc = defaultdict(int)
    for x in lit:
        vc[vname(x["verdict"])] += 1
    lit_terms = {x["term"] for x in lit}
    goa_only = [t for t in curated if t not in lit_terms and not curated[t]["not"]]
    m = st.columns(6)
    m[0].metric("Locations in papers", len({x["term"] for x in lit if vname(x["polarity"]) == "Present"}), border=True)
    for col, v in zip(m[1:5], ["Consistent", "Refinement", "Novel", "Conflicting"]):
        col.metric(v, vc.get(v, 0), help=VERDICT_HELP[v], border=True)
    m[5].metric("GOA only", len(goa_only), help=VERDICT_HELP["GOA only"], border=True)

    rows = []
    for x in lit:
        k = D.local(x["a"])
        cd = curated.get(x["term"])
        rows.append({"key": k, "GO slim": slim_text(slim, x["term"]), "location": x["label"],
                     "claim": "present" if vname(x["polarity"]) == "Present" else "NOT (absent)",
                     "verdict": vname(x["verdict"]), "papers": int(x["nPapers"]), "groups": int(x["nGroups"]),
                     "timeline": [years[k].get(y, 0) for y in range(y0, y1 + 1)],
                     "GOA evidence": EV.LABEL.get(x.get("evidence"), ""),
                     "GOA (same term)": (("NOT " if cd["not"] else "") + ev_text(cd["ev"])) if cd else "",
                     "condition": "yes" if x.get("context") == "true" else ""})
    for t in goa_only:
        cd = curated[t]
        rows.append({"key": "", "GO slim": slim_text(slim, t), "location": cd["label"], "claim": "",
                     "verdict": "GOA only", "papers": 0, "groups": 0, "timeline": [0] * (y1 - y0 + 1),
                     "GOA evidence": EV.LABEL.get(next(iter(EV.groups_of(cd["ev"])), ""), ""),
                     "GOA (same term)": ev_text(cd["ev"]), "condition": ""})
    if not rows:
        st.info("No assertions or GOA annotations for this protein.")
        return
    df = pd.DataFrame(rows)
    if group:
        df["_none"] = df["GO slim"].eq(NO_SLIM)
        df = df.sort_values(["_none", "GO slim", "papers"], ascending=[True, True, False]).drop(columns="_none")
    else:
        df = df.drop(columns="GO slim")
        df["_goa"] = df["verdict"].eq("GOA only")
        df = df.sort_values(["_goa", "papers"], ascending=[True, False]).drop(columns="_goa")
    df = df.reset_index(drop=True)

    st.markdown("**Localization profile**: literature and curators side by side, one row per GO term as stated"
                + (", grouped by GO slim" if group else "") + ". Select a row to see the evidence.")
    styled = df.drop(columns=["key"]).style.map(
        lambda v: f"background-color: {COLOR.get(v, '#ffffff')}33" if v in COLOR else "", subset=["verdict"])
    ev = st.dataframe(styled, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key=f"profile_{acc}", height=min(38 + 35 * len(df), 560),
                      column_config={
                          "papers": st.column_config.ProgressColumn("papers", format="%d", min_value=0,
                                                                    max_value=max(int(df["papers"].max()), 1)),
                          "groups": st.column_config.NumberColumn("independent groups", format="%d"),
                          "timeline": st.column_config.BarChartColumn(f"papers per year {y0}–{y1}", y_min=0),
                          "GOA evidence": st.column_config.TextColumn("GOA evidence", help="strongest GO evidence among "
                                                                      "the GOA rows behind the verdict (experimental > "
                                                                      "high-throughput > author statement > curator > "
                                                                      "computational > electronic)"),
                          "GOA (same term)": st.column_config.TextColumn("GOA on the same term", help="evidence groups "
                                                                         "and codes of GOA rows on exactly this term"),
                          "condition": st.column_config.TextColumn("condition stated", help="some supporting sentence "
                                                                   "names a condition (treatment, disease, stimulus)")})
    with st.expander("What do the GOA evidence codes mean?"):
        st.markdown(EV.legend_html(), unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(EV.legend_rows()), hide_index=True, width="stretch")
    sel = ev.selection.rows if ev and ev.selection else []
    sel_key = df.iloc[sel[0]]["key"] if sel else None
    if sel_key != st.session_state.get(f"lastsel_{acc}"):      # a new row was selected: it wins
        st.session_state[f"lastsel_{acc}"] = sel_key
        key = sel_key or st.session_state.get("assertion")
    else:                                                       # otherwise keep what buttons set (e.g. opposite claim)
        key = st.session_state.get("assertion")
    if key and key in set(df["key"]):
        st.session_state["assertion"] = key
        st.divider()
        evidence_panel(key, acc)
    elif sel:
        st.info("This location is curated in GOA but no abstract in our corpus states it.")
    sparql(lit_res, goa_res, yr_res, *([slim_res] if group else []), pres)


def evidence_panel(key, acc):
    info = cached("assertion", key)
    if not info[0]:
        st.warning(f"Assertion {key} not found.")
        return
    a = info[0][0]
    verdict = vname(a["verdict"])
    pol = vname(a["polarity"]).lower()
    opp = D.opposite(key)
    opp_info = cached("assertion", opp)[0]
    st.markdown(f"### {html.escape(a['symbol'])} {'NOT ' if pol == 'absent' else ''}in {html.escape(a['label'])} &nbsp;"
                f"{chip(verdict)}" + (f" &nbsp;<span style='font-size:0.6em'>GOA evidence {EV.badge(a['evidence'])}</span>"
                                      if a.get("evidence") else ""), unsafe_allow_html=True)
    np_, ng_ = int(a["nPapers"]), int(a["nGroups"])
    st.caption(f"{VERDICT_HELP.get(verdict, '')}. {np_} paper{'s' * (np_ != 1)} from {ng_} independent author "
               f"group{'s' * (ng_ != 1)} · "
               f"finding {a['nFinding']}, background {a['nBackground']}, hedged {a['nHedged']} · "
               f"{a.get('yearFirst', '?')}–{a.get('yearLast', '?')}"
               + (" · **GOA curators cited one of these papers** (same paper, read independently)"
                  if a.get("sameAsGOA") == "true" else ""))
    b1, b2, _ = st.columns([1.2, 1.6, 3])
    if b1.button("Open provenance graph", type="primary", key=f"prov_{key}"):
        open_assertion(key, acc, "provenance")
    if opp_info and b2.button(f"See the opposite claim ({opp_info[0]['nPapers']} papers say "
                              f"{'absent' if pol == 'present' else 'present'})", key=f"opp_{key}"):
        st.session_state["assertion"] = opp
        st.rerun()
    left, right = st.columns([3, 2])
    ms_res = cached("assertion_mentions", key)
    au_res = cached("provenance_authors", key)
    mentions = P.merge_mentions(ms_res[0])
    groups = P.author_groups(mentions, au_res[0])
    by_paper = defaultdict(list)
    for m in mentions:
        by_paper[m["paper"]].append(m)
    with left:
        st.markdown(f"**What the papers say**: {len(mentions)} sentence{'s' * (len(mentions) != 1)}, grouped by "
                    "independent author group")
        limit = st.session_state.get(f"more_{key}", 8)
        shown = 0
        for gi, (g, papers, link, _) in enumerate(groups, 1):
            if shown >= limit:
                break
            linked = ", ".join(nm for nm, _ in link[:4])
            st.markdown(f"<div style='margin-top:10px;color:#52514e;font-size:0.9em'><b>Author group {gi}</b> · "
                        f"{len(papers)} paper{'s' if len(papers) > 1 else ''}"
                        f"{' · linked by ' + html.escape(linked) if linked else ''}</div>", unsafe_allow_html=True)
            for pp in papers:
                if shown >= limit:
                    break
                shown += 1
                for m in by_paper[pp]:
                    pmid = D.local(m["paper"])
                    meta = [vname(m.get("sourceType")).lower()]
                    if vname(m.get("certainty")) == "Hedged":
                        meta.append("hedged")
                    meta += [x for x in (m.get("method"), m.get("organism"), m.get("cellType")) if x and x != "not_stated"]
                    if m["conditions"]:
                        meta.append("condition: " + "; ".join(sorted(m["conditions"])))
                    st.markdown(
                        f"<div style='border-left:3px solid #c3c2b7;padding:2px 0 2px 10px;margin:6px 0'>"
                        f"{mark(m['sentence'], m['marks'])}<br><small><a href='{PUBMED}{pmid}/' target='_blank'>PMID {pmid}</a>"
                        f" · {html.escape(m.get('year', '?'))} · <i>{html.escape((m.get('journal') or '')[:60])}</i> · "
                        f"{html.escape(' · '.join(meta))}</small></div>", unsafe_allow_html=True)
                G.abstract_popover(CTX, pmid, [x["sentence"] for x in by_paper[pp]], key=f"ev_{key}")
        n_papers = sum(len(pp) for _, pp, _, _ in groups)
        if shown < n_papers and st.button(f"Show more ({n_papers - shown} more papers)", key=f"morebtn_{key}"):
            st.session_state[f"more_{key}"] = limit + 20
            st.rerun()
    with right:
        g_res = cached("provenance_goa", key)
        st.markdown("**What curators say (GOA)**: rows along this location's lineage")
        if g_res[0]:
            agg = defaultdict(lambda: {"ev": set(), "src": set(), "by": set()})
            for g in g_res[0]:
                e = agg[(g["label"], {"same": "same term", "narrower": "more specific", "broader": "broader"}[g["link"]],
                         "NOT" if g["negated"] == "true" else "")]
                e["ev"].add(g["evidence"])
                if g.get("assignedBy"):
                    e["by"].add(g["assignedBy"])
                if g.get("source") and "pubmed" in g["source"]:
                    e["src"].add(D.local(g["source"]))
            mine = {D.local(m["paper"]) for m in mentions}
            gdf = pd.DataFrame([{"GOA term": k[0], "vs paper": k[1], "NOT": k[2],
                                 "strongest evidence": EV.LABEL.get(next(iter(EV.groups_of(v["ev"])), ""), ""),
                                 "codes": ", ".join(sorted(v["ev"])), "by": ", ".join(sorted(v["by"])),
                                 "cited papers": len(v["src"]), "also ours": len(v["src"] & mine)} for k, v in agg.items()])
            st.dataframe(gdf.sort_values(["vs paper", "cited papers"], ascending=[False, False]), hide_index=True,
                         width="stretch", column_config={
                             "codes": st.column_config.TextColumn("codes", help=EV.code_title(set().union(*[v["ev"] for v in agg.values()]))),
                             "by": st.column_config.TextColumn("by", help="database that made the annotation"),
                             "also ours": st.column_config.NumberColumn("also in our papers", help="GOA-cited papers that "
                                                                        "are also among this assertion's supporting papers")})
            st.markdown(EV.legend_html(), unsafe_allow_html=True)
        else:
            st.write("GOA has nothing along this location's lineage for this protein.")
    sparql(info, ms_res, au_res, g_res)


# --- Provenance --------------------------------------------------------------------------------------
def provenance_page():
    st.title("Provenance of an assertion")
    st.caption("How one assertion is built from the RDF: papers (boxed by independent author group) → the claims "
               "extracted from their sentences → the merged assertion → the GOA rows it was compared with. Every claim "
               "was generated by the extraction run shown on top (PROV-O). Click a claim to read its paper's full abstract "
               "under the graph, with the sentence highlighted; PMIDs and ORCID iDs are links.")
    c1, c2, c3 = st.columns([2, 3, 1.2])
    with c1:
        acc, opts, _ = protein_picker("Protein", "provprot")
    lit = cached("protein_literature", acc)[0]
    if not lit:
        st.info("No assertions for this protein.")
        return
    keys = [D.local(x["a"]) for x in lit]
    lab = {D.local(x["a"]): f"{'NOT ' if vname(x['polarity']) == 'Absent' else ''}{x['label']} · {vname(x['verdict'])} · "
                            f"{x['nPapers']} papers" for x in lit}
    cur = st.session_state.get("assertion")
    with c2:
        key = st.selectbox("Assertion", keys, index=keys.index(cur) if cur in keys else 0, format_func=lab.get,
                           key=f"provkey_{acc}_{cur}")
    st.session_state["assertion"] = key
    with c3:
        n = st.slider("Papers shown", 2, 40, 10)
    info = cached("assertion", key)
    ms = cached("assertion_mentions", key)
    au = cached("provenance_authors", key)
    goa = cached("provenance_goa", key)
    run = cached("run_info")
    html_, height, stats = P.build(info[0][0], ms[0], au[0], goa[0], run[0][0] if run[0] else None, n, COLOR,
                                   abstract_fn=lambda pm: (cached("abstract", pm)[0] or [None])[0])
    st.caption(f"Showing {stats['papers_shown']} of {stats['papers_shown'] + stats['papers_hidden']} papers in "
               f"{stats['groups_shown']} of {stats['groups']} author groups (largest groups first). Two papers are in one "
               "group when they share an ORCID or at least two author names (last name + first initial); common names "
               "can merge unrelated labs, so group counts are approximate.")
    components.html(html_, height=int(height) + 24, scrolling=False)
    if st.button("Open this protein's profile"):
        open_assertion(key, acc)
    sparql(info, ms, au, goa, run)


# --- Explore -----------------------------------------------------------------------------------------
def explore():
    st.title("Explore all assertions")
    df, q, s = assertions_df()
    c1, c2, c3 = st.columns([3, 1.4, 1.6])
    verdicts = c1.pills("Verdict", D.VERDICTS, selection_mode="multi", default=["Novel", "Refinement", "Conflicting"])
    pol = c2.segmented_control("Claim", ["present", "absent"], selection_mode="multi", default=["present", "absent"])
    ymin, ymax = int(df["yearFirst"].min()), int(df["yearLast"].max())
    yr = c3.slider("Published between", ymin, ymax, (ymin, ymax))
    c4, c5, c6 = st.columns([1.6, 1.4, 3])
    min_g = c4.slider("Min. independent author groups", 1, 20, 2)
    ctx_free = c5.toggle("No condition stated", help="hide assertions where a supporting sentence names a condition "
                                                     "(treatment, disease, stimulus) that could explain the location")
    text = c6.text_input("Protein or location contains", placeholder="e.g. TFEB, lysosome")
    c7, c8 = st.columns([4, 1.6])
    evs = c7.pills("Strongest GOA evidence behind the verdict", [EV.LABEL[g] for g in EV.GROUPS] + ["none"],
                   selection_mode="multi", default=None, help="Consistent, Refinement and Conflicting have GOA rows behind "
                   "them; 'none' = Novel or Uninformative. Empty = all.")
    same = c8.toggle("GOA cites one of the papers", help="GOA curators cited one of the supporting papers")
    f = df[df["verdict"].isin(verdicts or []) & df["polarity"].isin(pol or []) & (df["nGroups"] >= min_g)
           & (df["yearLast"] >= yr[0]) & (df["yearFirst"] <= yr[1])]
    if ctx_free:
        f = f[~f["context"]]
    if evs:
        keep = {g for g in EV.GROUPS if EV.LABEL[g] in evs} | ({""} if "none" in evs else set())
        f = f[f["evidence"].isin(keep)]
    if same:
        f = f[f["samePaper"]]
    if text:
        t = text.strip().lower()
        f = f[f["symbol"].str.lower().str.contains(t, regex=False) | f["label"].str.lower().str.contains(t, regex=False)]
    f = f.sort_values(["nGroups", "nPapers"], ascending=False)
    st.markdown(f"**{len(f):,}** of {len(df):,} assertions")
    if f.empty:
        return
    left, right = st.columns([2, 3])
    with left:
        pts = f.head(3000).copy()
        pts["what"] = pts["symbol"] + (pts["polarity"].eq("absent").map({True: " NOT", False: ""})) + " in " + pts["label"]
        sel = alt.selection_point(fields=["key"], name="pick")
        chart = alt.Chart(pts).transform_calculate(      # jitter on the log scale so equal counts do not hide each other
            xj="datum.nPapers * (1 + 0.28 * (random() - 0.5))", yj="datum.nGroups * (1 + 0.28 * (random() - 0.5))"
        ).mark_circle(opacity=0.7, stroke="#fcfcfb", strokeWidth=0.8).encode(
            x=alt.X("xj:Q", scale=alt.Scale(type="log"), title="papers"),
            y=alt.Y("yj:Q", scale=alt.Scale(type="log"), title="independent author groups"),
            color=alt.Color("verdict:N", scale=alt.Scale(domain=D.VERDICTS, range=[COLOR[v] for v in D.VERDICTS]),
                            legend=alt.Legend(orient="bottom", title=None, columns=3)),
            size=alt.value(55),
            tooltip=["what", "verdict", "nPapers", "nGroups", "yearFirst", "yearLast"],
        ).add_params(sel).properties(height=420)
        picked = st.altair_chart(chart, width="stretch", on_select="rerun", key="explore_chart")
        st.caption("Click a point, then open it. Up and to the right = reported by many independent groups.")
        pk = (picked or {}).get("selection", {}).get("pick") or []
        if pk and (f["key"] == pk[0].get("key")).any():
            r = f[f["key"] == pk[0]["key"]].iloc[0]
            if st.button(f"Open {r['symbol']} in {r['label']}", type="primary", key="open_pt"):
                open_assertion(r["key"], r["acc"])
    with right:
        show = f[["key", "acc", "symbol", "label", "polarity", "verdict", "evidence", "nGroups", "nPapers", "yearFirst",
                  "yearLast", "context"]].head(1000).reset_index(drop=True)
        show["evidence"] = show["evidence"].map(lambda g: EV.LABEL.get(g, ""))
        ev = st.dataframe(show.drop(columns=["key", "acc"]).rename(columns={
            "label": "location", "polarity": "claim", "evidence": "GOA evidence", "nGroups": "groups", "nPapers": "papers", "yearFirst": "first",
            "yearLast": "last", "context": "condition"}).style.map(
            lambda v: f"background-color: {COLOR.get(v, '#ffffff')}33" if v in COLOR else "", subset=["verdict"]),
            hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", height=470,
            column_config={"first": st.column_config.NumberColumn(format="%d"),
                           "last": st.column_config.NumberColumn(format="%d")})
        if ev and ev.selection.rows:
            r = show.iloc[ev.selection.rows[0]]
            if st.button(f"Open {r['symbol']} {'NOT ' if r['polarity'] == 'absent' else ''}in {r['label']}",
                         type="primary", key="open_row"):
                open_assertion(r["key"], r["acc"])
        st.caption("Select a row, then open it (top 1,000 by independent groups).")
    sparql((df, q, s))


# --- Quality -----------------------------------------------------------------------------------------
ERROR_HELP = {   # plain meaning of the rubric's error types (reports/precision_rubric.md)
    "not_stated": ("Not stated", "The abstract never says this protein is (or is not) at this location: the location "
                   "belongs to another protein or process in the sentence, or the word is only part of a name."),
    "normalization": ("Wrong protein", "The name in the text was linked to the wrong human gene (ambiguous symbol, "
                      "family name, or a text fragment), so the claim is about the wrong protein."),
    "organism_nonhuman": ("Not a human protein", "The protein is bacterial, viral or from another species with no "
                          "human counterpart meant, but was linked to a human gene."),
    "location": ("Wrong location", "Right protein, but the GO term is not what the text says (a different or more "
                 "specific compartment)."),
    "polarity": ("Present / absent flipped", "Read as 'absent' when the text only says reduced or not observed, or "
                 "the other way round."),
}


def precision_errors(prec):
    """Quality page: what the wrong claims in the precision sample got wrong, in plain words, with examples."""
    a = prec["all"]
    errs = prec.get("errors", [])
    st.markdown("**What the wrong ones got wrong** (precision check)")
    st.caption(f"{a['n'] - a['correct']} of {a['n']} sampled claims were judged wrong "
               f"(rubric: reports/precision_rubric.md). One example per type; all of them below.")
    rows = []
    for k, n in sorted(prec["error_types"].items(), key=lambda kv: -kv[1]):
        name, help_ = ERROR_HELP.get(k, (k.replace("_", " "), ""))
        ex = next((e for e in errs if e["type"] == k), None)
        rows.append({"error": name, "claims": n, "share of wrong": round(100 * n / max(a["n"] - a["correct"], 1)),
                     "what it means": help_,
                     "example": (f"{ex['protein']} ('{ex['mention'].split(';')[0]}') {'NOT ' if ex['polarity'] == 'absent' else ''}"
                                 f"in {ex['location']}: {ex['reason']}") if ex else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", row_height=72,
                 column_config={"share of wrong": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                                "what it means": st.column_config.TextColumn(width="large"),
                                "example": st.column_config.TextColumn(width="large")})
    bv = prec.get("by_verdict", {})
    if bv:
        st.caption("Precision by verdict of the claim's assertion: " + " · ".join(
            f"{v} {x['correct']}/{x['n']} ({x['correct'] / x['n']:.0%})" for v, x in bv.items() if x["n"]))
    if errs:
        with st.expander(f"All {len(errs)} wrong claims with the judge's reason"):
            st.dataframe(pd.DataFrame([{"error": ERROR_HELP.get(e["type"], (e["type"],))[0], "protein": e["protein"],
                                        "mentioned as": e["mention"], "location": ("NOT " if e["polarity"] == "absent" else "")
                                        + e["location"], "verdict": e["verdict"], "reason": e["reason"],
                                        "PMID": f"{PUBMED}{e['pmid']}/"} for e in errs]),
                         hide_index=True, width="stretch",
                         column_config={"PMID": st.column_config.LinkColumn("PMID", display_text=r"https://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/"),
                                        "reason": st.column_config.TextColumn(width="large")})

def quality():
    st.title("How good is it?")
    st.caption("Live counts from Fuseki, plus the evaluation reports the pipeline wrote under reports/.")
    prec, silver, rdf = D.report("precision"), D.report("silver_eval"), D.report("rdf_stats")
    c = st.columns(4)
    if prec:
        a = prec["all"]
        c[0].metric("Precision (manual check)", f"{a['precision']:.0%}", help=f"{a['correct']}/{a['n']} sampled assertions "
                    f"judged correct by {', '.join(prec['judges'])}; 95% Wilson {a['wilson95'][0]:.0%}–{a['wilson95'][1]:.0%}",
                    border=True)
    if silver:
        c[1].metric("Recall vs GOA-cited abstracts", f"{silver['llm']['recall_hierarchical']:.0%}",
                    help="share of curated (protein, location) pairs from low-throughput experiments in the same abstracts "
                         "that the LLM found (same term or along its lineage). A lower bound: curators read full texts.",
                    border=True)
        c[2].metric("Agrees with GOA (LLM)", f"{silver['llm']['goa_agreement_hierarchical']:.0%}",
                    delta=f"co-occurrence baseline {silver['cooccurrence_baseline']['goa_agreement_hierarchical']:.0%}",
                    delta_color="off", border=True)
    if rdf:
        c[3].metric("Claims valid", f"{rdf['share_valid']:.1%}", help="grounded and passed the Python + SHACL validators",
                    border=True)
    left, right = st.columns(2)
    with left:
        if silver:
            st.markdown("**Recall on GOA-cited abstracts** (silver set)")
            rec = pd.DataFrame([
                {"method": "LLM", "recall": silver["llm"]["recall_hierarchical"]},
                {"method": "co-occurrence", "recall": silver["cooccurrence_baseline"]["recall_hierarchical"]},
                {"method": "ceiling", "recall": silver["coverage"]["hierarchical"]}])
            st.altair_chart(alt.Chart(rec).mark_bar(cornerRadiusEnd=4, height=22, color="#2a78d6").encode(
                x=alt.X("recall:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1]), title=None),
                y=alt.Y("method:N", sort=None, title=None, axis=alt.Axis(labelLimit=200)),
                tooltip=["method", alt.Tooltip("recall:Q", format=".1%")]).properties(height=120), width="stretch")
            st.caption(f"Ceiling: the curated protein and location are both among the abstract's candidates. "
                       f"The co-occurrence baseline pairs every protein with every location in a sentence: similar recall, but only "
                       f"{silver['cooccurrence_baseline']['goa_agreement_hierarchical']:.0%} of its pairs agree with GOA "
                       f"vs {silver['llm']['goa_agreement_hierarchical']:.0%} for the LLM. {silver['caveat']}")
    with right:
        flags = cached("error_flags")
        st.markdown("**Validator flags on claims** (live; some only warn)")
        fdf = pd.DataFrame([{"flag": f["flag"].replace("_", " "), "claims": int(f["mentions"])} for f in flags[0]])
        if len(fdf):
            st.altair_chart(alt.Chart(fdf).mark_bar(cornerRadiusEnd=4, height=16, color="#8b8a85").encode(
                x=alt.X("claims:Q", title=None), y=alt.Y("flag:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                tooltip=["flag", alt.Tooltip("claims:Q", format=",")]).properties(height=28 * len(fdf)),
                width="stretch")
        if rdf:
            qf = rdf.get("quality_flags", {})
            st.caption(f"SHACL quality shapes: {qf.get('impossible_location', 0)} impossible locations (e.g. plant "
                       f"structures), {qf.get('too_generic', 0)} too generic. SHACL gate shapes conform: "
                       f"{rdf.get('gate_conforms')}.")
        syn = D.report("synonym_stats")
        run = cached("run_info")[0]
        if syn and run and run[0]["promptVersion"] == "v3":
            st.markdown("**Ambiguous protein names** (synonym layer)")
            st.caption(f"{syn['abstracts_with_alternative_readings']:,} abstracts contain a name that can mean several "
                       f"proteins; on {syn['claims_on_ambiguous_names']:,} claims the model chose another protein than "
                       f"the tagger's in {syn['share_alternative']:.0%}.")
    vj = D.report("verdicts")
    if vj and vj.get("goa_evidence_group_behind_verdict"):
        st.markdown("**How strong is the GOA evidence behind each verdict?**")
        NOGOA = "no GOA row behind the verdict"
        role = {"Consistent": "Consistent · agrees", "Refinement": "Refinement · agrees, paper more specific",
                "Conflicting": "Conflicting · disagrees", "Novel": "Novel · nothing in GOA",
                "Uninformative": "Uninformative · too generic"}
        gb = vj["goa_evidence_group_behind_verdict"]
        evd = []
        for v in role:
            tot = vj["verdicts"].get(v, 0)
            if not tot:
                continue
            counts = [(EV.LABEL[g], gb.get(v, {}).get(g, 0)) for g in EV.GROUPS]
            counts.append((NOGOA, tot - sum(n for _, n in counts)))
            for i, (lab, n) in enumerate(counts):
                if n:
                    evd.append({"verdict": role[v], "evidence": lab, "order": i, "assertions": n, "share": n / tot,
                                "text": f"{n / tot:.0%}" if n / tot >= 0.07 else ""})
        evd = pd.DataFrame(evd)
        dom = [EV.LABEL[g] for g in EV.GROUPS] + [NOGOA]
        rng_ = [EV.EV_COLOR[g] for g in EV.GROUPS] + ["#ebe8df"]
        y = alt.Y("verdict:N", sort=[role[v] for v in role], title=None, axis=alt.Axis(labelLimit=280, labelFontSize=12))
        bars = alt.Chart(evd).mark_bar(height={"band": 0.7}, stroke="#fcfcfb", strokeWidth=2).encode(
            x=alt.X("assertions:Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
            y=y, color=alt.Color("evidence:N", scale=alt.Scale(domain=dom, range=rng_),
                                 legend=alt.Legend(orient="bottom", title=None, columns=4, labelLimit=260)),
            order=alt.Order("order:Q"),
            tooltip=["verdict", "evidence", alt.Tooltip("assertions:Q", format=","),
                     alt.Tooltip("share:Q", format=".1%", title="share of the verdict")])
        st.altair_chart(bars.properties(height={"step": 40}), width="stretch")
        st.caption("Each bar = one verdict; segments = the strongest GOA evidence among the GOA rows behind it (dark = "
                   "experimental … light = electronic); hover for counts and shares. Novel and Uninformative have no GOA row behind "
                   "them by definition.")
        up = vj.get("upgrade_candidates", {})
        st.caption(f"Strongest evidence group among the GOA rows behind the verdict. "
                   f"{sum(up.values()):,} Consistent/Refinement assertions have no experimental GOA evidence "
                   f"(literature could upgrade them); {vj.get('conflicting_with_experimental_goa', 0):,} of "
                   f"{vj['verdicts']['Conflicting']:,} conflicts are with experimental GOA. In "
                   f"{vj.get('curated_from_same_paper', 0):,} assertions GOA cites one of the supporting papers.")
    if prec:
        precision_errors(prec)
    sparql(flags)


CTX = SimpleNamespace(cached=cached, COLOR=COLOR, picker=protein_picker, sparql=sparql, assertions=assertions_df)


def conditions():
    G.conditions_page(CTX, slim_toggle)


def network():
    G.network_page(CTX)


def timeline():
    G.timeline_page(CTX)


PAGES = {
    "home": st.Page(home, title="Home", default=True),
    "protein": st.Page(protein_page, title="Profile", url_path="protein"),
    "conditions": st.Page(conditions, title="Conditions", url_path="conditions"),
    "network": st.Page(network, title="Network", url_path="network"),
    "timeline": st.Page(timeline, title="Timeline", url_path="timeline"),
    "provenance": st.Page(provenance_page, title="Provenance", url_path="provenance"),
    "explore": st.Page(explore, title="Explore", url_path="explore"),
    "quality": st.Page(quality, title="Quality", url_path="quality"),
}
SECTIONS = {"": ["home"], "Protein": ["protein", "conditions", "network", "timeline", "provenance"],
            "All assertions": ["explore", "quality"]}
if "_test_page" in st.session_state:   # used by app/check_demo.py (AppTest cannot switch to function pages)
    sidebar()
    globals()[st.session_state["_test_page"]]()
else:
    nav = st.navigation({sec: [PAGES[k] for k in ks] for sec, ks in SECTIONS.items()}, position="top")
    sidebar()
    nav.run()
