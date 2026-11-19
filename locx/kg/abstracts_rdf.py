"""Abstracts graph: the text the LLM read for each paper (PubTator title + abstract) as its own entity,
locx:abstract/<PMID> a fabio:Abstract, frbr:partOf the paper, text in c4o:hasContent. A claim's evidence sentence is a
W3C Web Annotation span of this abstract (character offsets into exactly this text). Kept in its own named graph
(urn:locx:graph:abstracts), separate from the papers graph, so it can be added or dropped without touching anything else.

  python -m locx.kg.abstracts_rdf build   # data/interim/papers.jsonl -> data/rdf/abstracts.ttl
  python -m locx.kg.abstracts_rdf load    # PUT into the abstracts graph (skips if this exact file is loaded)
"""
import argparse

from locx.config import CFG, INTERIM, RDF
from locx.io import read_jsonl
from locx.kg import fuseki
from locx import ontology as O
from locx.kg.ttl import LOCX, PREFIXES, lit

PATH = RDF / "abstracts.ttl"


def build():
    for t in ("fabio:Abstract", "c4o:hasContent", "frbr:partOf"):
        O.term(t)
    n = skipped = 0
    with open(PATH, "w") as f:
        f.write(PREFIXES + "@prefix fabio: <http://purl.org/spar/fabio/> .\n@prefix frbr: <http://purl.org/vocab/frbr/core#> .\n"
                "@prefix c4o: <http://purl.org/spar/c4o/> .\n\n")
        for p in read_jsonl(INTERIM / "papers.jsonl"):
            if not p.get("text"):
                skipped += 1
                continue
            f.write(f"<{LOCX}abstract/{p['pmid']}> a fabio:Abstract ; frbr:partOf pubmed:{p['pmid']} ;\n"
                    f"    c4o:hasContent {lit(p['text'])} .\n")
            n += 1
    print(f"[abstracts] {n} papers with text, {skipped} without -> {PATH} ({PATH.stat().st_size / 1e6:.0f} MB)")


def load():
    g = CFG["graphs"]["abstracts"]
    n = fuseki.load(g, PATH, replace=True)   # the abstracts graph holds only this file
    print(f"[abstracts] {g}: {n} triples")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "load"])
    {"build": build, "load": load}[ap.parse_args().step]()
