"""Synonym layer at scale (prompt v3 only): which reading the model chose for ambiguous protein names.

  python -m locx.analysis.synonym_stats --run RUN [--run RUN ...] [--out synonym_stats]

For each run, reads its candidates file (run.json "input") and last answer per abstract. Counts abstracts
with alternative readings, claims on ambiguous names, tagger's reading kept vs an alternative chosen, and
lists the most frequent switches (name: tagger's protein -> chosen protein).
Writes reports/<out>.json and reports/<out>.md.
"""
import argparse
import json
from collections import Counter

from locx.analysis.synonym_pilot import RUNS, answers, pairs
from locx.config import REPORTS, ROOT
from locx.io import read_jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--out", default="synonym_stats")
    a = ap.parse_args()
    c, switches, examples = Counter(), Counter(), []
    for run_id in a.run:
        meta = json.loads((RUNS / run_id / "run.json").read_text())
        cands = {r["pmid"]: r for r in read_jsonl(ROOT / meta["input"])}
        for pmid, r in answers(run_id).items():
            rec = cands.get(pmid)
            if rec is None:
                continue
            c["abstracts"] += 1
            if not any(p.get("alt") for p in rec["proteins"]):
                continue
            c["abstracts_with_alternative_readings"] += 1
            if r["status"] != "ok":
                c["affected_not_ok"] += 1
                continue
            sents = {s["id"]: s["text"] for s in rec["sentences"]}
            for x in pairs(rec, r["claims"]):
                alt = x["cand"].get("alt")
                if not alt:
                    continue
                c["claims_on_ambiguous_names"] += 1
                roles = set(alt.values())
                if "alternative" in roles and "tagger" not in roles:
                    c["chose_alternative"] += 1
                    name = next(iter(alt))
                    tagger = [p["symbol"] for p in rec["proteins"] if (p.get("alt") or {}).get(name) == "tagger"]
                    key = f"{name}: {', '.join(tagger)} -> {x['symbol']}"
                    switches[key] += 1
                    if switches[key] == 1:
                        examples.append({"pmid": pmid, "switch": key, "location": x["loc"],
                                         "sentence": sents[x["sentence"]]})
                else:
                    c["kept_tagger_reading"] += 1
    n = c["claims_on_ambiguous_names"]
    out = {"runs": a.run, **dict(c),
           "share_alternative": round(c["chose_alternative"] / n, 3) if n else None,
           "top_switches": dict(switches.most_common(50))}
    (REPORTS / f"{a.out}.json").write_text(json.dumps(out, indent=2))
    md = [f"# Synonym layer at scale ({len(a.run)} runs)", "",
          f"{c['abstracts']} abstracts; {c['abstracts_with_alternative_readings']} with alternative readings "
          f"({100 * c['abstracts_with_alternative_readings'] / max(c['abstracts'], 1):.1f}%).",
          f"Claims on ambiguous names: {n}; tagger's reading kept {c['kept_tagger_reading']}, "
          f"alternative chosen {c['chose_alternative']} ({100 * (out['share_alternative'] or 0):.1f}%).", "",
          "## Most frequent switches (name: tagger -> chosen, count)", ""]
    md += [f"- {k}: {v}" for k, v in switches.most_common(50)]
    md += ["", "## One example per switch (first seen)", "", "| PMID | switch | location | sentence |", "|---|---|---|---|"]
    md += [f"| {e['pmid']} | {e['switch']} | {e['location']} | {e['sentence'][:200].replace('|', '/')} |"
           for e in sorted(examples, key=lambda e: -switches[e["switch"]])[:80]]
    (REPORTS / f"{a.out}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:5]))
    print(f"-> reports/{a.out}.json, reports/{a.out}.md")


if __name__ == "__main__":
    main()
