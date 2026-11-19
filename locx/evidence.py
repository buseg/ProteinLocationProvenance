"""GO evidence categories as the code sees them, read from the locx ontology (section 9: the GO guide's categories
defined over ECO classes, with our strength rank). No code tables here: a GOA row's category is computed in SPARQL
from its ECO term (queries/verdicts_02_rules.ru); the report and demo use these labels and ranks.
"""
from rdflib.namespace import RDF, RDFS

from locx import ontology as O


def _categories():
    g = O.graph()
    rank = O.expand("locx:evidenceRank")
    out = []
    for v in g.subjects(RDF.type, O.expand("locx:EvidenceCategory")):
        out.append((int(g.value(v, rank)), str(g.value(v, O.LOCX.token)), str(g.value(v, RDFS.label)),
                    str(g.value(v, RDFS.comment)), str(v)))
    if not out:
        raise SystemExit("[evidence] the ontology defines no locx:EvidenceCategory individuals")
    return sorted(out)


_CATS = _categories()
GROUPS = [(key, label, definition) for _, key, label, definition, _ in _CATS]   # strongest first
GROUP_LABEL = {k: label for k, label, _ in GROUPS}
GROUP_HELP = {k: d for k, _, d in GROUPS}
GROUP_IRI = {key: iri for _, key, _, _, iri in _CATS}
RANK = {k: r for r, k, *_ in _CATS}


def strongest(keys) -> str | None:
    """The strongest category among category keys (None if empty)."""
    ks = [k for k in keys if k in RANK]
    return min(ks, key=RANK.get) if ks else None


