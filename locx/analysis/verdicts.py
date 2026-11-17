"""M8: verdicts against GOA (SPARQL UPDATE in queries/verdicts_*.ru) + aggregation per assertion.

  python -m locx.analysis.verdicts [--run-id ID] [--replace]

1. queries/verdicts_01_goa_links.ru, verdicts_02_rules.ru -> GRAPH <urn:locx:graph:verdicts>
2. Python: independent author groups (locx/analysis/independence.py) and per-assertion stats from
   claims_final.jsonl + papers.jsonl; appended to the verdicts graph (locx:authorGroup on mentions,
   locx:nPapers, locx:nGroups, ... on assertions) - the loaded run graph is left unchanged.
3. Cross-check with queries/assertion_stats.rq; reports: verdicts.json, assertion_stats.tsv,
   top_novel.tsv, top_conflicting.tsv.
The verdicts graph is rebuilt from scratch; a non-empty graph is only dropped with --replace.
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict

from locx import evidence
from locx.analysis.independence import groups
from locx.config import CFG, DATA, INTERIM, QUERIES, RDF, REPORTS
from locx.io import read_jsonl
from locx.kg import fuseki
from locx.kg.ttl import LOCX, lit

G = CFG["graphs"]
V = G["verdicts"]
RUNS = DATA / "runs"
VERDICTS = ["Consistent", "Refinement", "Novel", "Conflicting", "Uninformative", "Error"]


def akey(cl) -> str:
    return f"{cl['protein']['uniprot']}_{cl['location']['go_id'].replace(':', '_')}_{cl['polarity']}"


def integer(x) -> str:
    return f'"{int(x)}"^^xsd:integer'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=CFG["extract"]["main_run"])
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    run_graph = G["run_prefix"] + a.run_id
    t0 = time.time()

    n = fuseki.count(V)
    if n and not a.replace:
        sys.exit(f"[verdicts] {V} already has {n} triples; rerun with --replace to rebuild it")
    if n:
        fuseki.update(f"DROP SILENT GRAPH <{V}>")
        print(f"[verdicts] dropped {V} ({n} triples) to rebuild")

    # 1. SPARQL verdicts
    for name in ("verdicts_01_goa_links.ru", "verdicts_02_rules.ru"):
        s = fuseki.run_update_file(QUERIES / name, {"%RUN_GRAPH%": run_graph,
                                                     "%EVIDENCE_CODES%": evidence.sparql_code_values(),
                                                     "%EVIDENCE_GROUPS%": evidence.sparql_group_values()})
        print(f"[verdicts] {name}: {s:.0f} s ({fuseki.count(V)} triples in {V})")
    rows = fuseki.select(f"""PREFIX locx: <{LOCX}>
        SELECT ?a ?v ?ctx ?weak ?exp ?evg WHERE {{ GRAPH <{V}> {{ ?a locx:verdict ?v
          OPTIONAL {{ ?a locx:contextDependent ?ctx }} OPTIONAL {{ ?a locx:weakGoaMatch ?weak }}
          OPTIONAL {{ ?a locx:goaExperimental ?exp }} OPTIONAL {{ ?a locx:goaEvidence ?evg }} }} }}""")
    verdict = {}
    for r in rows:
        k = r["a"].rsplit("/", 1)[-1]
        if k in verdict:
            sys.exit(f"[verdicts] assertion {k} got two verdicts")
        verdict[k] = {"verdict": r["v"].rsplit("/", 1)[-1], "context": r.get("ctx") == "true",
                      "weak": r.get("weak") == "true", "goa_experimental": None if "exp" not in r else r["exp"] == "true",
                      "goa_evidence": r.get("evg", "")}
    goa_src = defaultdict(set)   # assertion -> PMIDs that GOA cites for P in T's lineage
    for r in fuseki.select(f"""PREFIX locx: <{LOCX}> PREFIX dcterms: <http://purl.org/dc/terms/>
        SELECT ?a ?src WHERE {{ GRAPH <{V}> {{ ?a locx:goaSame|locx:goaNarrower|locx:goaBroader ?g }}
          GRAPH <{G['goa']}> {{ ?g dcterms:source ?src }} }}"""):
        goa_src[r["a"].rsplit("/", 1)[-1]].add(r["src"].rsplit("/", 1)[-1])
    mention_iri = {r["cid"]: r["m"] for r in fuseki.select(f"""PREFIX locx: <{LOCX}>
        SELECT ?m ?cid WHERE {{ GRAPH <{run_graph}> {{ ?m locx:claimId ?cid }} }}""")}

    # 2. aggregation + author groups
    claims = [c for c in read_jsonl(RUNS / a.run_id / "claims_final.jsonl") if c["valid"]]
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.jsonl")}
    by_a = defaultdict(list)
    for c in claims:
        by_a[akey(c)].append(c)
    pt_papers = defaultdict(set)   # (protein, GO) -> {polarity: pmids}
    for c in claims:
        pt_papers[(c["protein"]["uniprot"], c["location"]["go_id"], c["polarity"])].add(c["pmid"])
    stats, ttl = {}, ["@prefix locx: <http://example.org/locx/> .\n@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"]
    for k, cs in sorted(by_a.items()):
        pm = sorted({c["pmid"] for c in cs}, key=int)
        g = groups(pm, papers)
        for c in cs:
            group_id = f"{k}/g{g[c['pmid']]}"
            ttl.append(f"<{mention_iri[c['claim_id']]}> locx:authorGroup {lit(group_id)} .")
        c0 = cs[0]
        opp = "absent" if c0["polarity"] == "present" else "present"
        years = [papers[p]["year"] for p in pm if papers[p].get("year")]
        s = {"assertion": k, "symbol": c0["protein"]["symbol"], "uniprot": c0["protein"]["uniprot"],
             "go_id": c0["location"]["go_id"], "location": c0["location"]["label"], "polarity": c0["polarity"],
             **verdict.get(k, {"verdict": "MISSING"}),
             "n_mentions": len(cs), "n_papers": len(pm),
             "n_papers_finding": len({c["pmid"] for c in cs if c["source_type"] == "finding"}),
             "n_papers_background": len({c["pmid"] for c in cs if c["source_type"] == "background"}),
             "n_papers_hedged": len({c["pmid"] for c in cs if c["certainty"] == "hedged"}),
             "n_groups": len(set(g.values())),
             "year_first": min(years) if years else None, "year_last": max(years) if years else None,
             "n_journals": len({papers[p].get("journal") for p in pm if papers[p].get("journal")}),
             "sum_citations": sum(papers[p].get("cited_by") or 0 for p in pm),
             "methods": sorted({c["method"] for c in cs} - {"not_stated"}),
             "organisms": sorted({c["organism"] for c in cs} - {"not_stated"}),
             "conditions": list(dict.fromkeys(x for c in cs for x in c["conditions"]))[:5],
             "n_opposing_papers": len(pt_papers.get((c0["protein"]["uniprot"], c0["location"]["go_id"], opp), set())),
             "curated_from_same_paper": bool(set(pm) & goa_src.get(k, set())),
             "tiers": sorted({t for c in cs for t in c["tiers"]}), "pmids": pm,
             "example": {"pmid": c0["pmid"], "sentence": c0["sentence_text"]}}
        stats[k] = s
        subj = f"<{LOCX}assertion/{k}>"
        ttl.append(f"{subj} locx:nMentions {integer(s['n_mentions'])} ; locx:nPapers {integer(s['n_papers'])} ; "
                   f"locx:nPapersFinding {integer(s['n_papers_finding'])} ; locx:nPapersBackground {integer(s['n_papers_background'])} ; "
                   f"locx:nPapersHedged {integer(s['n_papers_hedged'])} ; locx:nGroups {integer(s['n_groups'])} ; "
                   + (f"locx:yearFirst {integer(s['year_first'])} ; locx:yearLast {integer(s['year_last'])} ; " if years else "")
                   + f"locx:nJournals {integer(s['n_journals'])} ; locx:sumCitations {integer(s['sum_citations'])} ; "
                   f"locx:nOpposingPapers {integer(s['n_opposing_papers'])} ; "
                   f"locx:curatedFromSamePaper {'true' if s['curated_from_same_paper'] else 'false'} .")
    missing = [k for k in by_a if k not in verdict]
    if missing or len(verdict) != len(by_a):
        sys.exit(f"[verdicts] {len(by_a)} assertions with valid mentions, {len(verdict)} verdicts; missing {missing[:5]}")
    path = RDF / f"verdict_stats_{a.run_id}.ttl"
    path.write_text("\n".join(ttl) + "\n")
    fuseki.append(V, path)
    nv = fuseki.count(V)
    print(f"[verdicts] appended stats + author groups ({len(ttl) - 1} statements); {V}: {nv} triples")
    man = json.loads(fuseki.MANIFEST.read_text()) if fuseki.MANIFEST.exists() else {}
    man[V] = {"file": "(SPARQL UPDATE + verdict_stats)", "sha256": None, "triples": nv,
              "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    fuseki.MANIFEST.write_text(json.dumps(man, indent=1))

    # 3. cross-check with the SPARQL version of the stats
    q = (QUERIES / "assertion_stats.rq").read_text().replace("%RUN_GRAPH%", run_graph)
    sparql = {r["a"].rsplit("/", 1)[-1]: r for r in fuseki.select(q)}
    bad = [k for k, s in stats.items() if int(sparql[k]["n_papers"]) != s["n_papers"]
           or int(sparql[k]["n_groups"]) != s["n_groups"] or int(sparql[k]["n_mentions"]) != s["n_mentions"]]
    print(f"[verdicts] SPARQL assertion_stats.rq vs Python: {len(stats) - len(bad)}/{len(stats)} agree")

    # reports
    dist = Counter(s["verdict"] for s in stats.values())
    per_tier = {t: Counter(s["verdict"] for s in stats.values() if t in s["tiers"]) for t in ("silver", "discovery")}
    ev = {v: Counter("experimental" if s["goa_experimental"] else "non-experimental only"
                     for s in stats.values() if s["verdict"] == v) for v in ("Consistent", "Refinement", "Conflicting")}
    out = {"run_id": a.run_id, "assertions": len(stats),
           "verdicts": {v: dist[v] for v in VERDICTS},
           "verdicts_share": {v: round(dist[v] / len(stats), 3) for v in VERDICTS},
           "per_tier": {t: {v: c[v] for v in VERDICTS} for t, c in per_tier.items()},
           "goa_evidence_behind_verdict": {v: dict(c) for v, c in ev.items()},
           # strongest GO evidence group among the GOA rows behind the verdict (locx/evidence.py)
           "goa_evidence_group_behind_verdict": {
               v: {g: sum(1 for s in stats.values() if s["verdict"] == v and s["goa_evidence"] == g)
                   for g, _, _ in evidence.GROUPS} for v in ("Consistent", "Refinement", "Conflicting")},
           # literature support for curated locations that have no experimental GOA evidence
           "upgrade_candidates": {v: sum(1 for s in stats.values() if s["verdict"] == v and s["goa_evidence"]
                                         and evidence.RANK[s["goa_evidence"]] > evidence.RANK["high_throughput"])
                                  for v in ("Consistent", "Refinement")},
           "conflicting_with_experimental_goa": sum(1 for s in stats.values() if s["verdict"] == "Conflicting"
                                                    and s["goa_evidence"] == "experimental"),
           "context_dependent": sum(s["context"] for s in stats.values()),
           "weak_goa_match_only": sum(s["weak"] for s in stats.values()),
           "curated_from_same_paper": sum(s["curated_from_same_paper"] for s in stats.values()),
           "novel_by_n_groups": dict(sorted(Counter(min(s["n_groups"], 5) for s in stats.values()
                                                    if s["verdict"] == "Novel").items())),
           "sparql_python_agreement": f"{len(stats) - len(bad)}/{len(stats)}",
           "seconds": round(time.time() - t0)}
    (REPORTS / "verdicts.json").write_text(json.dumps(out, indent=2))
    cols = ["symbol", "location", "go_id", "polarity", "verdict", "n_papers", "n_groups", "n_papers_finding",
            "n_papers_background", "n_papers_hedged", "n_mentions", "year_first", "year_last", "n_journals",
            "sum_citations", "n_opposing_papers", "curated_from_same_paper", "context", "weak", "goa_experimental", "goa_evidence",
            "methods", "organisms", "conditions", "tiers", "uniprot", "pmids", "example_pmid", "example_sentence"]

    def write(path, items):
        with open(path, "w", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(cols)
            for s in items:
                w.writerow([("; ".join(map(str, s[c])) if isinstance(s.get(c), list) else s.get(c)) for c in cols[:-2]]
                           + [s["example"]["pmid"], s["example"]["sentence"]])
    ranked = sorted(stats.values(), key=lambda s: (-s["n_groups"], -s["n_papers_finding"], -s["n_papers"], s["assertion"]))
    write(REPORTS / "assertion_stats.tsv", ranked)
    write(REPORTS / "top_novel.tsv", [s for s in ranked if s["verdict"] == "Novel"][:20])
    write(REPORTS / "top_conflicting.tsv", [s for s in ranked if s["verdict"] == "Conflicting"][:20])

    print(f"[verdicts] {len(stats)} assertions: " + ", ".join(f"{v} {dist[v]} ({dist[v] / len(stats):.0%})" for v in VERDICTS))
    for t, c in per_tier.items():
        print(f"  {t:10s} " + ", ".join(f"{v} {c[v]}" for v in VERDICTS))
    print(f"  GOA evidence behind verdict: {out['goa_evidence_behind_verdict']}")
    print(f"  strongest GOA evidence group: {out['goa_evidence_group_behind_verdict']}")
    print(f"  upgrade candidates {out['upgrade_candidates']}, conflicting with experimental GOA "
          f"{out['conflicting_with_experimental_goa']}")
    print(f"  context-dependent {out['context_dependent']}, weak-only {out['weak_goa_match_only']}, "
          f"curated from same paper {out['curated_from_same_paper']}, novel by n_groups {out['novel_by_n_groups']}")
    print(f"[verdicts] -> reports/verdicts.json, assertion_stats.tsv, top_novel.tsv, top_conflicting.tsv ({out['seconds']} s)")


if __name__ == "__main__":
    main()
