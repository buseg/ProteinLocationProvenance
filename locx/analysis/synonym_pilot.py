"""Synonym-layer pilot: prompt v3 (alternative readings) vs v2 (PubTator only) on the same abstracts.

  python -m locx.analysis.synonym_pilot --v2 RUN_V2 --v3 RUN_V3 --v2-cands FILE --v3-cands FILE

Per abstract the claims are mapped to (UniProt, GO term or OTHER text, polarity). Reports:
- claims in v3 on proteins with alternative readings: tagger's reading vs an alternative chosen
- every claim that switched to an alternative (sentence, name, tagger's protein -> chosen protein)
- claim counts, and for silver abstracts the share of (protein, GO) pairs that match a GOA pair
  (same term or is_a/part_of ancestor/descendant) in v2 vs v3
Writes reports/synonym_pilot.json and reports/synonym_pilot.md.
"""
import argparse
import json
from collections import Counter

from locx.config import DATA, INTERIM, RAW, REPORTS, ROOT
from locx.io import read_jsonl
from locx.kg.go_cc import parse

RUNS = DATA / "runs"


def answers(run_id):
    last = {}
    for r in read_jsonl(RUNS / run_id / "raw.jsonl"):
        last[r["pmid"]] = r
    return last


def pairs(rec, claims):
    P = {p["cid"]: p for p in rec["proteins"]}
    L = {l["cid"]: l for l in rec["locations"]}
    out = []
    for c in claims:
        p = P[c["protein"]]
        loc = L[c["location"]]["go_id"] if c["location"] != "OTHER" else "OTHER:" + (c["other_location_text"] or "").lower()
        out.append({"uniprot": p["uniprot"], "symbol": p["symbol"], "loc": loc, "polarity": c["polarity"],
                    "sentence": c["sentence"], "cand": p})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", required=True)
    ap.add_argument("--v3", required=True)
    ap.add_argument("--v2-cands", required=True)
    ap.add_argument("--v3-cands", required=True)
    a = ap.parse_args()
    a2, a3 = answers(a.v2), answers(a.v3)
    c2 = {r["pmid"]: r for r in read_jsonl(ROOT / a.v2_cands)}
    c3 = {r["pmid"]: r for r in read_jsonl(ROOT / a.v3_cands)}
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.expanded2.jsonl") if p["pmid"] in a3}
    _, _, parents = parse(RAW / "go" / "go-basic.obo")
    up = {}

    def anc(t):
        if t not in up:
            up[t] = set()
            for _, p in parents.get(t, ()):
                up[t] |= {p} | anc(p)
        return up[t]

    def related(x, y):
        return x == y or x in anc(y) or y in anc(x)

    c = Counter()
    switched = []
    agree = Counter()
    for pmid, r3 in a3.items():
        r2 = a2.get(pmid)
        if not r2 or r2["status"] != "ok" or r3["status"] != "ok":
            c["skipped_not_ok"] += 1
            continue
        c["abstracts"] += 1
        v2 = pairs(c2[pmid], r2["claims"])
        v3 = pairs(c3[pmid], r3["claims"])
        c["claims_v2"] += len(v2)
        c["claims_v3"] += len(v3)
        s3 = {(x["uniprot"], x["loc"], x["polarity"]) for x in v3}
        s2 = {(x["uniprot"], x["loc"], x["polarity"]) for x in v2}
        c["claims_same"] += len(s2 & s3)
        c["claims_only_v2"] += len(s2 - s3)
        c["claims_only_v3"] += len(s3 - s2)
        sents = {s["id"]: s["text"] for s in c3[pmid]["sentences"]}
        for x in v3:
            alt = x["cand"].get("alt")
            if not alt:
                continue
            roles = set(alt.values())
            c["v3_claims_on_ambiguous_names"] += 1
            if "alternative" in roles and "tagger" not in roles:
                c["v3_chose_alternative"] += 1
                name = next(iter(alt))
                tagger = [p["symbol"] for p in c3[pmid]["proteins"] if (p.get("alt") or {}).get(name) == "tagger"]
                switched.append({"pmid": pmid, "name": name, "tagger": ", ".join(tagger), "chosen": x["symbol"],
                                 "location": x["loc"], "polarity": x["polarity"], "sentence": sents[x["sentence"]]})
            else:
                c["v3_kept_tagger_reading"] += 1
        if "silver" in c3[pmid]["tiers"]:
            goa = [(g["uniprot"], g["go_id"]) for g in papers[pmid].get("goa_cc_pairs", []) if not g["negated"]]
            for name, vs in (("v2", v2), ("v3", v3)):
                for x in vs:
                    if x["loc"].startswith("GO:") and x["polarity"] == "present":
                        agree[f"{name}_pairs"] += 1
                        agree[f"{name}_match"] += any(u == x["uniprot"] and related(x["loc"], g) for u, g in goa)
    out = {"v2_run": a.v2, "v3_run": a.v3, **dict(c),
           "silver_goa_agreement": {k: (round(agree[f"{k}_match"] / agree[f"{k}_pairs"], 3) if agree[f"{k}_pairs"] else None)
                                    for k in ("v2", "v3")},
           "silver_pairs": {k: agree[f"{k}_pairs"] for k in ("v2", "v3")},
           "switched_names": dict(Counter(f"{s['name']}: {s['tagger']} -> {s['chosen']}" for s in switched).most_common(40))}
    (REPORTS / "synonym_pilot.json").write_text(json.dumps(out, indent=2))
    md = [f"# Synonym-layer pilot: v3 `{a.v3}` vs v2 `{a.v2}`", "",
          f"{c['abstracts']} abstracts with alternative readings. Claims v2 {c['claims_v2']} → v3 {c['claims_v3']} "
          f"(same {c['claims_same']}, only v2 {c['claims_only_v2']}, only v3 {c['claims_only_v3']}).",
          f"v3 claims on ambiguous names: {c['v3_claims_on_ambiguous_names']}; tagger's reading kept "
          f"{c['v3_kept_tagger_reading']}, alternative chosen {c['v3_chose_alternative']}.",
          f"Silver agreement with GOA (lineage): v2 {out['silver_goa_agreement']['v2']} "
          f"({agree['v2_pairs']} pairs), v3 {out['silver_goa_agreement']['v3']} ({agree['v3_pairs']} pairs).", "",
          "## Claims that switched to an alternative reading", "",
          "| PMID | name | tagger → chosen | location | sentence |", "|---|---|---|---|---|"]
    md += [f"| {s['pmid']} | {s['name']} | {s['tagger']} → **{s['chosen']}** | {s['location']} ({s['polarity']}) | "
           f"{s['sentence'][:220].replace('|', '/')} |" for s in switched]
    (REPORTS / "synonym_pilot.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6]))
    print(f"switched claims: {len(switched)} -> reports/synonym_pilot.md")


if __name__ == "__main__":
    main()
