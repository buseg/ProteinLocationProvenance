"""UniProt human graph: the UniProt RDF fetched by locx/fetch/uniprot_rdf.py, in UniProt's own vocabulary (up:).

Per protein: up:Protein, up:mnemonic (entry name), up:recommendedName / up:alternativeName -> up:fullName,
up:encodedBy -> up:Gene with skos:prefLabel (symbol) / skos:altLabel (synonyms), rdfs:seeAlso -> NCBI GeneID,
and the subcellular location annotation (free-text rdfs:comment, up:locatedIn -> UniProt location terms, the ECO
evidence and cited papers behind each term). The location terms themselves are UniProt's published vocabulary,
loaded unchanged as graph uniprot-locations. N-Triples is valid Turtle, so the cached responses are concatenated as they are.
"""
import re
from collections import Counter

from locx.config import RDF
from locx.fetch import uniprot_rdf

TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
PROTEIN = "<http://purl.uniprot.org/core/Protein>"


def build() -> dict:
    info = uniprot_rdf.fetch()   # cached: no requests when all files exist
    out, types = RDF / "uniprot_human.nt", RDF / "uniprot_proteins.ttl"
    c, seen = Counter(), set()
    with open(out, "w") as f, open(types, "w") as ft:
        for name in info["files"]:
            if name.startswith("terms_"):
                continue   # the location vocabulary is graph uniprot-locations (UniProt's published file)
            for line in (uniprot_rdf.CACHE / name).read_text().splitlines():
                if not line.strip() or line in seen:
                    continue
                seen.add(line)
                f.write(line + "\n")
                c["triples"] += 1
                s, p, o = line.split(" ", 2)
                if p == TYPE and o.startswith(PROTEIN):
                    ft.write(line + "\n")   # protein types only: the SHACL gate's class check
                    c["proteins"] += 1
                elif p == "<http://purl.uniprot.org/core/encodedBy>":
                    c["encodedBy"] += 1
                elif p == "<http://www.w3.org/2000/01/rdf-schema#seeAlso>":
                    c["geneid_links"] += 1
                elif p == "<http://purl.uniprot.org/core/annotation>":
                    c["location_annotations"] += 1
                elif p == "<http://purl.uniprot.org/core/cellularComponent>" and s.startswith("<http://purl.uniprot.org/uniprot/"):
                    c["location_terms_used"] += 1
                elif p == "<http://purl.uniprot.org/core/evidence>":
                    c["location_evidence"] += 1
    seen.clear()
    with_ann = len({line.split(" ", 1)[0] for line in open(out) if " <http://purl.uniprot.org/core/annotation> " in line})
    stats = {"proteins": info["proteins_found"], "other_uniprot_entries_cited_as_evidence": c["proteins"] - info["proteins_found"],
             "missing_from_uniprot": info["missing"], "triples": c["triples"],
             "gene_links": c["encodedBy"], "geneid_links": c["geneid_links"],
             "proteins_with_location_annotation": with_ann, "location_term_links": c["location_terms_used"],
             "location_evidence_links": c["location_evidence"], "uniprot_location_terms": info["location_terms"]}
    print(f"[uniprot] {stats['proteins']} human Swiss-Prot proteins ({len(info['missing'])} no longer in UniProt; "
          f"{stats['other_uniprot_entries_cited_as_evidence']} other UniProt entries cited as evidence), "
          f"{with_ann} with a subcellular location annotation, {c['triples']} triples -> {out.name}")
    return stats
