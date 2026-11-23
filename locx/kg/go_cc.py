"""GO cellular component terms from go-basic.obo -> the grounding dictionary (data/interim/go_cc_dictionary.tsv),
the non-human / too-generic sets and counts. The knowledge graph uses the official GO OWL release of the same version
(graph go, locx/kg/releases.py); this module no longer writes a GO graph of its own.
Which terms are too generic or non-human is stated in the locx ontology (section 10) and read from there.
"""
import json
import re
from collections import defaultdict

import obonet

from locx import ontology as O
from locx.config import CFG, INTERIM

# Adjective / short-form map; every ID is verified by its label at build time.
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


def go_id(iri: str) -> str:
    """http://purl.obolibrary.org/obo/GO_0005634 -> GO:0005634"""
    return iri.rsplit("/", 1)[1].replace("_", ":")


def ontology_sets():
    """Non-human compartment roots and too-generic terms, as stated in the locx ontology (section 10)."""
    return [go_id(i) for i in O.annotated("nonHumanCompartmentRoot")], [go_id(i) for i in O.annotated("tooGeneric")]

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
    roots, generic = ontology_sets()
    for g in roots + generic:
        if g not in cc:
            raise SystemExit(f"[go_cc] FAIL: {g} (stated in the locx ontology) is not a current GO CC term")
    non_human = descendants({g: cc[g]["name"] for g in roots}, parents)
    too_generic = {g: cc[g]["name"] for g in generic}

    n_isa = sum(rel == "is_a" for ps in parents.values() for rel, _ in ps)
    n_partof = sum(rel == "part_of" for ps in parents.values() for rel, _ in ps)

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
