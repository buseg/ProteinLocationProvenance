"""Minimal Turtle writing (plain text is much faster than rdflib for ~10^6 triples)."""
PREFIXES = """\
@prefix locx:     <http://example.org/locx/> .
@prefix obo:      <http://purl.obolibrary.org/obo/> .
@prefix uniprot:  <http://purl.uniprot.org/uniprot/> .
@prefix pubmed:   <https://pubmed.ncbi.nlm.nih.gov/> .
@prefix dcterms:  <http://purl.org/dc/terms/> .
@prefix oboInOwl: <http://www.geneontology.org/formats/oboInOwl#> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:      <http://www.w3.org/2002/07/owl#> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

"""
LOCX = "http://example.org/locx/"
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
