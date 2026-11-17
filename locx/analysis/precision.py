"""M9.2 manual precision.

  python -m locx.analysis.precision sample [--run-id ID]   # reports/precision_sample.csv + precision_review.md
  python -m locx.analysis.precision score                  # precision with a 95% Wilson interval

The sample: random valid claims, stratified discovery / silver (default 200 / 100; the MVP sheet had 40 / 20,
kept in reports/precision_mvp/; seed from config). The
review file shows each claim with its full abstract, for the judge (rubric: reports/precision_rubric.md).
`sample` refuses to overwrite a sheet that already has judgements.
"""
import argparse
import csv
import json
import math
import random
import sys

from locx.config import CFG, DATA, INTERIM, REPORTS
from locx.io import read_jsonl

RUNS = DATA / "runs"
SHEET = REPORTS / "precision_sample.csv"
COLS = ["claim_id", "pmid", "tier", "pubmed_url", "sentence_id", "sentence_text", "protein_symbol",
        "protein_mention", "location_label", "polarity", "condition", "source_type", "verdict",
        "correct", "notes", "judge"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def sample(run_id, n_disc=200, n_silv=100):
    if SHEET.exists() and any(r["correct"].strip() for r in csv.DictReader(open(SHEET))):
        sys.exit(f"[precision] {SHEET} already has judgements; not overwriting")
    claims = [c for c in read_jsonl(RUNS / run_id / "claims_final.jsonl") if c["valid"]]
    verdict = {}
    with open(REPORTS / "assertion_stats.tsv") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            verdict[(r["uniprot"], r["go_id"], r["polarity"])] = r["verdict"]
    rng = random.Random(CFG["corpus"]["seed"])
    disc = [c for c in claims if "discovery" in c["tiers"] and "silver" not in c["tiers"]]
    silv = [c for c in claims if "silver" in c["tiers"]]
    pick = [("discovery", c) for c in rng.sample(disc, n_disc)] + [("silver", c) for c in rng.sample(silv, n_silv)]
    rng.shuffle(pick)   # judge in mixed order, not tier by tier
    cands = {r["pmid"]: r for r in read_jsonl(INTERIM / "candidates.jsonl")}
    rows, md = [], ["# Precision review sheet", "", "Rubric: `reports/precision_rubric.md`. Verdicts are hidden here.", ""]
    for i, (tier, c) in enumerate(pick, 1):
        cand = cands[c["pmid"]]
        P = {p["cid"]: p for p in cand["proteins"]}
        mentions = list(dict.fromkeys(m["text"] for m in P[c["protein"]["cid"]]["mentions"]))
        loc = c["location"]["label"] + (f" (OTHER: “{c['location']['other_location_text']}”)"
                                         if c["location"]["cid"] == "OTHER" else "")
        rows.append({"claim_id": c["claim_id"], "pmid": c["pmid"], "tier": tier,
                     "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{c['pmid']}/", "sentence_id": c["sentence"],
                     "sentence_text": c["sentence_text"], "protein_symbol": c["protein"]["symbol"],
                     "protein_mention": "; ".join(mentions), "location_label": loc, "polarity": c["polarity"],
                     "condition": "; ".join(c["conditions"]), "source_type": c["source_type"],
                     "verdict": verdict.get((c["protein"]["uniprot"], c["location"]["go_id"], c["polarity"]), ""),
                     "correct": "", "notes": "", "judge": ""})
        md += [f"## {i}. claim {c['claim_id']} (PMID {c['pmid']})", "",
               f"**Claim:** {c['protein']['symbol']} (mentioned as {', '.join(mentions)}) — **{loc}** — "
               f"{c['polarity']}, {c['certainty']}, {c['source_type']}; cited {c['sentence']}; "
               f"condition: {'; '.join(c['conditions']) or '-'}; flags: {', '.join(c['flags']) or '-'}", ""]
        md += [f"[{s['id']}] {s['text']}" + ("  ← cited" if s["id"] == c["sentence"] else "") + "  " for s in cand["sentences"]]
        md.append("")
    with open(SHEET, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    (REPORTS / "precision_review.md").write_text("\n".join(md))
    print(f"[precision] {len(rows)} claims ({n_disc} discovery, {n_silv} silver) -> {SHEET.name}, precision_review.md")


def score():
    rows = list(csv.DictReader(open(SHEET)))
    judged = [r for r in rows if r["correct"].strip() in ("0", "1")]
    out = {"judged": len(judged), "of": len(rows), "judges": sorted({r["judge"] for r in judged})}
    for name, sel in (("all", judged), ("discovery", [r for r in judged if r["tier"] == "discovery"]),
                      ("silver", [r for r in judged if r["tier"] == "silver"])):
        k = sum(r["correct"].strip() == "1" for r in sel)
        out[name] = {"n": len(sel), "correct": k, "precision": round(k / len(sel), 3) if sel else None,
                     "wilson95": wilson(k, len(sel))}
    errors = {}
    for r in judged:
        if r["correct"].strip() == "0":
            t = (r["notes"].split(":")[0].split()[0] if r["notes"].strip() else "unspecified")
            errors[t] = errors.get(t, 0) + 1
    out["error_types"] = errors
    by_verdict = {}
    for r in judged:
        v = by_verdict.setdefault(r["verdict"] or "?", [0, 0])
        v[0] += r["correct"].strip() == "1"
        v[1] += 1
    out["by_verdict"] = {v: {"correct": a, "n": b} for v, (a, b) in sorted(by_verdict.items())}
    second = REPORTS / "precision_second_judge.csv"   # a second judge on a random subset (agreement check)
    if second.exists():
        first = {r["claim_id"]: r["correct"].strip() for r in judged}
        pairs = [(first[r["claim_id"]], r["correct"].strip()) for r in csv.DictReader(open(second))
                 if r["claim_id"] in first and r["correct"].strip() in ("0", "1")]
        if pairs:
            po = sum(x == y for x, y in pairs) / len(pairs)
            p1 = sum(x == "1" for x, _ in pairs) / len(pairs)
            p2 = sum(y == "1" for _, y in pairs) / len(pairs)
            pe = p1 * p2 + (1 - p1) * (1 - p2)
            out["second_judge"] = {"n": len(pairs), "agreement": round(po, 3),
                                   "cohen_kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
                                   "judge": "Claude Opus 5.5 (main session), blind to the first judgement"}
    (REPORTS / "precision.json").write_text(json.dumps(out, indent=2))
    a = out["all"]
    print(f"[precision] {a['correct']}/{a['n']} correct = {a['precision']:.1%} (95% Wilson {a['wilson95']}) | "
          f"discovery {out['discovery']['precision']} silver {out['silver']['precision']} | errors {errors} | "
          f"by verdict {out['by_verdict']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "score"])
    ap.add_argument("--run-id", default=CFG["extract"]["main_run"])
    ap.add_argument("--n-discovery", type=int, default=200)
    ap.add_argument("--n-silver", type=int, default=100)
    a = ap.parse_args()
    sample(a.run_id, a.n_discovery, a.n_silver) if a.step == "sample" else score()


if __name__ == "__main__":
    main()
