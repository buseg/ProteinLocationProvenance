"""make check-ontology: check the data against the hand-maintained locx ontology (ontology/locx.owl.ttl), the
other way round from a generated ontology ("ontology first").

1. Coverage: every class and predicate used in our data graphs is declared in the ontology (the external releases
   go, eco, ro, uniprot-locations are other people's ontologies and are not checked against ours).
2. Outside IDs written in the ontology exist in their sources: GO flags (current, cellular component) in graph go,
   ECO roots in graph eco, the claims' relation in graph ro, NCBITaxon matches via EBI's Ontology Lookup Service
   (cached in data/raw/obo/ols_*.json).
3. HermiT (OWL 2 DL) on the ontology with ECO and the cellular-component module of GO: consistency and
   unsatisfiable classes. Not with all of GO (did not finish in 30 min; GO classifies its own release with ELK) and
   not with RO (did not finish in 5 min: RO's property chains; our ontology uses RO terms only as values).
4. A one-protein sample for Protégé (ontology/sample_<SYMBOL>.ttl, queries/ontology_sample.rq) checked triple by
   triple against domains, ranges, functional properties and disjoint classes.
-> reports/ontology.json

  python scripts/check_ontology.py [--protein TFEB] [--no-hermit]
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from rdflib import Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx import ontology as O  # noqa: E402
from locx.config import CFG, QUERIES, RAW, REPORTS, ROOT  # noqa: E402
from locx.io import get_json  # noqa: E402
from locx.kg import fuseki, releases  # noqa: E402
from locx.kg.ttl import NAMESPACES  # noqa: E402

G = CFG["graphs"]
RUN_GRAPH = G["run_prefix"] + CFG["extract"]["main_run"]
OURS = {"papers": G["papers"], "abstracts": G["abstracts"], "run": RUN_GRAPH, "assertions": G["assertions"],
        "goa-human": G["goa"], "uniprot-human": G["uniprot"], "support": G["support"], "verdicts": G["verdicts"]}
BUILTIN = {str(RDF.type), str(RDFS.label), str(RDFS.comment), str(RDFS.seeAlso), str(RDFS.subClassOf),
           str(RDF.subject), str(RDF.predicate), str(RDF.object), str(OWL.sameAs)}
OUT = ROOT / "ontology"
CATALOG_NOTE = "catalog-v001.xml resolves the imports to data/raw/obo/ (server) or the OBO PURLs (elsewhere)"


def short(iri: str) -> str:
    for p, ns in NAMESPACES.items():
        if iri.startswith(ns):
            return f"{p}:{iri[len(ns):]}"
    return iri


# --- 1. coverage --------------------------------------------------------------------------------------------------
def coverage() -> dict:
    declared = {str(s) for s in O.graph().subjects(RDF.type, None)}
    out = {}
    for name, g in OURS.items():
        preds = {r["p"] for r in fuseki.select(f"SELECT DISTINCT ?p WHERE {{ GRAPH <{g}> {{ ?s ?p ?o }} }}")}
        classes = {r["c"] for r in fuseki.select(f"SELECT DISTINCT ?c WHERE {{ GRAPH <{g}> {{ ?s a ?c }} }}")}
        # classes of the imported GO, ECO and UniProt core releases count as declared (e.g. the types of location and
        # evidence individuals, UniProt's name and citation nodes)
        imported = {r["c"] for r in fuseki.select(f"""PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?c WHERE {{ GRAPH <{g}> {{ ?s a ?c }}
              {{ GRAPH <{G['go']}> {{ ?c a owl:Class }} }} UNION {{ GRAPH <{G['eco']}> {{ ?c a owl:Class }} }}
              UNION {{ GRAPH <{G['uniprot_core']}> {{ ?c a owl:Class }} }} }}""")}
        out[name] = {"predicates": len(preds), "classes": len(classes), "classes_from_go_eco": len(imported),
                     "undeclared_predicates": sorted(short(p) for p in preds - declared - BUILTIN),
                     "undeclared_classes": sorted(short(c) for c in classes - declared - imported
                                                  if not c.startswith(str(RDF)))}
    return out


# --- 2. outside IDs -------------------------------------------------------------------------------------------------
def outside_ids() -> dict:
    problems, checked = [], []
    for prop in ("tooGeneric", "nonHumanCompartmentRoot"):
        for term in O.annotated(prop):
            rows = fuseki.select(f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX oio: <http://www.geneontology.org/formats/oboInOwl#> PREFIX owl: <http://www.w3.org/2002/07/owl#>
                SELECT ?label ?ns ?dep WHERE {{ GRAPH <{G['go']}> {{ <{term}> rdfs:label ?label .
                  OPTIONAL {{ <{term}> oio:hasOBONamespace ?ns }} OPTIONAL {{ <{term}> owl:deprecated ?dep }} }} }}""")
            ok = rows and rows[0].get("ns") == "cellular_component" and rows[0].get("dep") != "true"
            checked.append({"term": short(term), "as": prop, "label": rows[0]["label"] if rows else None, "ok": bool(ok)})
            if not ok:
                problems.append(f"{short(term)} ({prop}) is not a current GO cellular component term")
    g = O.graph()
    for root_prop in ("ecoRoot", "ecoExcludedRoot"):
        for _, root in g.subject_objects(O.expand(f"locx:{root_prop}")):
            rows = fuseki.select(f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?label WHERE {{ GRAPH <{G['eco']}> {{ <{root}> rdfs:label ?label }} }}""")
            checked.append({"term": short(str(root)), "as": root_prop, "label": rows[0]["label"] if rows else None,
                            "ok": bool(rows)})
            if not rows:
                problems.append(f"{short(str(root))} ({root_prop}) is not in ECO")
    rel = O.class_annotation("Claim", "statesRelation")
    rows = fuseki.select(f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?label WHERE {{ GRAPH <{G['ro']}> {{ <{rel}> rdfs:label ?label }} }}""")
    checked.append({"term": short(rel), "as": "Claim relation", "label": rows[0]["label"] if rows else None,
                    "ok": bool(rows) and rows[0]["label"] == "located in"})
    if not checked[-1]["ok"]:
        problems.append(f"the claims' relation {short(rel)} is not RO 'located in'")
    for v, match in g.subject_objects(O.LOCX.taxon):
        curie = str(match).rsplit("/", 1)[1].replace("_", ":")
        cache = RAW / "obo" / f"ols_{curie.replace(':', '_')}.json"
        if not cache.exists():
            cache.write_text(json.dumps(get_json("https://www.ebi.ac.uk/ols4/api/ontologies/ncbitaxon/terms",
                                                 params={"obo_id": curie})))
        label = json.loads(cache.read_text())["_embedded"]["terms"][0]["label"]
        expected = str(g.value(v, RDFS.comment) or "").rstrip(".")
        checked.append({"term": curie, "as": f"locx:taxon of {short(str(v))}", "label": label, "ok": label == expected})
        if label != expected:
            problems.append(f"{curie} is {label!r}, {short(str(v))} says {expected!r}")
    return {"checked": checked, "problems": problems}


# --- 3. HermiT ------------------------------------------------------------------------------------------------------
def hermit() -> dict:
    """HermiT on locx + ECO + UniProt core + the GO cellular-component module (owlready2 reads RDF/XML)."""
    import tempfile

    import owlready2 as o
    o.reasoning.JAVA_MEMORY = 16000
    t = time.time()
    with tempfile.TemporaryDirectory() as d:
        ours = Graph().parse(O.PATH)
        ours.remove((None, OWL.imports, None))
        ours.serialize(f"{d}/locx.owl", format="xml")
        Graph().parse(releases.go_cc_module(), format="nt").serialize(f"{d}/go_cc.owl", format="xml")
        # UniProt core imports FALDO, SKOS, FOAF and RDF(S) from the web; none is needed here, so its imports are
        # dropped (as for our ontology, whose imports are given as local files)
        up = Graph().parse(releases.path("uniprot_core"))
        up.remove((None, OWL.imports, None))
        # HermiT supports only the OWL 2 datatype map, which has no xsd:date, xsd:gYear or xsd:gYearMonth; UniProt core
        # uses them in 5 axioms (e.g. the ranges of up:created and up:modified). In this copy they become rdfs:Literal
        widened = [(s_, p_, o_) for s_, p_, o_ in up if o_ in (XSD.date, XSD.gYear, XSD.gYearMonth)]
        for s_, p_, o_ in widened:
            up.remove((s_, p_, o_))
            up.add((s_, p_, RDFS.Literal))
        up.serialize(f"{d}/uniprot_core.owl", format="xml")
        w = o.World()
        for p in (f"{d}/go_cc.owl", str(releases.path("eco")), f"{d}/uniprot_core.owl", f"{d}/locx.owl"):
            w.get_ontology("file://" + os.path.abspath(p)).load(only_local=True)
        try:
            o.sync_reasoner_hermit(w, infer_property_values=False, debug=0)
            unsat = [str(c) for c in w.inconsistent_classes()]
            res = {"consistent": True, "unsatisfiable_classes": unsat}
        except o.OwlReadyInconsistentOntologyError:
            res = {"consistent": False, "unsatisfiable_classes": None}
    res.update(reasoner="HermiT (owlready2 0.51)",
               note=f"UniProt core without its web imports; xsd:date / gYear / gYearMonth widened to rdfs:Literal "
                    f"in {len(widened)} axioms (not in HermiT's OWL 2 datatype map)",
               imports="locx + ECO + UniProt core + GO cellular-component module "
               "(not all of GO: >30 min; not RO: >5 min, used only as annotation values)",
               seconds=round(time.time() - t))
    print(f"[ontology] HermiT: {res}", flush=True)
    return res


# --- 4. sample ------------------------------------------------------------------------------------------------------
def build_sample(symbol: str) -> tuple[Graph, str]:
    acc = fuseki.select(f"""PREFIX up: <http://purl.uniprot.org/core/> PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT DISTINCT ?p WHERE {{ GRAPH <{G['uniprot']}> {{ ?p up:encodedBy/skos:prefLabel "{symbol}" }} }}""")
    if len(acc) != 1:
        raise SystemExit(f"[ontology] gene symbol {symbol!r}: {len(acc)} proteins")
    protein = acc[0]["p"]
    q = (QUERIES / "ontology_sample.rq").read_text().replace("%PROTEIN%", protein).replace("%RUN_GRAPH%", RUN_GRAPH)
    r = requests.post(f"{fuseki.BASE}/sparql", data={"query": q}, headers={"Accept": "text/turtle"}, timeout=600)
    r.raise_for_status()
    g = Graph().parse(data=r.text, format="turtle")
    s = URIRef(f"http://example.org/locx/sample/{symbol}")
    g.add((s, RDF.type, OWL.Ontology))
    g.add((s, OWL.imports, URIRef("http://example.org/locx/ontology")))
    for p, ns in NAMESPACES.items():
        g.bind(p, ns)
    return g, protein


def class_set(ont: Graph, node):
    if (node, OWL.unionOf, None) in ont:
        return set(Collection(ont, ont.value(node, OWL.unionOf)))
    return {node}


def check_sample(ont: Graph, sample: Graph) -> dict:
    """Every triple of the sample against the ontology: subject in the domain, object in the range (class or datatype),
    at most one value for functional properties, nothing typed with two disjoint classes."""
    types = defaultdict(set)
    for s, o_ in (sample + ont).subject_objects(RDF.type):
        types[s].add(o_)
    sup = defaultdict(set)   # our ontology's hierarchy plus the GO / ECO ancestors included in the sample
    for c, d in (ont + sample).subject_objects(RDFS.subClassOf):
        sup[c].add(d)

    def closure(ts):
        out, todo = set(ts), list(ts)
        while todo:
            for d in sup.get(todo.pop(), ()):
                if d not in out:
                    out.add(d)
                    todo.append(d)
        return out
    problems, examples = defaultdict(int), {}
    functional = set(ont.subjects(RDF.type, OWL.FunctionalProperty))
    seen = defaultdict(set)
    n = 0
    for s, p, o_ in sample:
        if p == RDF.type or (s, RDF.type, OWL.Ontology) in sample:
            continue
        n += 1
        dom, rng = ont.value(p, RDFS.domain), ont.value(p, RDFS.range)
        if dom is not None and not closure(types.get(s, set())) & class_set(ont, dom):
            problems[f"domain {short(str(p))}"] += 1
            examples.setdefault(f"domain {short(str(p))}", str(s))
        if rng is not None:
            ok = ((o_.datatype or XSD.string) == rng) if isinstance(o_, Literal) else \
                bool(closure(types.get(o_, set())) & class_set(ont, rng))
            if not ok:
                problems[f"range {short(str(p))}"] += 1
                examples.setdefault(f"range {short(str(p))}", f"{s} -> {o_}")
        if p in functional:
            seen[(s, p)].add(o_)
    for (s, p), vals in seen.items():
        if len(vals) > 1:
            problems[f"functional {short(str(p))}"] += 1
            examples.setdefault(f"functional {short(str(p))}", str(s))
    for d in ont.subjects(RDF.type, OWL.AllDisjointClasses):
        members = set(Collection(ont, ont.value(d, OWL.members)))
        for s, ts in types.items():
            if len(closure(ts) & members) > 1:
                problems["disjoint classes"] += 1
                examples.setdefault("disjoint classes", str(s))
    return {"triples_checked": n, "problems": dict(problems), "examples": examples}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protein", default="TFEB", help="gene symbol for the Protégé sample")
    ap.add_argument("--no-hermit", action="store_true")
    a = ap.parse_args()
    ont = O.graph()
    cov = coverage()
    print(f"[ontology] coverage: " + "; ".join(f"{k}: {len(v['undeclared_predicates'])} undeclared predicates, "
                                               f"{len(v['undeclared_classes'])} undeclared classes" for k, v in cov.items()))
    ids = outside_ids()
    print(f"[ontology] outside IDs: {len(ids['checked'])} checked, problems {ids['problems']}")
    hr = None if a.no_hermit else hermit()
    sample, protein = build_sample(a.protein)
    path = OUT / f"sample_{a.protein}.ttl"
    sample.serialize(path, format="turtle")
    chk = check_sample(ont, sample)
    print(f"[ontology] {path.name}: {len(sample):,} triples; {chk['triples_checked']:,} checked, problems {chk['problems']}")
    out = {"ontology": str(O.PATH.relative_to(ROOT)), "version": O.version(), "catalog": CATALOG_NOTE,
           "coverage": cov, "coverage_ok": not any(v["undeclared_predicates"] or v["undeclared_classes"] for v in cov.values()),
           "outside_ids": ids, "hermit": hr,
           "sample": {"file": str(path.relative_to(ROOT)), "protein": protein, "symbol": a.protein,
                      "triples": len(sample), **chk, "ok": not chk["problems"]}}
    out["ok"] = out["coverage_ok"] and not ids["problems"] and out["sample"]["ok"] and (hr is None or hr["consistent"])
    (REPORTS / "ontology.json").write_text(json.dumps(out, indent=1))
    print(f"[ontology] ok: {out['ok']} -> reports/ontology.json")
    if not out["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
