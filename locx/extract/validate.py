"""Claim validation, Python part (the location checks that need GO run as SHACL shapes).

  python -m locx.extract.validate [--run-id ID]      # default: config extract.main_run

Text-based checks per claim; flags are stored, no claim is dropped:
  V1 bad_json                  abstract-level: the model's answer did not parse (no claims)
  V2 protein_not_in_sentence   chosen protein not mentioned in the cited sentence
     protein_coref             ... but mentioned in an earlier sentence (warning only)
  V3 location_not_in_sentence  chosen candidate location not mentioned in the cited sentence
     location_coref            ... but mentioned in an earlier sentence (warning only)
  V4 other_grounded_exact / other_grounded_fuzzy / other_ungrounded   OTHER text -> GO CC
  V7 duplicates                same (protein, location, polarity, sentence) merged; count and
                               all distinct conditions kept
V5 impossible_location and V6 too_generic are SHACL shapes in M7 (run against the GO graph), so
`valid` here is provisional: final validity = provisional and no impossible_location.

Writes data/runs/<run_id>/claims.jsonl and reports/validation_<run_id>.json.
"""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict

from rapidfuzz import fuzz, process

from locx.config import CFG, DATA, INTERIM, RAW, REPORTS, ROOT
from locx.extract.candidates import load_dictionary
from locx.io import read_jsonl, write_jsonl
from locx.kg.go_cc import check_label, parse

RUNS = DATA / "runs"
FUZZY_MIN = 92        # minimum fuzzy score for grounding a free-text location
FUZZY_MIN_LEN = 5     # no fuzzy matching for very short texts ("er" vs "ecm")
# Grounding-only aliases for texts the candidate stoplist keeps out of the dictionary.
# Every ID is verified by its label against go-basic.obo at start-up.
ALIASES = {"er": ("GO:0005783", "endoplasmic reticulum"),
           "perinuclear region": ("GO:0048471", "perinuclear region of cytoplasm")}
INVALID = {"bad_json", "protein_not_in_sentence", "location_not_in_sentence", "other_ungrounded"}


def normalize(text: str) -> str:
    t = (text or "").lower().strip().strip(".,;:\"'()[]")
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"\s+", " ", t)


def keys(t: str):
    """The text itself, then English and Latin singulars (nucleoli -> nucleolus, lamellipodia -> lamellipodium)."""
    yield t
    if t.endswith("ies"):
        yield t[:-3] + "y"
    if t.endswith("es"):
        yield t[:-2]
    if t.endswith("s"):
        yield t[:-1]
    if t.endswith("i"):
        yield t[:-1] + "us"
    if t.endswith("ia"):
        yield t[:-1] + "um"
    if t.endswith("a"):
        yield t[:-1] + "um"
        yield t[:-1] + "on"


class Grounder:
    def __init__(self):
        self.terms, _ = load_dictionary()           # lower text -> {go_id: label} (best source only)
        _, cc, _ = parse(RAW / "go" / "go-basic.obo")
        for text, (go_id, label) in ALIASES.items():
            check_label(cc, go_id, label)
        self.aliases = {k: {v[0]: v[1]} for k, v in ALIASES.items()}
        self.choices = list(self.terms)

    def ground(self, text: str):
        t = normalize(text)
        if not t:
            return None
        for k in keys(t):
            hit = self.aliases.get(k) or self.terms.get(k)
            if hit:
                return {"method": "exact", "matched": k, "score": 100, "go_ids": hit}
        if len(t) >= FUZZY_MIN_LEN:
            best = process.extractOne(t, self.choices, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
            # nuclear vs nucleolar differ by two letters but are different compartments
            if best and ("nucleol" in t) != ("nucleol" in best[0]):
                best = None
            if best:
                return {"method": "fuzzy", "matched": best[0], "score": round(best[1], 1),
                        "go_ids": self.terms[best[0]]}
        return None


def claim_id(run_id, pmid, key) -> str:
    return hashlib.sha1(f"{run_id}|{pmid}|{json.dumps(key)}".encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=CFG.get("extract", {}).get("main_run"))
    a = ap.parse_args()
    run_dir = RUNS / a.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    # the run's own candidates file (run.json "input"); older runs without it used candidates.jsonl
    src = ROOT / meta["input"] if meta.get("input") else INTERIM / "candidates.jsonl"
    cands = {r["pmid"]: r for r in read_jsonl(src) if set(meta["tiers"]) & set(r["tiers"])}
    last = {}
    for r in read_jsonl(run_dir / "raw.jsonl"):
        last[r["pmid"]] = r
    g = Grounder()

    c, per_tier = Counter(), defaultdict(Counter)
    ungrounded, fuzzy_examples, other_exact = Counter(), [], Counter()
    out = []
    c["raw_records_outside_candidates"] = sum(1 for p in last if p not in cands)
    for pmid in sorted(cands, key=int):
        rec, r = cands[pmid], last.get(pmid)
        tiers = [t for t in rec["tiers"] if t in meta["tiers"]]
        if r is None:
            c["abstracts_missing_in_run"] += 1
            continue
        for t in tiers:
            per_tier[t]["abstracts"] += 1
        if r["status"] != "ok":
            c[f"abstracts_{r['status']}"] += 1          # V1 bad_json (or error): no claims to store
            for t in tiers:
                per_tier[t][f"abstracts_{r['status']}"] += 1
            continue
        S = {s["id"]: s for s in rec["sentences"]}
        order = {s["id"]: i for i, s in enumerate(rec["sentences"])}
        P = {p["cid"]: p for p in rec["proteins"]}
        L = {l["cid"]: l for l in rec["locations"]}
        merged = {}
        for cl in r["claims"]:
            c["claims_raw"] += 1
            for t in tiers:
                per_tier[t]["claims_raw"] += 1
            sid, p = cl["sentence"], P[cl["protein"]]
            flags = []
            # V2
            sent_idx = {order[m["sentence"]] for m in p["mentions"] if m["sentence"] in order}
            if order[sid] not in sent_idx:
                flags.append("protein_coref" if any(i < order[sid] for i in sent_idx) else "protein_not_in_sentence")
            # V3 / V4
            if cl["location"] == "OTHER":
                gr = g.ground(cl["other_location_text"])
                if gr is None:
                    flags.append("other_ungrounded")
                    ungrounded[normalize(cl["other_location_text"])] += 1
                    loc = {"cid": "OTHER", "go_id": None, "label": None}
                else:
                    flags.append(f"other_grounded_{gr['method']}")
                    go_id, label = sorted(gr["go_ids"].items())[0]
                    loc = {"cid": "OTHER", "go_id": go_id, "label": label}
                    if len(gr["go_ids"]) > 1:
                        flags.append("other_ambiguous")
                    if gr["method"] == "fuzzy" and len(fuzzy_examples) < 25:
                        fuzzy_examples.append(f"{cl['other_location_text']} -> {gr['matched']} ({gr['score']}) {go_id} {label}")
                    if gr["method"] == "exact":
                        other_exact[f"{normalize(cl['other_location_text'])} -> {label}"] += 1
                loc["other_location_text"] = cl["other_location_text"]
                loc["grounding"] = gr and {k: gr[k] for k in ("method", "matched", "score")}
            else:
                lo = L[cl["location"]]
                if not any(m["sentence"] == sid for m in lo["mentions"]):
                    earlier = any(order[m["sentence"]] < order[sid] for m in lo["mentions"])
                    flags.append("location_coref" if earlier else "location_not_in_sentence")
                loc = {"cid": lo["cid"], "go_id": lo["go_id"], "label": lo["label"], "other_location_text": None}
            # V7: merge within the abstract
            key = (p["uniprot"], loc["go_id"] or normalize(cl["other_location_text"]), cl["polarity"], sid)
            if key in merged:
                m = merged[key]
                m["duplicate_count"] += 1
                if cl["condition"] and cl["condition"] not in m["conditions"]:
                    m["conditions"].append(cl["condition"])
                c["claims_merged_away"] += 1
                continue
            merged[key] = {
                "claim_id": claim_id(a.run_id, pmid, key), "run_id": a.run_id, "pmid": pmid, "tiers": tiers,
                "sentence": sid, "sentence_text": S[sid]["text"], "sentence_start": S[sid]["start"],
                "sentence_end": S[sid]["end"],
                "protein": {"cid": p["cid"], "uniprot": p["uniprot"], "symbol": p["symbol"], "gene_ids": p["gene_ids"]},
                "location": loc,
                **{k: cl[k] for k in ("polarity", "certainty", "source_type", "condition", "cell_type",
                                      "organism", "method")},
                "conditions": [cl["condition"]] if cl["condition"] else [],
                "duplicate_count": 1, "flags": flags,
                "valid_provisional": not (set(flags) & INVALID),
            }
        for m in merged.values():
            out.append(m)
            for t in tiers:
                pt = per_tier[t]
                pt["claims"] += 1
                pt["valid_provisional"] += m["valid_provisional"]
                for f in m["flags"]:
                    pt[f] += 1
            c["claims"] += 1
            c["valid_provisional"] += m["valid_provisional"]
            for f in m["flags"]:
                c[f"flag_{f}"] += 1
        for t in tiers:
            per_tier[t]["abstracts_with_valid_claim"] += any(m["valid_provisional"] for m in merged.values())

    write_jsonl(run_dir / "claims.jsonl", out)
    stats = {
        "run_id": a.run_id, "totals": dict(c),
        "share_valid_provisional": round(c["valid_provisional"] / c["claims"], 3) if c["claims"] else None,
        "per_tier": {t: {**dict(v), "share_valid_provisional": round(v["valid_provisional"] / v["claims"], 3)
                         if v["claims"] else None} for t, v in per_tier.items()},
        "other_ungrounded_top": dict(ungrounded.most_common(40)),
        "other_grounded_exact_top": dict(other_exact.most_common(25)),
        "other_grounded_fuzzy_examples": fuzzy_examples,
        "fuzzy_min": FUZZY_MIN, "aliases": ALIASES,
        "note": "V5 impossible_location / V6 too_generic are checked by SHACL in M7; validity here is provisional.",
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"validation_{a.run_id}.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))

    print(f"[validate] run {a.run_id}: {c['claims_raw']} raw claims -> {c['claims']} after merging "
          f"({c['claims_merged_away']} duplicates) | valid (provisional) {c['valid_provisional']} "
          f"({stats['share_valid_provisional']:.1%}) | bad_json abstracts {c['abstracts_bad_json']}"
          f" | raw records outside candidates {c['raw_records_outside_candidates']}")
    print("  flags: " + ", ".join(f"{k[5:]} {v}" for k, v in sorted(c.items()) if k.startswith("flag_")))
    for t, v in stats["per_tier"].items():
        print(f"  {t:10s} abstracts {v['abstracts']:5d}  claims {v['claims']:5d}  valid {v['valid_provisional']:5d} "
              f"({v['share_valid_provisional']:.1%})  abstracts with a valid claim {v['abstracts_with_valid_claim']}")
    print(f"  OTHER ungrounded top: {dict(ungrounded.most_common(15))}")
    print(f"  OTHER fuzzy examples: {fuzzy_examples[:8]}")
    print(f"[validate] -> {run_dir}/claims.jsonl, reports/validation_{a.run_id}.json")


if __name__ == "__main__":
    main()
