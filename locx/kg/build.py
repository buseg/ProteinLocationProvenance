"""M2: download GO / GOA / UniProt, build Turtle, load the reference graphs, sanity-check, write stats.

Usage: python -m locx.kg.build [--force] [--replace]
  --force    rebuild Turtle files even if they exist
  --replace  allow overwriting a named graph that holds different content
"""
import argparse
import json

from locx.config import CFG, QUERIES, RDF, REPORTS
from locx.fetch import go, goa, uniprot
from locx.kg import fuseki, go_cc, goa_rdf, uniprot_rdf

STATS = RDF / "build_stats.json"


def sanity():
    def q(name):
        return (QUERIES / name).read_text()
    checks = []
    label = fuseki.select(q("m2_sanity_nucleus_label.rq"))
    checks.append(("GO:0005634 label is 'nucleus'", [r["label"] for r in label] == ["nucleus"], label))
    checks.append(("GO:0005739 reaches GO:0005737 via is_a/part_of", fuseki.ask(q("m2_sanity_mito_in_cytoplasm.rq")), None))
    n_tp53 = int(fuseki.select(q("m2_sanity_tp53_goa.rq"))[0]["n"])
    checks.append(("P04637 (TP53) has >= 1 GOA CC annotation", n_tp53 >= 1, n_tp53))
    n_not = int(fuseki.select(q("m2_sanity_not_rows.rq"))[0]["n"])
    checks.append((">= 1 negated GOA annotation", n_not >= 1, n_not))
    for name, ok, value in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" ({value})" if value is not None else ""))
    return [{"check": n, "pass": ok, "value": v} for n, ok, v in checks]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    obo, gaf, tsv = go.fetch(), goa.fetch(), uniprot.fetch()
    files = {"go_cc": RDF / "go_cc.ttl", "goa": RDF / "goa_human_cc.ttl", "uniprot": RDF / "uniprot_human.ttl"}
    stats = json.loads(STATS.read_text()) if STATS.exists() else {}
    if args.force or not files["go_cc"].exists() or "go_cc" not in stats:
        stats["go_cc"] = go_cc.build(obo)
    if args.force or not files["goa"].exists() or "goa" not in stats:
        _, cc, _ = go_cc.parse(obo)
        stats["goa"] = goa_rdf.build(gaf, set(cc))
    if args.force or not files["uniprot"].exists() or "uniprot" not in stats:
        stats["uniprot"] = uniprot_rdf.build(tsv)
    STATS.write_text(json.dumps(stats, indent=1))

    graphs = CFG["graphs"]
    triples = {graphs[k]: fuseki.load(graphs[k], f, replace=args.replace) for k, f in files.items()}

    print("[sanity]")
    checks = sanity()
    report = {"triples_per_graph": triples, "go_cc": stats["go_cc"], "goa_human_cc": stats["goa"],
              "uniprot_human": stats["uniprot"], "sanity_checks": checks}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "kg_stats.json").write_text(json.dumps(report, indent=1))
    print(f"[kg] triples: {triples}; wrote reports/kg_stats.json")
    if not all(c["pass"] for c in checks):
        raise SystemExit("[kg] sanity checks FAILED")


if __name__ == "__main__":
    main()
