"""Schema page of the demo: what is in the knowledge graph. The class diagram and the field tables come from
reports/kg_schema.json and reports/fig_kg_*.svg (scripts/kg_schema.py, scripts/kg_schema_fig.py); the IRI lookup
runs live against Fuseki (queries/demo_iri_out.rq, demo_iri_in.rq)."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import data as D

REPORTS = Path(__file__).resolve().parents[1] / "reports"
PREFIX_LINE = " · ".join(f"{p}: {ns}" for p, ns in D.NAMESPACES.items() if p not in ("rdf", "rdfs", "owl", "xsd"))


@st.cache_data(show_spinner=False)
def schema():
    p = REPORTS / "kg_schema.json"
    return json.loads(p.read_text()) if p.exists() else None


def field_table(fields):
    rows = []
    for f in fields:
        rng = " / ".join(f["range"])
        if "values" in f and f["range"][0] in ("IRI", "boolean"):
            rng += ": " + ", ".join(f["values"])
        rows.append({"field": f["predicate"], "points to": rng, "example": f["example"]})
    return pd.DataFrame(rows)


def lookup(ctx, start):
    st.subheader("Look up any IRI")
    st.caption("Everything stored about one IRI, in every named graph, and what points to it. Accepts full IRIs or "
               "prefixed names such as `uniprot:P04637`, `obo:GO_0005739`, `pubmed:21081917`.")
    name = st.text_input("IRI", value=start, key="schema_iri", label_visibility="collapsed")
    try:
        out = ctx.cached("iri_out", name)
        inc = ctx.cached("iri_in", name)
    except ValueError as e:
        st.warning(str(e))
        return
    o_rows, i_rows = out[0], inc[0]
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(f"**{len(o_rows)} triples about it**" + (" (first 200)" if len(o_rows) == 200 else ""))
        if o_rows:
            st.dataframe(pd.DataFrame([{"graph": r["g"].split(":")[-1], "predicate": D.compact(r["p"]),
                                        "value": D.compact(r["o"])} for r in o_rows]),
                         hide_index=True, width="stretch", height=min(38 + 35 * len(o_rows), 520))
        else:
            st.info("Nothing stored with this IRI as subject.")
    with c2:
        st.markdown(f"**{len(i_rows)} links pointing to it**" + (" (first 50)" if len(i_rows) == 50 else ""))
        if i_rows:
            st.dataframe(pd.DataFrame([{"graph": r["g"].split(":")[-1], "from": D.compact(r["s"]),
                                        "predicate": D.compact(r["p"])} for r in i_rows]),
                         hide_index=True, width="stretch", height=min(38 + 35 * len(i_rows), 520))
    ctx.sparql(out, inc)


def schema_page(ctx):
    st.title("What is in the knowledge graph")
    s = schema()
    if not s:
        st.error("reports/kg_schema.json is missing: run `make schema` on the server.")
        return
    total = sum(g["triples"] for g in s["graphs"])
    st.caption(f"{len(s['graphs'])} data graphs, {total:,} triples, run `{s['run_id']}`. Boxes are classes, "
               "arrows are links; the colour says which named graph stores the triples. Dashed boxes are classes of the "
               "official ontologies (GO, ECO, UniProt locations): a location or an evidence is an individual of such "
               "a class (\"is a\"). Read from the live data by `scripts/kg_schema.py`.")
    parts = [("Papers and people", "papers"), ("Claims", "claims"), ("Curation and verdicts", "curation"),
             ("Proteins (UniProt)", "uniprot")]
    for tab, (_, key) in zip(st.tabs([t for t, _ in parts]), parts):
        with tab:
            if (REPORTS / f"fig_kg_{key}.svg").exists():
                st.image(str(REPORTS / f"fig_kg_{key}.svg"), width="stretch")
    with st.expander("Every class with all its fields (one picture)"):
        if (REPORTS / "fig_kg_schema.svg").exists():
            st.image(str(REPORTS / "fig_kg_schema.svg"), width="stretch")
    st.caption("Prefixes: " + PREFIX_LINE)

    st.subheader("Graph by graph")
    names = [g["name"] for g in s["graphs"]]
    pick = st.segmented_control("Named graph", names, default="run", key="schema_graph",
                                label_visibility="collapsed") or "run"
    g = next(x for x in s["graphs"] if x["name"] == pick)
    st.markdown(f"`{g['graph']}` · {g['triples']:,} triples · {g['about']}")
    first = None
    for c in g["classes"]:
        where = "" if c["typed_here"] else " · *typed in another graph; these fields are added here*"
        ex = f" · example `{c['example_subject']}`" if c["example_subject"] else ""
        st.markdown(f"**{c['class']}**{where}{ex}")
        if c["fields"]:
            st.dataframe(field_table(c["fields"]), hide_index=True, width="stretch",
                         height=38 + 35 * len(c["fields"]))
        first = first or c["example_subject"]

    lookup(ctx, first or "uniprot:P04637")
