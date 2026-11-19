"""Schema of the knowledge graph, read from the live Fuseki data (read-only): for every named graph, which
classes it holds, which fields (predicates) each class has there, and what each field points to (another
class, an outside IRI, a fixed set of values, or text / number / date), with one example value.

Queries: queries/schema_*.rq. Subjects that are typed in another graph (verdicts sit on assertions, the abstract
sits on papers) are grouped under that class. Each predicate is sampled (SAMPLE triples), so this takes seconds;
a field that is rare *and* on a different class than the sampled ones could be missed, which the counts check at
the end would show as an empty class.

Output: reports/kg_schema.json and reports/kg_schema.md (one table per graph). The figure is drawn by
scripts/kg_schema_fig.py from the JSON.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locx.config import CFG, QUERIES, RDF, REPORTS  # noqa: E402
from locx.kg import fuseki  # noqa: E402
from locx.kg.ttl import NAMESPACES  # noqa: E402

SAMPLE = 300          # triples sampled per predicate
OFFSET = 1000         # skip the start of the index, where values are sorted (first values are untypical)
ENUM_MAX = 12         # a field with at most this many distinct values is listed as a fixed set
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

PREFIXES = {ns: p + ":" for p, ns in NAMESPACES.items()}
# outside IRIs that are not typed anywhere in our data, named by their namespace
EXTERNAL = {"https://pubmed.ncbi.nlm.nih.gov/": "PubMed paper (not in our corpus)",
            "http://purl.uniprot.org/uniprot/": "UniProt entry (not human Swiss-Prot)",
            "http://purl.uniprot.org/citations/": "UniProt citation", "http://purl.uniprot.org/geneid/": "NCBI GeneID",
            "http://purl.uniprot.org/taxonomy/": "UniProt taxon", "http://purl.uniprot.org/database/": "UniProt database",
            "http://purl.uniprot.org/locations/": "UniProt location term",
            "http://purl.obolibrary.org/obo/ECO_": "ECO evidence term", "http://purl.obolibrary.org/obo/NCBITaxon_": "NCBI taxon",
            "http://purl.obolibrary.org/obo/RO_": "RO relation", "http://purl.obolibrary.org/obo/BFO_": "RO relation",
            "http://purl.obolibrary.org/obo/GO_": "GO term", "https://orcid.org/": "ORCID person",
            "http://purl.obolibrary.org/obo/go#": "GO slim"}


def short(iri: str) -> str:
    for ns, p in PREFIXES.items():
        if iri.startswith(ns):
            return p + iri[len(ns):]
    return f"<{iri}>"


def q(name: str, **params) -> str:
    text = (QUERIES / name).read_text()
    for k, v in params.items():
        text = text.replace(f"%{k}%", str(v))
    return text


def rows(query: str) -> list[dict]:
    """Bindings with their RDF term type kept (uri / literal / bnode), unlike fuseki.select."""
    return fuseki.query(query)["results"]["bindings"]


OWL_CLASS, OWL_PROPERTY = "http://www.w3.org/2002/07/owl#Class", "http://www.w3.org/2002/07/owl#ObjectProperty"
# individuals typed with a class of an outside ontology (a statement's location, a GOA row's evidence) are grouped
BUCKETS = {"http://purl.obolibrary.org/obo/GO_": "GO class individual", "http://purl.obolibrary.org/obo/ECO_": "ECO class individual"}


def bucket(cls: str | None) -> str | None:
    for ns, name in BUCKETS.items():
        if cls and cls.startswith(ns):
            return name
    return cls


def object_kind(o: dict, o_class: str | None) -> str:
    if o["type"] == "literal":
        dt = o.get("datatype", "http://www.w3.org/2001/XMLSchema#string")
        return "text@" + o["xml:lang"] if "xml:lang" in o else short(dt).replace("xsd:", "")
    if o["type"] == "bnode":
        return short(o_class) if o_class else "blank node"
    if o_class and bucket(o_class) != o_class:
        return bucket(o_class)
    if o_class and o_class not in (OWL_CLASS, OWL_PROPERTY):
        return short(o_class)
    if not o_class and o["value"].startswith("http://purl.uniprot.org/uniprot/") and "#" in o["value"]:
        return "(untyped)"              # a node inside a UniProt entry that UniProt gives no class (located-in nodes)
    for ns, name in EXTERNAL.items():   # ontology terms (GO, ECO, RO ...) are named by their ID space
        if o["value"].startswith(ns):
            return name
    if o_class:
        return short(o_class)
    for ns, name in EXTERNAL.items():
        if o["value"].startswith(ns):
            return name
    return "IRI"


def show(o: dict) -> str:
    v = o["value"]
    if o["type"] == "uri":
        return short(v)
    v = " ".join(v.split())
    return v if len(v) <= 90 else v[:87] + "..."


def graph_schema(graph: str) -> dict:
    preds = [r["p"]["value"] for r in rows(q("schema_predicates.rq", GRAPH=graph))]
    typed_here = {bucket(r["class"]["value"]) for r in rows(q("schema_classes.rq", GRAPH=graph))}
    classes = defaultdict(dict)                     # class -> predicate -> field
    subjects = defaultdict(Counter)                 # class -> subject -> number of fields seen (to pick an example)
    for p in preds:
        if p == RDF_TYPE:
            continue
        sample = rows(q("schema_sample.rq", GRAPH=graph, PRED=p, OFFSET=OFFSET, LIMIT=SAMPLE)) \
            or rows(q("schema_sample.rq", GRAPH=graph, PRED=p, OFFSET=0, LIMIT=SAMPLE))
        values = rows(q("schema_values.rq", GRAPH=graph, PRED=p))
        by_class = defaultdict(list)
        for r in sample:
            sc = bucket(r.get("sClass", {}).get("value", "(untyped)"))
            by_class[sc].append(r)
        for sc, rs in by_class.items():
            kinds = Counter(object_kind(r["o"], r.get("oClass", {}).get("value")) for r in rs)
            field = {"predicate": short(p), "range": [k for k, _ in kinds.most_common()],
                     "example": show(rs[len(rs) // 2]["o"])}
            if len(values) <= ENUM_MAX:
                field["values"] = sorted(show(v["o"]) for v in values)
            classes[sc][short(p)] = field
            for r in rs:
                if r["s"]["type"] == "uri":
                    subjects[sc][r["s"]["value"]] += 1
    out = []
    for sc in sorted(classes, key=lambda c: (c not in typed_here, short(c))):
        ex = subjects[sc].most_common(1)
        out.append({"class": short(sc) if sc != "(untyped)" and sc.startswith("http") else sc, "typed_here": sc in typed_here,
                    "example_subject": short(ex[0][0]) if ex else None,
                    "fields": sorted(classes[sc].values(), key=lambda f: f["predicate"])})
    for c in sorted(typed_here - set(classes)):     # typed here, but the predicate samples did not reach an instance
        fields, ex = {}, None
        if c.startswith("http"):
            for r in rows(q("schema_class_fields.rq", GRAPH=graph, CLASS=c)):
                ex = short(r["s"]["value"]) if r["s"]["type"] == "uri" else None
                fields.setdefault(short(r["p"]["value"]), {"predicate": short(r["p"]["value"]),
                                                           "range": [object_kind(r["o"], r.get("oClass", {}).get("value"))],
                                                           "example": show(r["o"])})
        out.append({"class": short(c) if c.startswith("http") else c, "typed_here": True, "example_subject": ex,
                    "fields": sorted(fields.values(), key=lambda f: f["predicate"])})
    return {"graph": graph, "classes": out}


def example_values(graph: str, cls: dict) -> None:
    """Replace the per-field examples with the values of one subject that has most fields, so a class's
    examples belong together (one mention, one paper, ...). Fields that subject lacks keep their sampled example."""
    s = cls["example_subject"]
    if not s or s.startswith("<"):
        return
    iri = next(ns + s[len(p):] for ns, p in PREFIXES.items() if s.startswith(p))
    own = defaultdict(list)
    for r in rows(f"SELECT ?p ?o WHERE {{ GRAPH <{graph}> {{ <{iri}> ?p ?o }} }}"):
        own[short(r["p"]["value"])].append(show(r["o"]))
    for f in cls["fields"]:
        if own.get(f["predicate"]):
            f["example"] = " | ".join(sorted(own[f["predicate"]])[:3]) + (" | ..." if len(own[f["predicate"]]) > 3 else "")


def markdown(schema: dict) -> str:
    lines = ["# Knowledge graph schema", "",
             "Read from the live Fuseki data by `scripts/kg_schema.py` (queries `queries/schema_*.rq`). One table per",
             "named graph: the classes it holds, their fields, what each field points to, and one example value.",
             "A class marked *typed in another graph* gets extra fields here (e.g. verdicts on assertions).", "",
             "Prefixes: " + ", ".join(f"`{p}` {ns}" for ns, p in PREFIXES.items() if p in
                                      ("locx:", "obo:", "uniprot:", "pubmed:", "prov:", "dcterms:", "fabio:", "foaf:", "oboInOwl:")),
             ""]
    for g in schema["graphs"]:
        lines += [f"## `{g['graph']}`", "", f"{g['triples']:,} triples. {g['about']}", ""]
        for c in g["classes"]:
            where = "" if c["typed_here"] else " *(typed in another graph)*"
            ex = f" — example `{c['example_subject']}`" if c["example_subject"] else ""
            lines += [f"**{c['class']}**{where}{ex}", ""]
            if not c["fields"]:
                lines += ["(only its type is stated here)", ""]
                continue
            lines += ["| Field | Points to | Example |", "|---|---|---|"]
            for f in c["fields"]:
                rng = " / ".join(f["range"])
                if "values" in f and f["range"][0] in ("IRI", "boolean"):
                    rng += ": " + ", ".join(f["values"])
                elif "values" in f:
                    rng += f" (one of {len(f['values'])})"
                ex = f["example"].replace("|", "\\|")
                lines.append(f"| `{f['predicate']}` | {rng} | {ex} |")
            lines.append("")
    return "\n".join(lines) + "\n"


ABOUT = {
    "go": "The official GO release (go-basic.owl 2026-07-26), unmodified.",
    "eco": "The official ECO release (2026-07-10), unmodified.", "ro": "The official RO release (2026-09-04), unmodified.",
    "uniprot-locations": "UniProt's subcellular location vocabulary, as published.",
    "goa-human": "GOA human cellular component annotations: one node per row of GOA's annotation file, with its "
                 "evidence (ECO), relation (RO), references and contexts.",
    "uniprot-human": "Human Swiss-Prot proteins in UniProt's own vocabulary (up:), from UniProt's SPARQL endpoint: "
                     "names, gene, NCBI GeneID, and the subcellular location annotation with its evidence.",
    "papers": "The corpus: papers (Europe PMC metadata), journals (NLM Catalog), authorships and authors.",
    "support": "Per assertion: claim, paper and independent author-group counts, author groups as entities (support activity).",
    "inferred": "What the OWL 2 RL reasoner infers from the locx ontology + GO module + ECO and our data (make reason).",
    "assertions": "Deduplicated claims (protein, location, polarity), shared across runs.",
    "verdicts": "Per assertion: the verdict against GOA as a Verdict entity, the GOA rows behind it (verdict activity).",
    "abstracts": "The text the LLM read per paper (PubTator title + abstract), one fabio:Abstract each.",
    "run": "One extraction run: the run activity, the model agent, every claim with its evidence sentence (Web Annotation).",
}


def main():
    manifest = json.loads((RDF / "loaded.json").read_text())
    graphs = []
    for g, info in manifest.items():
        G = CFG["graphs"]
        if g in (G["ontology"], G["go"], G["eco"], G["ro"], G["uniprot_locations"], G["uniprot_core"], G["inferred"]):
            continue   # ontologies (ours and the official releases) and inferred facts: not our data's schema
        key = g.split(":")[-1].split("/")[0]
        print(f"[schema] {g} ...", flush=True)
        s = graph_schema(g)
        for c in s["classes"]:
            example_values(g, c)
        s.update(name=key, triples=info["triples"], about=ABOUT.get(key, ""))
        graphs.append(s)
        print(f"[schema]   {len(s['classes'])} classes, {sum(len(c['fields']) for c in s['classes'])} fields")
    schema = {"run_id": CFG["extract"]["main_run"], "graphs": graphs}
    (REPORTS / "kg_schema.json").write_text(json.dumps(schema, indent=1))
    (REPORTS / "kg_schema.md").write_text(markdown(schema))
    print(f"[schema] -> {REPORTS / 'kg_schema.json'}, {REPORTS / 'kg_schema.md'}")


if __name__ == "__main__":
    main()
