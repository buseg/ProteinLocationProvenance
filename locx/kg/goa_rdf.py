"""GOA human CC annotations -> Turtle (graph goa-human). The input is a GAF file (Gene Association File: the GO
Consortium's tab-separated annotation format, one annotation per line). One locx:CuratedAnnotation per line,
IRI = locx:goa/<sha1 of the line, 12 chars>; a CuratedAnnotation is a LocalizationStatement like a Claim.

Every value is an IRI from its source, never a string table of ours:
  location       an individual typed with the GO class (locx:goa/<id>/location a obo:GO_...), no punning
  relation       GAF qualifier (column 4) -> RO relation, by RO's own label     (locx/kg/releases.py)
  polarity       NOT in column 4 -> the ontology's absent value, else present   (locx/ontology.py)
  evidence       an individual typed with the ECO class of the GAF code (column 7), by ECO's own default mapping
  source         PMID references -> PubMed IRIs; other references (GO_REF, Reactome) -> locx:reference IRIs with
                 GO's official prefixes (db-xrefs.yaml)
  assignedBy     the group's IRI from GO's groups.yaml; a group not listed there keeps only its name
  contexts       the annotation extension column parsed: alternatives (|) -> locx:GOAContext, parts (,) -> relation (RO) + term
"""
import hashlib
import re
from collections import Counter

from locx import ontology as O
from locx.config import RDF
from locx.fetch import goa
from locx.kg import releases as R
from locx.kg.ttl import LOCX, PREFIXES, block, go_iri, lit

PART = re.compile(r"(\w+)\(([^()]+)\)")


def contexts(text, node, c):
    """The annotation extension column (GAF column 16) -> (pairs for the row, extra Turtle blocks): one locx:GOAContext
    per alternative, one locx:ContextPart (relation + term) per conjunctive part."""
    pairs, blocks = [], []
    for i, alt in enumerate(x for x in text.split("|") if x.strip()):
        ext = f"<{LOCX}goa/{node}/context{i + 1}>"
        parts = []
        for j, part in enumerate(p.strip() for p in alt.split(",")):
            m = PART.fullmatch(part)
            term = R.go_curie_iri(m.group(2)) if m else None
            if not m or not term:
                c["context_parts_unparsed"] += 1
                continue
            ep = f"<{LOCX}goa/{node}/context{i + 1}/{j + 1}>"
            blocks.append(block(ep, [("a", "locx:ContextPart"),
                                     ("locx:contextRelation", f"<{R.ro_relation(m.group(1))}>"),
                                     ("locx:contextTerm", f"<{term}>")]))
            parts.append(ep)
            c["context_parts"] += 1
        if parts:
            blocks.append(block(ext, [("a", "locx:GOAContext")] + [("locx:contextPart", p) for p in parts]))
            pairs.append(("locx:hasContext", ext))
    return pairs, blocks


def build(gaf_path, cc_terms):
    out = RDF / "goa_human_cc.ttl"
    for t in ("locx:CuratedAnnotation", "locx:relation", "locx:polarity", "locx:evidence", "locx:reference",
              "locx:assignedBy", "locx:hasContext", "locx:GOAContext", "locx:ContextPart"):
        O.term(t)
    present, absent = O.ttl("Polarity", "present"), O.ttl("Polarity", "absent")
    eco, groups = R.eco_for_go_codes(), R.go_groups()
    c = Counter()
    proteins, pmids, nodes, unnamed, used = set(), set(), set(), {}, {}
    generated = next((h.split(": ", 1)[1] for h in goa.header(gaf_path) if h.startswith("date-generated:")), None)
    with open(out, "w") as f:
        f.write(PREFIXES)
        # the GAF file itself, so that the verdict activity can say which GOA release it used
        f.write(block(f"<{LOCX}dataset/goa-human>", [
            ("a", "prov:Entity"), ("rdfs:label", lit("GOA human annotation file, cellular component rows")),
            ("dcterms:date", f'"{generated}:00"^^xsd:dateTime' if generated else None),
            ("dcterms:source", f"<{goa.URL}>")]))
        for line, r in goa.rows(gaf_path):
            c["rows"] += 1
            if r["db"] != "UniProtKB":
                c["dropped_not_uniprotkb"] += 1
                continue
            node = hashlib.sha1(line.encode()).hexdigest()[:12]
            if node in nodes:
                c["dropped_duplicate_line"] += 1
                continue
            nodes.add(node)
            quals = r["qualifier"].split("|")
            negated = "NOT" in quals
            qualifier = next((q for q in quals if q != "NOT"), "")
            c["not_rows"] += negated
            c[f"qualifier:{qualifier}"] += 1
            if r["evidence"] not in eco:
                raise SystemExit(f"[goa] GO evidence code {r['evidence']!r} has no default ECO term in ECO")
            if r["go_id"] not in cc_terms:
                c["go_id_not_in_cc_graph"] += 1
            refs = [x for x in r["refs"].split("|") if x]
            row_pmids = [x[5:] for x in refs if x.startswith("PMID:")]
            other = [R.go_curie_iri(x) for x in refs if not x.startswith("PMID:")]
            c["references_without_prefix"] += sum(x is None for x in other)
            pmids.update(row_pmids)
            proteins.add(r["acc"])
            group = groups.get(r["assigned_by"])
            if group:
                assigned = f"<{group}>"
            else:   # not in GO's groups.yaml: keep the name, invent no IRI
                assigned = unnamed.setdefault(r["assigned_by"], f"<{LOCX}group/{len(unnamed) + 1}>")
                c["rows_assigned_by_unlisted_group"] += 1
            used.setdefault(r["assigned_by"], assigned)
            d = r["date"]
            loc, evi = f"<{LOCX}goa/{node}/location>", f"<{LOCX}goa/{node}/evidence>"
            f.write(block(loc, [("a", go_iri(r["go_id"]))]))          # "a nucleus": typed with the GO class
            f.write(block(evi, [("a", f"<{eco[r['evidence']]}>")]))   # "a direct assay evidence": typed with ECO
            pairs = [("a", "locx:CuratedAnnotation"),
                     ("locx:protein", f"uniprot:{r['acc']}"),
                     ("locx:relation", f"<{R.ro_relation(qualifier)}>"),
                     ("locx:location", loc),
                     ("locx:polarity", absent if negated else present),
                     ("locx:evidence", evi),
                     ("locx:assignedBy", assigned),
                     ("dcterms:date", f'"{d[:4]}-{d[4:6]}-{d[6:8]}"^^xsd:date' if len(d) == 8 else None)]
            pairs += [("dcterms:source", f"pubmed:{p}") for p in row_pmids]
            pairs += [("locx:reference", f"<{x}>") for x in other if x]
            ext_pairs, ext_blocks = contexts(r["extension"], node, c) if r["extension"] else ([], [])
            f.write(block(f"<{LOCX}goa/{node}>", pairs + ext_pairs))
            f.writelines(ext_blocks)
        for name, iri in sorted(used.items()):   # every assigning group as an organisation with its GAF name
            f.write(block(iri, [("a", "foaf:Organization"), ("foaf:name", lit(name))]))
    stats = {"gaf_header": goa.header(gaf_path)[:12], "cc_rows": c["rows"], "nodes": len(nodes),
             "not_rows": c["not_rows"], "proteins": len(proteins), "distinct_pmids": len(pmids),
             "qualifiers": {k[10:]: v for k, v in c.items() if k.startswith("qualifier:")},
             "dropped_not_uniprotkb": c["dropped_not_uniprotkb"],
             "dropped_duplicate_line": c["dropped_duplicate_line"],
             "go_id_not_in_cc_graph": c["go_id_not_in_cc_graph"],
             "context_parts": c["context_parts"], "context_parts_unparsed": c["context_parts_unparsed"],
             "references_without_prefix": c["references_without_prefix"],
             "rows_assigned_by_unlisted_group": c["rows_assigned_by_unlisted_group"], "unlisted_groups": sorted(unnamed),
             "eco_release": R.version_iri("eco"), "ro_release": R.version_iri("ro")}
    print(f"[goa] {c['rows']} CC rows -> {len(nodes)} nodes ({c['not_rows']} NOT), {len(proteins)} proteins, "
          f"{len(pmids)} PMIDs; {c['context_parts']} GOA context parts ({c['context_parts_unparsed']} unparsed); "
          f"groups not in GO's list: {sorted(unnamed)} ({c['rows_assigned_by_unlisted_group']} rows)")
    return stats
