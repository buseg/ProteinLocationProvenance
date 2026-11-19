"""The locx ontology as the code sees it. ontology/locx.owl.ttl is the source of truth (DECISIONS 2026-11-19): the
code takes its vocabulary from there and stops when a term it needs is missing, so a change made in Protégé either
flows through or fails loudly.

    from locx import ontology as O
    O.ttl("Method", "not_stated")      # -> "<http://example.org/locx/MethodNotStated>" (looked up by locx:token)
    O.class_annotation("Claim", "statesRelation")   # -> "http://purl.obolibrary.org/obo/RO_0001025"
    O.term("locx:evidenceSentence")    # -> "locx:evidenceSentence", after checking it is declared
"""
from functools import lru_cache

import rdflib
from rdflib.namespace import OWL, RDF

from locx.config import ROOT
from locx.kg.ttl import NAMESPACES

PATH = ROOT / "ontology" / "locx.owl.ttl"
LOCX = rdflib.Namespace(NAMESPACES["locx"])


class OntologyError(SystemExit):
    pass


@lru_cache(maxsize=1)
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(PATH, format="turtle")
    return g


def expand(qname: str) -> rdflib.URIRef:
    if qname.startswith("http"):
        return rdflib.URIRef(qname)
    p, local = qname.split(":", 1)
    if p not in NAMESPACES:
        raise OntologyError(f"[ontology] unknown prefix in {qname!r}")
    return rdflib.URIRef(NAMESPACES[p] + local)


def declared(qname: str) -> bool:
    return (expand(qname), RDF.type, None) in graph()


def term(qname: str) -> str:
    """Return the prefixed name unchanged after checking that the ontology declares it."""
    if not declared(qname):
        raise OntologyError(f"[ontology] {qname} is not declared in {PATH.name}")
    return qname


def _cls(name: str) -> rdflib.URIRef:
    c = expand(name if ":" in name else "locx:" + name)
    if (c, RDF.type, OWL.Class) not in graph():
        raise OntologyError(f"[ontology] class {name} is not declared in {PATH.name}")
    return c


@lru_cache(maxsize=None)
def values(cls: str) -> dict[str, str]:
    """locx:token -> value IRI for the individuals of a value-set class (e.g. "Method")."""
    c, g, tok = _cls(cls), graph(), LOCX.token
    out = {str(g.value(v, tok)): str(v) for v in g.subjects(RDF.type, c) if g.value(v, tok)}
    if not out:
        raise OntologyError(f"[ontology] value set {cls} has no individuals with locx:token")
    return out


def value(cls: str, token: str) -> str:
    vs = values(cls)
    if token not in vs:
        raise OntologyError(f"[ontology] value set {cls} has no value with locx:token {token!r} "
                            f"(has: {', '.join(sorted(vs))})")
    return vs[token]


def ttl(cls: str, token: str) -> str:
    """Turtle term of a value, for the RDF builders."""
    return f"<{value(cls, token)}>"


def class_annotation(cls: str, prop: str) -> str:
    """The value of an annotation on a class, e.g. locx:statesRelation on locx:Claim."""
    c, p = _cls(cls), expand(prop if ":" in prop else "locx:" + prop)
    v = graph().value(c, p)
    if v is None:
        raise OntologyError(f"[ontology] class {cls} has no {prop} annotation")
    return str(v)


def annotated(prop: str) -> list[str]:
    """Subjects that carry an annotation property with value true (e.g. locx:tooGeneric on GO terms)."""
    p = expand(prop if ":" in prop else "locx:" + prop)
    return sorted(str(s) for s, o in graph().subject_objects(p) if o.toPython() is True)


def version() -> str:
    return str(graph().value(LOCX.ontology, OWL.versionInfo))
