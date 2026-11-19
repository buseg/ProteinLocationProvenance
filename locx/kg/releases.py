"""The official ontology releases we load unmodified (one named graph each) and what the builders read from them.

    go                 go-basic.owl, release 2026-07-26 (the release the grounding dictionary go-basic.obo comes from)
    eco                eco.owl, release 2026-07-10
    ro                 ro.owl, release 2026-09-04
    uniprot-locations  UniProt's subcellular location vocabulary (rest.uniprot.org/locations, RDF as published)
    uniprot-core       UniProt's core ontology (the up: vocabulary, core.owl as published)

Nothing here is a hand-written table: GAF evidence codes are mapped with ECO's own "has GO evidence code"
annotation (the one marked Default), GAF relation names with RO's own labels.
"""
from functools import lru_cache

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

from locx.config import RAW
from locx.io import download

OBO = "http://purl.obolibrary.org/obo/"
FILES = {   # graph key -> (local file, download URL, RDF format)
    "go": (RAW / "obo" / "go-basic_2026-07-26.owl",
           "https://release.geneontology.org/2026-08-05/ontology/go-basic.owl", "application/rdf+xml"),
    "eco": (RAW / "obo" / "eco_2026-07-10.owl", "http://purl.obolibrary.org/obo/eco/releases/2026-07-10/eco.owl",
            "application/rdf+xml"),
    "ro": (RAW / "obo" / "ro_2026-09-04.owl", "http://purl.obolibrary.org/obo/ro/releases/2026-09-04/ro.owl",
           "application/rdf+xml"),
    "uniprot_core": (RAW / "uniprot_core" / "core.owl",
                     "https://ftp.uniprot.org/pub/databases/uniprot/current_release/rdf/core.owl", "application/rdf+xml"),
    "uniprot_locations": (RAW / "uniprot_locations" / "locations.rdf",
                          "https://rest.uniprot.org/locations/stream?query=*&format=rdf", "application/rdf+xml"),
}
HAS_GO_CODE = rdflib.URIRef(OBO + "ECO_9000002")   # ECO annotation property "has GO evidence code"


def path(key: str):
    local, url, _ = FILES[key]
    return download(url, local)


@lru_cache(maxsize=None)
def parsed(key: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(path(key), format="xml")
    return g


def version_iri(key: str) -> str | None:
    g = parsed(key)
    ont = next(g.subjects(RDF.type, OWL.Ontology), None)
    v = g.value(ont, OWL.versionIRI) if ont is not None else None
    return str(v) if v else None


@lru_cache(maxsize=1)
def eco_for_go_codes() -> dict[str, str]:
    """GO evidence code -> ECO term IRI: ECO's own default mapping (the 'has GO evidence code' annotation whose axiom
    is annotated 'Default')."""
    g, out = parsed("eco"), {}
    for ax in g.subjects(OWL.annotatedProperty, HAS_GO_CODE):
        if any(str(c) == "Default" for c in g.objects(ax, RDFS.comment)):
            code, term = str(g.value(ax, OWL.annotatedTarget)), str(g.value(ax, OWL.annotatedSource))
            if code in out and out[code] != term:
                raise SystemExit(f"[releases] ECO has two default terms for GO code {code}: {out[code]}, {term}")
            out[code] = term
    if not out:
        raise SystemExit("[releases] no default GO-code mapping found in ECO")
    return out


@lru_cache(maxsize=1)
def ro_by_label() -> dict[str, str]:
    """RO relation name -> IRI (object properties of the RO release, including the BFO relations it ships): labels
    first, then RO's exact synonyms (e.g. 'exists during' for RO:0002491)."""
    g = parsed("ro")
    exact = rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym")
    props = list(g.subjects(RDF.type, OWL.ObjectProperty))
    out = {str(s): str(p) for p in props for s in g.objects(p, exact)}
    out.update({str(lab): str(p) for p in props for lab in g.objects(p, RDFS.label)})
    return out


def ro_relation(gaf_name: str) -> str:
    """GAF relation name (located_in, part_of, occurs_in ...) -> RO IRI, via RO's label ('located in')."""
    label = gaf_name.replace("_", " ")
    rel = ro_by_label().get(label)
    if not rel:
        raise SystemExit(f"[releases] no RO relation labelled {label!r} (GAF {gaf_name!r})")
    return rel


# GO Consortium metadata (go-site/metadata): the official RDF prefix of every ID space (db-xrefs.yaml) and the IRIs
# of the groups that make annotations (groups.yaml). Used for GOA references, annotation-extension terms, assignedBy.
GO_METADATA = "https://raw.githubusercontent.com/geneontology/go-site/master/metadata/"


@lru_cache(maxsize=1)
def go_prefixes() -> dict[str, str]:
    """ID space (and its synonyms) -> RDF IRI prefix, e.g. GO_REF -> http://purl.obolibrary.org/obo/go/references/."""
    import yaml
    out = {}
    for d in yaml.safe_load(open(download(GO_METADATA + "db-xrefs.yaml", RAW / "go_metadata" / "db-xrefs.yaml"))):
        if d.get("rdf_uri_prefix"):
            for name in [d["database"]] + list(d.get("synonyms") or []):
                out.setdefault(name, d["rdf_uri_prefix"])
    out.setdefault("DOI", "https://doi.org/")   # the DOI resolver (db-xrefs.yaml has no RDF prefix for DOI)
    return out


def go_curie_iri(curie: str) -> str | None:
    """CL:0000059 -> http://purl.obolibrary.org/obo/CL_0000059 (None if the ID space has no official prefix)."""
    space, local = curie.split(":", 1)
    prefix = go_prefixes().get(space)
    return prefix + local if prefix else None


@lru_cache(maxsize=1)
def go_groups() -> dict[str, str]:
    """Annotation group (GAF column 15 shorthand or label) -> its IRI from groups.yaml."""
    import yaml
    out = {}
    for g in yaml.safe_load(open(download(GO_METADATA + "groups.yaml", RAW / "go_metadata" / "groups.yaml"))):
        for k in ("shorthand", "label"):
            if g.get(k) and g.get("id"):
                out.setdefault(g[k], g["id"])
    return out


def go_cc_module():
    """data/rdf/go_cc_module.nt: the cellular-component part of the official GO release, triples unchanged (every
    triple whose subject is a CC term, plus the part_of restrictions under them). Only for the local SHACL checks,
    which run in many worker processes and cannot each parse the full 118 MB GO; Fuseki holds the full release."""
    from locx.config import RDF as RDF_DIR
    out = RDF_DIR / "go_cc_module.nt"
    if out.exists() and out.stat().st_mtime > path("go").stat().st_mtime:
        return out
    g = parsed("go")
    ns = rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#hasOBONamespace")
    cc = {s for s in g.subjects(ns, rdflib.Literal("cellular_component"))}
    m = rdflib.Graph()
    for s in cc:
        for p, o in g.predicate_objects(s):
            m.add((s, p, o))
            if isinstance(o, rdflib.BNode):
                for p2, o2 in g.predicate_objects(o):
                    m.add((o, p2, o2))
    m.serialize(out, format="nt")
    print(f"[releases] GO CC module: {len(cc)} terms, {len(m)} triples -> {out.name}")
    return out
