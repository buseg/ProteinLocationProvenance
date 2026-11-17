"""Dry run of run.py's --seed-from check: how many abstracts of a candidates file would be reused, and how
many would go to the model. Same rule as run.py (identical system + user message + schema; first seed run
that matches wins). Writes nothing except the printed counts.

  python scripts/seed_dryrun.py --candidates FILE --tiers silver,discovery --seed-from RUN1,RUN2,...
"""
import argparse
import json
from collections import Counter

from locx.config import DATA, ROOT
from locx.extract import prompt, schema
from locx.io import read_jsonl

RUNS = DATA / "runs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--tiers", default="silver,discovery")
    ap.add_argument("--seed-from", required=True)
    a = ap.parse_args()
    tiers = set(a.tiers.split(","))
    new_in = {r["pmid"]: r for r in read_jsonl(ROOT / a.candidates) if tiers & set(r["tiers"])}
    done, per_seed, changed = {}, Counter(), Counter()
    for seed_id in a.seed_from.split(","):
        sm = json.loads((RUNS / seed_id / "run.json").read_text())
        old_in = {r["pmid"]: r for r in read_jsonl(ROOT / sm["input"]) if r["pmid"] in new_in}
        last = {}
        for r in read_jsonl(RUNS / seed_id / "raw.jsonl"):
            last[r["pmid"]] = r
        for p, r in last.items():
            if p in done or p not in new_in or r["status"] == "error" or p not in old_in:
                continue
            if prompt.messages(old_in[p]) == prompt.messages(new_in[p]) and schema.build(old_in[p]) == schema.build(new_in[p]):
                done[p] = seed_id
                per_seed[seed_id] += 1
            else:
                changed[seed_id] += 1
        print(f"  {seed_id}: reused {per_seed[seed_id]}, request changed {changed[seed_id]}", flush=True)
    todo = [p for p in new_in if p not in done]
    by_tier = Counter("+".join(sorted(tiers & set(new_in[p]["tiers"]))) for p in todo)
    print(f"[dryrun] {len(new_in)} abstracts in tiers {sorted(tiers)}: reused {len(done)}, to the model {len(todo)} "
          f"{dict(by_tier)}")


if __name__ == "__main__":
    main()
