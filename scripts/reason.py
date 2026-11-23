"""make reason: OWL 2 RL reasoning over the locx ontology + our data graphs.

The OWL 2 RL rules the ontology relies on run as SPARQL updates inside Fuseki (queries/reason_rules.ru), once per
data graph, writing every inferred triple to urn:locx:graph:inferred (asserted facts are never changed):
  prp-spo1  sub-properties (locx:evidenceSentence -> oa:hasTarget)
  prp-dom   types from property domains (named classes)
  prp-rng   types from object-property ranges (named classes)
  cax-sco   superclass types: locx ontology (a claim is a LocalizationStatement and a prov:Entity), GO (a nucleus
            location is also an organelle, a cellular component ...), ECO (an IDA evidence is experimental evidence)
  prp-ifp   owl:sameAs between persons that share an ORCID (locx:orcid is inverse functional)
Then the OWL 2 RL inconsistency rules are checked over asserted + inferred facts (queries/reason_*.rq): an individual
in two disjoint classes, owl:sameAs between individuals declared different, two values of a functional datatype
property. Any violation stops the build. -> reports/reasoning.json

Why SPARQL and not an in-memory reasoner: `reasonable` (OWL 2 RL, Rust) needed about 586 GB for a one-million-triple
slice of the papers graph and was stopped by the system; Fuseki evaluates the same rules on disk.

  python scripts/reason.py [--graphs papers,run,...] [--append]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx import ontology as O  # noqa: E402
from locx.config import CFG, QUERIES, REPORTS  # noqa: E402
from locx.kg import fuseki  # noqa: E402

G = CFG["graphs"]
RUN_GRAPH = G["run_prefix"] + CFG["extract"]["main_run"]
DATA_GRAPHS = {"papers": G["papers"], "run": RUN_GRAPH, "assertions": G["assertions"], "goa": G["goa"],
               "uniprot": G["uniprot"], "support": G["support"], "verdicts": G["verdicts"]}
INFERRED = G["inferred"]


def rule_blocks() -> list[tuple[str, str]]:
    """(name, SPARQL update) for every '#-- name ...' block of queries/reason_rules.ru, with the PREFIX header."""
    text = (QUERIES / "reason_rules.ru").read_text()
    prefixes = "".join(line + "\n" for line in text.splitlines() if line.startswith("PREFIX "))
    blocks = []
    for part in re.split(r"\n(?=#-- )", text)[1:]:
        first = part.split("\n", 1)[0][4:]
        name = first.split(":", 1)[0].strip()
        name = name.replace(" ontology)", ")").replace("(locx ontology", "(locx")
        body = "\n".join(line for line in part.splitlines() if not line.startswith("#"))
        blocks.append((name, prefixes + body))
    return blocks


def checks() -> dict:
    """OWL 2 RL inconsistency rules in SPARQL over all asserted + inferred data (queries/reason_*.rq)."""
    out = {}
    for p in sorted(QUERIES.glob("reason_*.rq")):
        rows = fuseki.select(p.read_text().replace("%RUN_GRAPH%", RUN_GRAPH))
        out[p.stem] = {"violations": len(rows), "examples": rows[:5]}
        print(f"[reason] check {p.stem}: {len(rows)} violations", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphs", default=",".join(DATA_GRAPHS))
    ap.add_argument("--append", action="store_true",
                    help="add to the inferred graph instead of rebuilding it (e.g. --graphs support,verdicts)")
    a = ap.parse_args()
    t0 = time.time()
    if not a.append:
        fuseki.update(f"DROP SILENT GRAPH <{INFERRED}>")
    blocks = rule_blocks()
    per_graph = {}
    for name in a.graphs.split(","):
        g = DATA_GRAPHS[name]
        if not fuseki.count(g):
            print(f"[reason] {name}: graph empty, skipped")
            continue
        before, stats = fuseki.count(INFERRED), {}
        for rule, update in blocks:
            t = time.time()
            n0 = fuseki.count(INFERRED)
            fuseki.update(update.replace("%GRAPH%", g))
            stats[rule] = {"new": fuseki.count(INFERRED) - n0, "seconds": round(time.time() - t)}
        per_graph[name] = {"inferred": fuseki.count(INFERRED) - before, "rules": stats}
        print(f"[reason] {name}: {per_graph[name]['inferred']:,} inferred ("
              + ", ".join(f"{r} {v['new']:,}" for r, v in stats.items()) + ")", flush=True)
    # superclasses of the types inferred from domains and ranges
    sco = next(u for r, u in blocks if r == "cax-sco (locx)")
    n0 = fuseki.count(INFERRED)
    fuseki.update(sco.replace("%GRAPH%", INFERRED))
    print(f"[reason] cax-sco over inferred types: {fuseki.count(INFERRED) - n0:,} more", flush=True)
    n = fuseki.count(INFERRED)
    if a.append and (REPORTS / "reasoning.json").exists():
        per_graph = {**json.loads((REPORTS / "reasoning.json").read_text()).get("per_graph", {}), **per_graph}
    man = json.loads(fuseki.MANIFEST.read_text()) if fuseki.MANIFEST.exists() else {}
    man[INFERRED] = {"file": "(SPARQL UPDATE, queries/reason_rules.ru)", "sha256": None, "triples": n,
                     "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    fuseki.MANIFEST.write_text(json.dumps(man, indent=1))
    result = {"reasoner": "OWL 2 RL rules as SPARQL updates in Fuseki (prp-spo1, prp-dom, prp-rng, cax-sco, prp-ifp)",
              "tbox": "locx ontology + UniProt core + official GO + official ECO", "ontology": O.version(), "per_graph": per_graph,
              "inferred_graph_triples": n, "consistency": checks(), "seconds": round(time.time() - t0)}
    result["consistent"] = all(c["violations"] == 0 for c in result["consistency"].values())
    (REPORTS / "reasoning.json").write_text(json.dumps(result, indent=1))
    print(f"[reason] {n:,} triples in {INFERRED}; consistent: {result['consistent']} -> reports/reasoning.json")
    if not result["consistent"]:
        sys.exit("[reason] the data contradicts the ontology; see reports/reasoning.json")


if __name__ == "__main__":
    main()
