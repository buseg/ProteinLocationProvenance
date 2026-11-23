"""reports/dev_samples.md: 20 random dev abstracts with their extracted claims, for manual review.

  python -m locx.extract.samples [--run-id ID] [--n 20]
Default run: the newest data/runs/* whose tiers are ["dev"].
"""
import argparse
import json
import random

from locx.config import CFG, DATA, INTERIM, REPORTS
from locx.io import read_jsonl

RUNS = DATA / "runs"


def latest_dev_run() -> str:
    runs = sorted(d for d in RUNS.iterdir() if (d / "run.json").exists()
                  and json.loads((d / "run.json").read_text())["tiers"] == ["dev"])
    return runs[-1].name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    run_id = a.run_id or latest_dev_run()
    run_dir = RUNS / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    last = {}
    for r in read_jsonl(run_dir / "raw.jsonl"):
        last[r["pmid"]] = r
    cands = {r["pmid"]: r for r in read_jsonl(INTERIM / "candidates.jsonl") if r["pmid"] in last}
    papers = {p["pmid"]: p for p in read_jsonl(INTERIM / "papers.jsonl") if p["pmid"] in last}
    pmids = sorted(last, key=int)
    pick = sorted(random.Random(CFG["corpus"]["seed"]).sample(pmids, min(a.n, len(pmids))), key=int)

    out = [f"# Dev samples — run `{run_id}`", "",
           f"Prompt {meta['prompt_version']} (sha256 `{meta['prompt_sha256'][:12]}`), schema v{meta['schema_version']}, "
           f"{len(pick)} of {len(pmids)} dev abstracts (random, seed {CFG['corpus']['seed']}).", "",
           "Columns: S = sentence, pol = polarity (present/absent), cert = certainty, src = finding/background.", ""]
    for i, pmid in enumerate(pick, 1):
        c, r, p = cands[pmid], last[pmid], papers.get(pmid, {})
        P = {x["cid"]: x["symbol"] or x["uniprot"] for x in c["proteins"]}
        Lo = {x["cid"]: x["label"] for x in c["locations"]}
        out += [f"## {i}. PMID {pmid} ({p.get('year', '?')}, {p.get('journal', '?')})", ""]
        out += [f"**[{s['id']}]** {s['text']}  " for s in c["sentences"]] + [""]
        out.append("Candidate proteins: " + "; ".join(
            f"{x['cid']} {P[x['cid']]} ({', '.join(dict.fromkeys(m['text'] for m in x['mentions']))})" for x in c["proteins"]))
        out.append("")
        out.append("Candidate locations: " + "; ".join(
            f"{x['cid']} {Lo[x['cid']]} ({', '.join(dict.fromkeys(m['text'] for m in x['mentions']))})" for x in c["locations"]))
        out.append("")
        if r["status"] != "ok":
            out += [f"**{r['status']}**: {r.get('error', '')}", ""]
            continue
        if not r["claims"]:
            out += ["*No claims.*", ""]
            continue
        out += ["| S | protein | location | pol | cert | src | condition | cell type | organism | method |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for cl in r["claims"]:
            loc = Lo.get(cl["location"], f"OTHER: “{cl['other_location_text']}”")
            out.append(f"| {cl['sentence']} | {P[cl['protein']]} | {loc} | {cl['polarity']} | {cl['certainty']} | "
                       f"{cl['source_type']} | {cl['condition'] or ''} | {cl['cell_type'] or ''} | {cl['organism']} | "
                       f"{cl['method']} |")
        out.append("")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "dev_samples.md").write_text("\n".join(out))
    print(f"[samples] {len(pick)} abstracts -> reports/dev_samples.md (run {run_id})")


if __name__ == "__main__":
    main()
