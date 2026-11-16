"""GOA human CC annotations -> Turtle. One node per GAF row, IRI = locx:goa/<sha1 of the line, 12 chars>."""
import hashlib
from collections import Counter

from locx.config import RDF
from locx.fetch import goa
from locx.kg.ttl import LOCX, PREFIXES, block, go_iri, lit


def build(gaf_path, cc_terms):
    out = RDF / "goa_human_cc.ttl"
    c = Counter()
    proteins, pmids, nodes = set(), set(), set()
    with open(out, "w") as f:
        f.write(PREFIXES)
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
            if r["go_id"] not in cc_terms:
                c["go_id_not_in_cc_graph"] += 1
            refs = [x for x in r["refs"].split("|") if x]
            row_pmids = [x[5:] for x in refs if x.startswith("PMID:")]
            pmids.update(row_pmids)
            proteins.add(r["acc"])
            d = r["date"]
            pairs = [("a", "locx:CuratedAnnotation"),
                     ("locx:protein", f"uniprot:{r['acc']}"),
                     ("locx:location", go_iri(r["go_id"])),
                     ("locx:qualifier", lit(qualifier)),
                     ("locx:negated", "true" if negated else "false"),
                     ("locx:evidenceCode", lit(r["evidence"])),
                     ("locx:assignedBy", lit(r["assigned_by"])),
                     ("dcterms:date", f'"{d[:4]}-{d[4:6]}-{d[6:8]}"^^xsd:date' if len(d) == 8 else None)]
            pairs += [("dcterms:source", f"pubmed:{p}") for p in row_pmids]
            pairs += [("locx:reference", lit(x)) for x in refs if not x.startswith("PMID:")]
            if r["extension"]:
                pairs.append(("locx:annotationExtension", lit(r["extension"])))
            f.write(block(f"<{LOCX}goa/{node}>", pairs))
    stats = {"gaf_header": goa.header(gaf_path)[:12], "cc_rows": c["rows"], "nodes": len(nodes),
             "not_rows": c["not_rows"], "proteins": len(proteins), "distinct_pmids": len(pmids),
             "qualifiers": {k[10:]: v for k, v in c.items() if k.startswith("qualifier:")},
             "dropped_not_uniprotkb": c["dropped_not_uniprotkb"],
             "dropped_duplicate_line": c["dropped_duplicate_line"],
             "go_id_not_in_cc_graph": c["go_id_not_in_cc_graph"]}
    print(f"[goa] {c['rows']} CC rows -> {len(nodes)} nodes ({c['not_rows']} NOT), {len(proteins)} proteins, "
          f"{len(pmids)} PMIDs; dropped: {c['dropped_not_uniprotkb']} not UniProtKB, "
          f"{c['dropped_duplicate_line']} duplicate lines; {c['go_id_not_in_cc_graph']} rows with GO ID not in CC graph")
    return stats
