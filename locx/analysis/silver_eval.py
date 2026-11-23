"""Silver recall: LLM claims against the GOA pairs of GOA-cited abstracts.

  python -m locx.analysis.silver_eval [--run-id ID]

Expected pairs per silver PMID: GOA (UniProt, GO CC) pairs that cite the PMID with low-throughput
experimental evidence (config silver.evidence_low_throughput), not negated. Only pairs whose protein
is among that abstract's candidates are kept (the abstract cannot support the others); candidates are
computed for every silver paper, including the ones the M4 prefilter dropped, so the denominator is
honest. A pair is recovered
  exactly        if a valid present claim from that PMID has the same protein and GO term,
  hierarchically if the claim's term equals it or is one is_a/part_of step above or below it.
Coverage = expected pairs whose protein and term both appear as candidates (the design's ceiling).
Baseline = co-occurrence: every protein candidate x location candidate in the same sentence.
GOA agreement = share of a method's (protein, term) pairs that match an expected pair (exact / hier).
Writes reports/silver_eval.json and reports/silver_eval.md.
"""
import argparse
import json
from collections import Counter, defaultdict

from locx.config import CFG, DATA, INTERIM, RAW, REPORTS
from locx.extract.candidates import load_dictionary, load_symbols, process
from locx.fetch import uniprot
from locx.io import read_jsonl
from locx.kg.go_cc import parse

RUNS = DATA / "runs"
LOW = set(CFG["silver"]["evidence_low_throughput"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=CFG["extract"]["main_run"])
    a = ap.parse_args()

    _, cc, parents = parse(RAW / "go" / "go-basic.obo")
    up = defaultdict(set)
    for child, rels in parents.items():
        for _, p in rels:
            up[child].add(p)

    def near(x, y):   # same term or one is_a/part_of step either way
        return x == y or y in up.get(x, ()) or x in up.get(y, ())

    papers = [p for p in read_jsonl(INTERIM / "papers.jsonl") if "silver" in p["tiers"]]
    gene2acc, symbols = uniprot.gene_to_accessions(), load_symbols()
    terms, rx = load_dictionary()
    junk = (Counter(), Counter(), {})
    claims = defaultdict(set)      # pmid -> {(acc, go)} valid present claims
    claims_all = defaultdict(set)  # incl. invalid (grounded) claims, for reference
    for cl in read_jsonl(RUNS / a.run_id / "claims_final.jsonl"):
        if "silver" in cl["tiers"] and cl["polarity"] == "present" and cl["location"]["go_id"]:
            pair = (cl["protein"]["uniprot"], cl["location"]["go_id"])
            claims_all[cl["pmid"]].add(pair)
            if cl["valid"]:
                claims[cl["pmid"]].add(pair)

    c = Counter()
    vol = Counter()
    agree = Counter()
    per_evidence = defaultdict(Counter)
    for p in papers:
        rec = process(p, gene2acc, symbols, terms, rx, *junk)
        cand_p = {x["uniprot"] for x in rec["proteins"]}
        cand_l = {x["go_id"] for x in rec["locations"]}
        prefiltered = not (rec["proteins"] and rec["locations"])
        # co-occurrence baseline
        sent_p, sent_l = defaultdict(set), defaultdict(set)
        for x in rec["proteins"]:
            for m in x["mentions"]:
                sent_p[m["sentence"]].add(x["uniprot"])
        for x in rec["locations"]:
            for m in x["mentions"]:
                sent_l[m["sentence"]].add(x["go_id"])
        cooc = {(acc, go) for s in sent_p for acc in sent_p[s] for go in sent_l.get(s, ())}

        pairs = {}
        for g in p.get("goa_cc_pairs", []):
            if g["negated"] or g["evidence"] not in LOW:
                continue
            pairs.setdefault((g["uniprot"], g["go_id"]), set()).add(g["evidence"])
        c["goa_pairs_low_throughput"] += len(pairs)
        expected = {k: v for k, v in pairs.items() if k[0] in cand_p}
        c["removed_protein_not_candidate"] += len(pairs) - len(expected)
        c["papers_with_expected"] += bool(expected)
        llm, base = claims.get(p["pmid"], set()), cooc
        for (acc, go), evs in expected.items():
            c["expected"] += 1
            c["expected_in_prefiltered_paper"] += prefiltered
            c["coverage_exact"] += go in cand_l
            c["coverage_hier"] += any(near(go, l) for l in cand_l)
            hit_e = any(x == (acc, go) for x in llm)
            hit_h = any(x[0] == acc and near(x[1], go) for x in llm)
            c["llm_exact"] += hit_e
            c["llm_hier"] += hit_h
            c["llm_all_claims_hier"] += any(x[0] == acc and near(x[1], go) for x in claims_all.get(p["pmid"], ()))
            c["base_exact"] += (acc, go) in base
            c["base_hier"] += any(x[0] == acc and near(x[1], go) for x in base)
            for ev in evs:
                per_evidence[ev]["expected"] += 1
                per_evidence[ev]["llm_hier"] += hit_h
        vol["llm_pairs"] += len(llm)
        vol["base_pairs"] += len(base)
        for name, s in (("llm", llm), ("base", base)):
            for acc, go in s:
                agree[f"{name}_exact"] += (acc, go) in pairs
                agree[f"{name}_hier"] += any(k[0] == acc and near(k[1], go) for k in pairs)
        c["papers"] += 1
        c["papers_prefiltered"] += prefiltered

    def r(k):
        return round(c[k] / c["expected"], 3) if c["expected"] else None
    out = {
        "run_id": a.run_id, "evidence_codes": sorted(LOW), "papers": c["papers"],
        "papers_prefiltered_out_in_M4": c["papers_prefiltered"],
        "goa_pairs_low_throughput": c["goa_pairs_low_throughput"],
        "removed_protein_not_candidate": c["removed_protein_not_candidate"],
        "expected_pairs": c["expected"], "papers_with_expected_pairs": c["papers_with_expected"],
        "expected_in_prefiltered_papers": c["expected_in_prefiltered_paper"],
        "coverage": {"exact": r("coverage_exact"), "hierarchical": r("coverage_hier")},
        "llm": {"recall_exact": r("llm_exact"), "recall_hierarchical": r("llm_hier"),
                "recall_hierarchical_incl_invalid": r("llm_all_claims_hier"),
                "pairs": vol["llm_pairs"],
                "goa_agreement_exact": round(agree["llm_exact"] / vol["llm_pairs"], 3),
                "goa_agreement_hierarchical": round(agree["llm_hier"] / vol["llm_pairs"], 3)},
        "cooccurrence_baseline": {"recall_exact": r("base_exact"), "recall_hierarchical": r("base_hier"),
                                  "pairs": vol["base_pairs"],
                                  "goa_agreement_exact": round(agree["base_exact"] / vol["base_pairs"], 3),
                                  "goa_agreement_hierarchical": round(agree["base_hier"] / vol["base_pairs"], 3)},
        "llm_recall_hier_by_evidence": {ev: {"expected": v["expected"],
                                             "recall": round(v["llm_hier"] / v["expected"], 3)}
                                        for ev, v in sorted(per_evidence.items())},
        "caveat": "GOA curators read full texts; some curated pairs are not stated in the abstract, so recall is a lower bound.",
    }
    (REPORTS / "silver_eval.json").write_text(json.dumps(out, indent=2))
    L, B = out["llm"], out["cooccurrence_baseline"]
    md = [f"# Silver evaluation — run `{a.run_id}`", "",
          f"{c['papers']} silver abstracts; {c['goa_pairs_low_throughput']} GOA low-throughput experimental pairs "
          f"({', '.join(sorted(LOW))}); {c['removed_protein_not_candidate']} removed because the protein is not a "
          f"candidate in the abstract; **{c['expected']} expected pairs** in {c['papers_with_expected']} abstracts "
          f"({c['expected_in_prefiltered_paper']} of them in abstracts the M4 prefilter dropped).", "",
          "| | recall exact | recall hierarchical (±1 step) | (protein, term) pairs produced | agreement with GOA exact | agreement hierarchical |",
          "|---|---|---|---|---|---|",
          f"| Coverage (ceiling: protein and term are candidates) | {out['coverage']['exact']:.1%} | {out['coverage']['hierarchical']:.1%} | | | |",
          f"| **LLM (valid present claims)** | **{L['recall_exact']:.1%}** | **{L['recall_hierarchical']:.1%}** | {L['pairs']} | {L['goa_agreement_exact']:.1%} | {L['goa_agreement_hierarchical']:.1%} |",
          f"| Co-occurrence baseline (same sentence) | {B['recall_exact']:.1%} | {B['recall_hierarchical']:.1%} | {B['pairs']} | {B['goa_agreement_exact']:.1%} | {B['goa_agreement_hierarchical']:.1%} |",
          "", f"LLM hierarchical recall including invalid claims: {L['recall_hierarchical_incl_invalid']:.1%}.",
          "", "Agreement with GOA = share of a method's pairs that match a curated pair for that paper (a rough precision proxy; GOA is incomplete).",
          "", f"*{out['caveat']}*"]
    (REPORTS / "silver_eval.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
