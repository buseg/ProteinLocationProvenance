"""GO cellular component subgraph -> Turtle, location dictionary, non-human / too-generic sets.

part_of is written as a direct class-class triple (obo:BFO_0000050) on purpose, so that
(rdfs:subClassOf|obo:BFO_0000050)* works in SPARQL. Not OWL-correct (SPEC M2.1).
"""
import json
import re
from collections import defaultdict

import obonet

from locx.config import CFG, INTERIM, RDF
from locx.kg.ttl import PREFIXES, block, go_iri, lit

# Adjective / short-form map (SPEC M2.4); every ID is verified by its label at build time.
ADJECTIVES = [
    (["nuclear", "nucleus", "nuclei"], "GO:0005634", "nucleus"),
    (["nucleoplasmic"], "GO:0005654", "nucleoplasm"),
    (["nucleolar"], "GO:0005730", "nucleolus"),
    (["cytoplasmic"], "GO:0005737", "cytoplasm"),
    (["cytosolic"], "GO:0005829", "cytosol"),
    (["mitochondrial", "mitochondria"], "GO:0005739", "mitochondrion"),
    (["lysosomal", "lysosomes"], "GO:0005764", "lysosome"),
    (["endosomal", "endosomes"], "GO:0005768", "endosome"),
    (["peroxisomal"], "GO:0005777", "peroxisome"),
    (["perinuclear"], "GO:0048471", "perinuclear region of cytoplasm"),
    (["plasma membrane", "cell membrane"], "GO:0005886", "plasma membrane"),
    (["cell surface"], "GO:0009986", "cell surface"),
    (["extracellular", "secreted"], "GO:0005576", "extracellular region"),
    (["endoplasmic reticulum"], "GO:0005783", "endoplasmic reticulum"),  # bare "ER" excluded (estrogen receptor)
    (["Golgi"], "GO:0005794", "Golgi apparatus"),
    (["centrosomal"], "GO:0005813", "centrosome"),
    (["stress granules"], "GO:0010494", "cytoplasmic stress granule"),
]
# Roots whose descendants (is_a or part_of) cannot be in human cells (SPEC M2.5).
NON_HUMAN_ROOTS = {"GO:0009536": "plastid", "GO:0005618": "cell wall",
                   "GO:0009579": "thylakoid", "GO:0042597": "periplasmic space"}
# Too generic to support a verdict (SPEC M2.6); labels have changed over time, so match on ID only.
TOO_GENERIC = ["GO:0005575", "GO:0110165", "GO:0005622"]

SYN = re.compile(r'^"((?:[^"\\]|\\.)*)"\s+(EXACT|RELATED|NARROW|BROAD)')


def parse(obo_path):
    g = obonet.read_obo(obo_path)
    cc = {n: d for n, d in g.nodes(data=True)
          if d.get("namespace") == "cellular_component" and not d.get("is_obsolete")}
    parents = defaultdict(set)   # child -> {(relation, parent)}
    for child, parent, rel in g.edges(keys=True):
        if child in cc and parent in cc and rel in ("is_a", "part_of"):
            parents[child].add((rel, parent))
    return g.graph.get("data-version", "?"), cc, parents


def synonyms(d):
    out = []
    for s in d.get("synonym", []):
        m = SYN.match(s)
        if m:
            out.append((m.group(2), m.group(1).replace('\\"', '"')))
    return out


def descendants(roots, parents):
    children = defaultdict(set)
    for c, ps in parents.items():
        for _, p in ps:
            children[p].add(c)
    seen, todo = set(roots), list(roots)
    while todo:
        for c in children[todo.pop()]:
            if c not in seen:
                seen.add(c)
                todo.append(c)
    return seen


def check_label(cc, go_id, expected):
    if go_id not in cc:
        raise SystemExit(f"[go_cc] FAIL: {go_id} [{expected}] is not a live CC term in go-basic.obo")
    if cc[go_id]["name"] != expected:
        raise SystemExit(f"[go_cc] FAIL: {go_id} label is {cc[go_id]['name']!r}, expected {expected!r}")


def build(obo_path):
    version, cc, parents = parse(obo_path)

    for _, go_id, label in ADJECTIVES:
        check_label(cc, go_id, label)
    for go_id, label in NON_HUMAN_ROOTS.items():
        check_label(cc, go_id, label)
    for go_id in TOO_GENERIC:
        if go_id not in cc:
            raise SystemExit(f"[go_cc] FAIL: too-generic term {go_id} missing")
    non_human = descendants(NON_HUMAN_ROOTS, parents)
    too_generic = {g: cc[g]["name"] for g in TOO_GENERIC}

    # Turtle
    out = RDF / "go_cc.ttl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n_isa = n_partof = 0
    with open(out, "w") as f:
        f.write(PREFIXES)
        for go_id, d in sorted(cc.items()):
            pairs = [("a", "owl:Class"), ("rdfs:label", lit(d["name"]))]
            for kind, text in synonyms(d):
                if kind == "EXACT":
                    pairs.append(("oboInOwl:hasExactSynonym", lit(text)))
                elif kind == "RELATED":
                    pairs.append(("oboInOwl:hasRelatedSynonym", lit(text)))
            for rel, p in sorted(parents[go_id]):
                pairs.append(("rdfs:subClassOf" if rel == "is_a" else "obo:BFO_0000050", go_iri(p)))
                n_isa += rel == "is_a"
                n_partof += rel == "part_of"
            if go_id in non_human:
                pairs.append(("locx:nonHumanCompartment", "true"))
            if go_id in too_generic:
                pairs.append(("locx:tooGeneric", "true"))
            f.write(block(go_iri(go_id), pairs))

    # Dictionary: label + exact + related synonyms + adjective map, minus the stoplist
    stop = {s.lower() for s in CFG["candidates"]["stoplist"]}
    rows, dropped = set(), defaultdict(int)
    def add(text, go_id, source):
        text = text.strip()
        if len(text) < 3:
            dropped["shorter_than_3"] += 1
        elif text.lower() in stop:
            dropped["stoplist"] += 1
        else:
            rows.add((text, go_id, cc[go_id]["name"], source))
    for go_id, d in cc.items():
        add(d["name"], go_id, "label")
        for kind, text in synonyms(d):
            if kind in ("EXACT", "RELATED"):
                add(text, go_id, kind.lower())
    for forms, go_id, _ in ADJECTIVES:
        for form in forms:
            add(form, go_id, "adjective_map")
    by_text = defaultdict(set)
    for text, go_id, _, _ in rows:
        by_text[text.lower()].add(go_id)
    ambiguous = sorted(t for t, ids in by_text.items() if len(ids) > 1)

    INTERIM.mkdir(parents=True, exist_ok=True)
    with open(INTERIM / "go_cc_dictionary.tsv", "w") as f:
        f.write("text\tgo_id\tlabel\tsource\n")
        for r in sorted(rows, key=lambda r: (r[0].lower(), r[1], r[3])):
            f.write("\t".join(r) + "\n")
    sets = {"go_data_version": version,
            "non_human": sorted(non_human),
            "too_generic": too_generic,
            "adjective_map_verified": {go_id: label for _, go_id, label in ADJECTIVES}}
    (INTERIM / "go_cc_sets.json").write_text(json.dumps(sets, indent=1))

    stats = {"go_data_version": version, "cc_terms": len(cc), "is_a_edges": n_isa, "part_of_edges": n_partof,
             "non_human_terms": len(non_human), "too_generic_terms": too_generic,
             "dictionary_rows": len(rows), "dictionary_texts": len(by_text),
             "dictionary_ambiguous_texts": len(ambiguous), "dictionary_dropped": dict(dropped)}
    print(f"[go_cc] {version}: {len(cc)} CC terms, {n_isa} is_a, {n_partof} part_of, "
          f"{len(non_human)} non-human, dictionary {len(rows)} rows / {len(by_text)} texts "
          f"({len(ambiguous)} ambiguous), dropped {dict(dropped)}; all {len(ADJECTIVES)} adjective IDs verified")
    return stats
