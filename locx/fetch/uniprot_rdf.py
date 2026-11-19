"""UniProt RDF for the human Swiss-Prot entries, from UniProt's SPARQL endpoint (sparql.uniprot.org).

We need under 3% of each UniProt entry: names, gene, NCBI GeneID link, the subcellular location annotation with
its evidence (ECO code + cited papers), and the UniProt location terms it points to. Instead of streaming the full
RDF (~3.5 GB), one CONSTRUCT per batch of accessions returns exactly those triples in UniProt's own vocabulary
(up: = http://purl.uniprot.org/core/). One simple query per part (queries/uniprot_<part>.rq): the endpoint answers
each in about a second, while a UNION of them times out. Responses are cached as N-Triples under
data/raw/uniprot_rdf/ and never fetched twice.
"""
import hashlib
import json
import re
import time

import requests

from locx.config import QUERIES, RAW
from locx.fetch import uniprot

ENDPOINT = "https://sparql.uniprot.org/sparql"
CACHE = RAW / "uniprot_rdf"
BATCH = 500
PARTS = ("core", "recname", "altname", "gene", "geneid", "loccomment", "locterms", "locevidence")
PAUSE = 1.0


def construct(query: str, dest, retries: int = 4) -> str:
    """Run a CONSTRUCT once; the N-Triples response is cached in `dest`."""
    if dest.exists():
        return dest.read_text()
    for attempt in range(retries + 1):
        try:
            r = requests.post(ENDPOINT, data={"query": query}, headers={"Accept": "application/n-triples"},
                              timeout=600)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.ConnectionError(f"HTTP {r.status_code}")
            r.raise_for_status()
            break
        except requests.ConnectionError as e:
            if attempt == retries:
                raise
            wait = 10 * 2 ** attempt
            print(f"[uniprot-rdf] {e}; waiting {wait} s")
            time.sleep(wait)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_text(r.text)
    part.rename(dest)
    time.sleep(PAUSE)
    return r.text


def accessions() -> list[str]:
    """The accessions in the cached human Swiss-Prot TSV (the same proteins the pipeline grounds to)."""
    import csv
    import gzip
    with gzip.open(uniprot.fetch(), "rt", newline="") as f:
        return sorted(r["Entry"] for r in csv.DictReader(f, delimiter="\t"))


def fetch() -> dict:
    """Per batch and part: <part>_NNN_<hash>.nt; terms_<hash>.nt (the UniProt location terms used); types_NNNN_<hash>.nt
    (the rdf:type UniProt gives the name, GeneID, citation, attribution and located-in nodes we point to).
    Writes data/raw/uniprot_rdf/fetch.json (files, counts, accessions UniProt no longer has)."""
    accs = accessions()
    files, t = [], time.time()
    tmpl = {k: (QUERIES / f"uniprot_{k}.rq").read_text() for k in PARTS + ("terms",)}
    for i in range(0, len(accs), BATCH):
        chunk = accs[i:i + BATCH]
        values = " ".join(f"<http://purl.uniprot.org/uniprot/{a}>" for a in chunk)
        key = hashlib.sha1(",".join(chunk).encode()).hexdigest()[:12]
        for kind in PARTS:
            dest = CACHE / f"{kind}_{i // BATCH:03d}_{key}.nt"
            construct(tmpl[kind].replace("%PROTEINS%", values), dest)
            files.append(dest)
        if (i // BATCH) % 5 == 4:
            print(f"[uniprot-rdf] {min(i + BATCH, len(accs))}/{len(accs)} proteins ({time.time() - t:.0f} s)")
    # location terms used as component, topology or orientation
    loc = re.compile(r"<(http://purl\.uniprot\.org/locations/\d+)>")
    terms = sorted({m for f in files if f.name.startswith("loc") for m in loc.findall(f.read_text())},
                   key=lambda x: int(x.rsplit("/", 1)[1]))
    key = hashlib.sha1(",".join(terms).encode()).hexdigest()[:12]
    dest = CACHE / f"terms_{key}.nt"
    construct(tmpl["terms"].replace("%TERMS%", " ".join(f"<{x}>" for x in terms)), dest)
    files.append(dest)
    # the types UniProt gives the nodes we point to (names, GeneID links, citations, attributions, located-in nodes)
    pointer = re.compile(r"<http://purl\.uniprot\.org/core/(?:recommendedName|alternativeName|source|attribution|locatedIn)> "
                         r"<([^>]+)>|<http://www\.w3\.org/2000/01/rdf-schema#seeAlso> <([^>]+)>")
    nodes = sorted({a or b for f in files if not f.name.startswith("terms_") for a, b in pointer.findall(f.read_text())})
    ttmpl = (QUERIES / "uniprot_types.rq").read_text()
    for i in range(0, len(nodes), 1000):
        chunk = nodes[i:i + 1000]
        dest = CACHE / f"types_{i // 1000:04d}_{hashlib.sha1(','.join(chunk).encode()).hexdigest()[:12]}.nt"
        construct(ttmpl.replace("%NODES%", " ".join(f"<{x}>" for x in chunk)), dest)
        files.append(dest)
    print(f"[uniprot-rdf] types of {len(nodes)} referenced nodes ({time.time() - t:.0f} s)")
    found = set()
    for f in files:
        if f.name.startswith("core_"):
            found |= set(re.findall(r"^<http://purl\.uniprot\.org/uniprot/(\w+)> "
                                    r"<http://www\.w3\.org/1999/02/22-rdf-syntax-ns#type> "
                                    r"<http://purl\.uniprot\.org/core/Protein>", f.read_text(), re.M))
    out = {"accessions": len(accs), "proteins_found": len(found), "missing": sorted(set(accs) - found),
           "location_terms": len(terms), "files": [f.name for f in files]}
    (CACHE / "fetch.json").write_text(json.dumps(out, indent=1))
    print(f"[uniprot-rdf] {len(found)}/{len(accs)} proteins, {len(terms)} location terms, "
          f"{len(out['missing'])} missing ({time.time() - t:.0f} s)")
    return out


if __name__ == "__main__":
    fetch()
