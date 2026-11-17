"""Abstracts graph: the text the LLM read for each paper (PubTator title + abstract), so the demo can show a claim's
sentence inside its full abstract. Kept in its own named graph (urn:locx:graph:abstracts), separate from the papers
graph, so it can be added or dropped without touching anything else.

  python -m locx.kg.abstracts_rdf build   # data/interim/papers.jsonl -> data/rdf/abstracts.ttl
  python -m locx.kg.abstracts_rdf load    # PUT into the abstracts graph (skips if this exact file is loaded)
"""
import argparse

from locx.config import CFG, INTERIM, RDF
from locx.io import read_jsonl
from locx.kg import fuseki
from locx.kg.ttl import PREFIXES, lit

PATH = RDF / "abstracts.ttl"


def build():
    n = skipped = 0
    with open(PATH, "w") as f:
        f.write(PREFIXES)
        for p in read_jsonl(INTERIM / "papers.jsonl"):
            if not p.get("text"):
                skipped += 1
                continue
            f.write(f"pubmed:{p['pmid']} dcterms:abstract {lit(p['text'])} .\n")
            n += 1
    print(f"[abstracts] {n} papers with text, {skipped} without -> {PATH} ({PATH.stat().st_size / 1e6:.0f} MB)")


def load():
    g = CFG["graphs"]["abstracts"]
    n = fuseki.load(g, PATH)
    print(f"[abstracts] {g}: {n} triples")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "load"])
    {"build": build, "load": load}[ap.parse_args().step]()
