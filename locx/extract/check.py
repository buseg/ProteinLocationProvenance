"""Automatic prompt evaluation for one extraction run (used to compare prompt versions).

  python -m locx.extract.check --run-id ID [--run-id ID2 ...]

Per run, over the last record per PMID:
- grounding: chosen protein / location is mentioned in the cited sentence
- rule-4 proxy: "absent" claims whose sentence has a reduction cue (reduced, impaired, prevented...)
  but no explicit negative cue (not, absent, excluded...)
- method / organism: share of finding claims with not_stated, and how often the abstract names a
  localization method / non-human organism anywhere
- OTHER: count, share that matches the GO CC dictionary exactly, the texts
- noise: claims whose location is supported only by a known false-match string in the sentence
- silver (GOA-cited abstracts): recall of GOA (protein, GO CC) pairs by present claims, matching
  the same term or an is_a/part_of ancestor or descendant; and the share of silver claims that
  match a GOA pair. GOA pairs often come from full text, so recall is a relative signal only.
Writes reports/prompt_eval_<run_id>.json and prints a side-by-side table.
"""
import argparse
import json
import re
from collections import Counter

from locx.config import DATA, INTERIM, RAW, REPORTS
from locx.io import read_jsonl
from locx.kg.go_cc import parse

RUNS = DATA / "runs"
NEG = re.compile(r"\b(not|no|absent|absence|excluded|exclusion|lack(s|ed|ing)?|devoid|neither|nor|never|"
                 r"fail(s|ed)? to|undetectable|without)\b", re.I)
RED = re.compile(r"(reduc|decreas|impair|prevent|inhibit|block|attenuat|limit|diminish|suppress|abolish|"
                 r"abrogat|restrain|retain|sequest|loss of)", re.I)
METHOD = re.compile(r"(immunofluoresc|immunostain|confocal|microscop|fractionat|western blot|immunoblot|"
                    r"GFP|RFP|mCherry|immunohistochem|IHC|electron micro|immunogold|proteomic|BioID|APEX|"
                    r"proximity label|live.cell imaging|subcellular fraction)", re.I)
NONHUMAN = re.compile(r"\b(mice|mouse|murine|rats?|zebrafish|drosophila|yeast|elegans|xenopus|chick|"
                      r"porcine|pigs?|bovine|shrimp|fish|plants?|arabidopsis|monkey|rabbit|hamster|dog|canine)\b", re.I)
NOISE = {"antibody", "antibodies", "mass", "masses", "ser", "nor", "pka", "npc", "npcs", "tac", "hsc", "hscs",
         "mac", "macs", "mucus", "car", "cars", "tcr", "tcrs", "rpa", "orc", "torc1", "nac"}


def go_relatives():
    _, cc, parents = parse(RAW / "go" / "go-basic.obo")
    up = {}

    def ancestors(t):
        if t not in up:
            out = set()
            for _, p in parents.get(t, ()):
                out |= {p} | ancestors(p)
            up[t] = out
        return up[t]
    for t in cc:
        ancestors(t)
    return up


def evaluate(run_id, cands, papers, dictionary, up):
    last = {}
    for r in read_jsonl(RUNS / run_id / "raw.jsonl"):
        last[r["pmid"]] = r
    meta = json.loads((RUNS / run_id / "run.json").read_text())
    c = Counter()
    other_texts, absent_red_examples = Counter(), []
    rec_hit = rec_all = rec_cand = 0
    silver_claims = silver_claims_match = 0
    for pmid, r in last.items():
        if pmid not in cands:  # e.g. abstracts of a stopped expanded-corpus session
            c["outside_candidates"] += 1
            continue
        if r["status"] != "ok":
            c["not_ok"] += 1
            continue
        cand = cands[pmid]
        sents = {s["id"]: s["text"] for s in cand["sentences"]}
        P = {p["cid"]: p for p in cand["proteins"]}
        Lo = {l["cid"]: l for l in cand["locations"]}
        abstract = " ".join(sents.values())
        c["abstracts"] += 1
        c["with_claim"] += bool(r["claims"])
        for cl in r["claims"]:
            c["claims"] += 1
            sid = cl["sentence"]
            c["protein_in_sentence"] += any(m["sentence"] == sid for m in P[cl["protein"]]["mentions"])
            if cl["location"] == "OTHER":
                c["other"] += 1
                t = (cl["other_location_text"] or "").strip().lower()
                other_texts[t] += 1
                c["other_in_dictionary"] += t in dictionary
            else:
                c["named_location"] += 1
                ms = [m for m in Lo[cl["location"]]["mentions"] if m["sentence"] == sid]
                c["location_in_sentence"] += bool(ms)
                if ms and all(m["text"].lower() in NOISE for m in ms):
                    c["noise_location"] += 1
            if cl["polarity"] == "absent":
                c["absent"] += 1
                s = sents.get(sid, "")
                if RED.search(s) and not NEG.search(s):
                    c["absent_reduction_only"] += 1
                    if len(absent_red_examples) < 8:
                        absent_red_examples.append(f"{pmid} {sid}: {s[:160]}")
            if cl["source_type"] == "finding":
                c["finding"] += 1
                c["finding_method_not_stated"] += cl["method"] == "not_stated"
                c["finding_method_not_stated_but_abstract_names_one"] += (cl["method"] == "not_stated"
                                                                          and bool(METHOD.search(abstract)))
                c["finding_organism_not_stated"] += cl["organism"] == "not_stated"
                c["finding_organism_not_stated_but_nonhuman_word"] += (cl["organism"] == "not_stated"
                                                                       and bool(NONHUMAN.search(abstract)))
            if cl["certainty"] == "hedged":
                c["hedged"] += 1
        # silver recall / agreement
        if "silver" in r["tiers"]:
            goa = [(g["uniprot"], g["go_id"]) for g in papers[pmid].get("goa_cc_pairs", []) if not g["negated"]]
            claims = set()
            for cl in r["claims"]:
                if cl["polarity"] == "present" and cl["location"] != "OTHER":
                    claims.add((P[cl["protein"]]["uniprot"], Lo[cl["location"]]["go_id"]))
            cand_acc = {p["uniprot"] for p in cand["proteins"]}

            def related(a, b):
                return a == b or a in up.get(b, ()) or b in up.get(a, ())
            for acc, go in set(goa):
                rec_all += 1
                rec_cand += acc in cand_acc
                rec_hit += any(a == acc and related(g, go) for a, g in claims)
            for a, g in claims:
                silver_claims += 1
                silver_claims_match += any(acc == a and related(g, go) for acc, go in goa)

    def share(k, d):
        return round(c[k] / c[d], 3) if c[d] else None
    out = {
        "run_id": run_id, "prompt_version": meta["prompt_version"], "tiers": meta["tiers"],
        "abstracts": c["abstracts"], "not_ok": c["not_ok"], "outside_candidates": c["outside_candidates"], "claims": c["claims"],
        "claims_per_abstract": round(c["claims"] / c["abstracts"], 2) if c["abstracts"] else None,
        "share_with_claim": share("with_claim", "abstracts"),
        "protein_in_sentence": share("protein_in_sentence", "claims"),
        "location_in_sentence": share("location_in_sentence", "named_location"),
        "noise_location_claims": c["noise_location"],
        "absent": c["absent"], "absent_reduction_only": c["absent_reduction_only"],
        "hedged": c["hedged"],
        "finding_method_not_stated": share("finding_method_not_stated", "finding"),
        "finding_method_not_stated_but_abstract_names_one": share("finding_method_not_stated_but_abstract_names_one", "finding"),
        "finding_organism_not_stated": share("finding_organism_not_stated", "finding"),
        "finding_organism_not_stated_but_nonhuman_word": share("finding_organism_not_stated_but_nonhuman_word", "finding"),
        "other": c["other"], "other_in_dictionary": c["other_in_dictionary"],
        "other_texts": dict(other_texts.most_common(30)),
        "absent_reduction_only_examples": absent_red_examples,
        "silver": {"goa_pairs": rec_all, "goa_pairs_protein_is_candidate": rec_cand, "recovered": rec_hit,
                   "recall": round(rec_hit / rec_all, 3) if rec_all else None,
                   "recall_candidate_proteins": round(rec_hit / rec_cand, 3) if rec_cand else None,
                   "claims": silver_claims, "claims_matching_goa": silver_claims_match,
                   "claim_goa_agreement": round(silver_claims_match / silver_claims, 3) if silver_claims else None},
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"prompt_eval_{run_id}.json").write_text(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", action="append", required=True)
    a = ap.parse_args()
    ids = set()
    for rid in a.run_id:
        ids |= {r["pmid"] for r in read_jsonl(RUNS / rid / "raw.jsonl")}
    cands = {r["pmid"]: r for r in read_jsonl(INTERIM / "candidates.jsonl") if r["pmid"] in ids}
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.jsonl") if p["pmid"] in ids}
    dictionary = set()
    with open(INTERIM / "go_cc_dictionary.tsv") as f:
        next(f)
        for line in f:
            dictionary.add(line.split("\t")[0].lower())
    up = go_relatives()
    res = [evaluate(rid, cands, papers, dictionary, up) for rid in a.run_id]
    keys = [k for k in res[0] if k not in ("run_id", "tiers", "other_texts", "absent_reduction_only_examples", "silver")]
    print(f"{'metric':52s}" + "".join(f"{r['prompt_version'] + ' ' + ','.join(r['tiers']):>22s}" for r in res))
    for k in keys:
        print(f"{k:52s}" + "".join(f"{str(r[k]):>22s}" for r in res))
    for k in res[0]["silver"]:
        print(f"{'silver.' + k:52s}" + "".join(f"{str(r['silver'][k]):>22s}" for r in res))
    for r in res:
        print(f"\n[{r['run_id']}] OTHER texts: {r['other_texts']}")
        for e in r["absent_reduction_only_examples"]:
            print("  absent? ", e)


if __name__ == "__main__":
    main()
