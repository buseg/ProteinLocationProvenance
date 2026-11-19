"""Minimal Turtle writing (plain text is much faster than rdflib for ~10^6 triples)."""
PREFIXES = """\
@prefix locx:     <http://example.org/locx/> .
@prefix obo:      <http://purl.obolibrary.org/obo/> .
@prefix uniprot:  <http://purl.uniprot.org/uniprot/> .
@prefix pubmed:   <https://pubmed.ncbi.nlm.nih.gov/> .
@prefix dcterms:  <http://purl.org/dc/terms/> .
@prefix foaf:     <http://xmlns.com/foaf/0.1/> .
@prefix prov:     <http://www.w3.org/ns/prov#> .
@prefix oboInOwl: <http://www.geneontology.org/formats/oboInOwl#> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:      <http://www.w3.org/2002/07/owl#> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

"""
LOCX = "http://example.org/locx/"
# prefix -> namespace for every vocabulary and ID space in the knowledge graph (schema report, demo IRI lookup,
# ontology). Order matters for shortening: more specific namespaces first.
NAMESPACES = {
    "locx": LOCX, "uniprot": "http://purl.uniprot.org/uniprot/", "up": "http://purl.uniprot.org/core/",
    "uplocation": "http://purl.uniprot.org/locations/", "citation": "http://purl.uniprot.org/citations/",
    "geneid": "http://purl.uniprot.org/geneid/", "taxon": "http://purl.uniprot.org/taxonomy/",
    "pubmed": "https://pubmed.ncbi.nlm.nih.gov/", "nlm": "https://www.ncbi.nlm.nih.gov/nlmcatalog/",
    "orcid": "https://orcid.org/", "obo": "http://purl.obolibrary.org/obo/",
    "oboInOwl": "http://www.geneontology.org/formats/oboInOwl#", "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/", "fabio": "http://purl.org/spar/fabio/",
    "frbr": "http://purl.org/vocab/frbr/core#", "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "c4o": "http://purl.org/spar/c4o/", "oa": "http://www.w3.org/ns/oa#", "vann": "http://purl.org/vocab/vann/",
    "foaf": "http://xmlns.com/foaf/0.1/", "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "owl": "http://www.w3.org/2002/07/owl#", "xsd": "http://www.w3.org/2001/XMLSchema#",
}
_ESC = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"})


def lit(s: str) -> str:
    return '"' + str(s).translate(_ESC) + '"'


def go_iri(go_id: str) -> str:
    """GO:0005634 -> obo:GO_0005634"""
    return "obo:" + go_id.replace(":", "_")


def block(subject: str, pairs) -> str:
    """One subject with (predicate, object) pairs; objects must already be Turtle terms."""
    pairs = [(p, o) for p, o in pairs if o is not None]
    return subject + " " + " ;\n    ".join(f"{p} {o}" for p, o in pairs) + " .\n"
