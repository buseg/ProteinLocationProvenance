"""M5 extraction: async requests to the local vLLM endpoint, one per abstract.

  python -m locx.extract.run --tiers dev                     # new run on the dev tier
  python -m locx.extract.run --tiers silver,discovery        # full run
  python -m locx.extract.run --run-id <id>                   # resume: skips PMIDs already done

Writes data/runs/<run_id>/raw.jsonl incrementally (one line per finished request) and run.json.
Throughput and per-tier claim stats go to reports/extract_<run_id>.json.
"""
import argparse
import asyncio
import hashlib
import json
import random
import statistics
import time
from collections import Counter
from datetime import datetime

import requests
from openai import AsyncOpenAI

from locx.config import CFG, DATA, INTERIM, REPORTS, secret
from locx.extract import prompt, schema
from locx.io import read_jsonl

L = CFG["llm"]
RUNS = DATA / "runs"
RETRIES = 2


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def done_pmids(raw_path) -> set[str]:
    """PMIDs whose last record has status ok or bad_json (a model answer we keep); errors are redone."""
    last = {}
    if raw_path.exists():
        for r in read_jsonl(raw_path):
            last[r["pmid"]] = r["status"]
    return {p for p, s in last.items() if s != "error"}


async def extract_one(client, rec, sem, out, lock, progress):
    async with sem:
        body = dict(model=L["served_name"], messages=prompt.messages(rec), temperature=L["temperature"],
                    max_tokens=L["max_tokens"],
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": "claims", "schema": schema.build(rec)}})
        row = {"pmid": rec["pmid"], "tiers": rec["tiers"]}
        for attempt in range(RETRIES + 1):
            t = time.time()
            try:
                r = await client.chat.completions.create(**body)
                ch = r.choices[0]
                row.update(attempts=attempt + 1, latency=round(time.time() - t, 2), finish_reason=ch.finish_reason,
                           prompt_tokens=r.usage.prompt_tokens, completion_tokens=r.usage.completion_tokens,
                           content=ch.message.content)
                try:
                    row["claims"] = json.loads(ch.message.content)["claims"]
                    row["status"] = "ok"
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    row.update(status="bad_json", error=f"{type(e).__name__}: {e}"[:300])
                break
            except Exception as e:  # network/HTTP errors: retry up to RETRIES times
                row.update(status="error", attempts=attempt + 1, error=f"{type(e).__name__}: {e}"[:300])
                if attempt < RETRIES:
                    await asyncio.sleep(5 * (attempt + 1))
        row["finished"] = datetime.now().isoformat(timespec="seconds")
        async with lock:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            progress[0] += 1
            if progress[0] % 25 == 0 or progress[0] == progress[1]:
                print(f"[extract] {progress[0]}/{progress[1]} done ({time.time() - progress[2]:.0f} s)")


async def run_all(recs, raw_path, concurrency):
    client = AsyncOpenAI(base_url=L["endpoint"], api_key=secret("VLLM_API_KEY"), timeout=900, max_retries=0)
    sem, lock = asyncio.Semaphore(concurrency), asyncio.Lock()
    progress = [0, len(recs), time.time()]
    with open(raw_path, "a") as out:
        await asyncio.gather(*(extract_one(client, r, sem, out, lock, progress) for r in recs))
    await client.close()


def summarize(run_dir, recs_all, tiers, wall_s, new_pmids):
    """Per-tier claim stats (last record per PMID) and throughput of this session's requests."""
    last = {}
    for r in read_jsonl(run_dir / "raw.jsonl"):
        last[r["pmid"]] = r
    rows = [last[r["pmid"]] for r in recs_all if r["pmid"] in last]
    status = Counter(r["status"] for r in rows)
    per_tier = {}
    for t in tiers:
        tr = [r for r in rows if t in r["tiers"]]
        ok = [r for r in tr if r["status"] == "ok"]
        n_claims = [len(r["claims"]) for r in ok]
        per_tier[t] = {"abstracts": len(tr), "ok": len(ok),
                       "claims": sum(n_claims),
                       "claims_per_abstract": round(statistics.mean(n_claims), 2) if n_claims else 0,
                       "share_with_claim": round(sum(1 for n in n_claims if n) / len(ok), 3) if ok else 0}
    answered = [r for r in rows if r["status"] != "error"]
    pt = sum(r["prompt_tokens"] for r in answered)
    ct = sum(r["completion_tokens"] for r in answered)
    stats = {
        "abstracts": len(rows), "status": dict(status),
        "error_rate": round(status["error"] / len(rows), 4) if rows else 0,
        "bad_json_rate": round(status["bad_json"] / len(rows), 4) if rows else 0,
        "truncated_max_tokens": sum(1 for r in answered if r.get("finish_reason") == "length"),
        "retried": sum(1 for r in rows if r.get("attempts", 1) > 1),
        "tokens": {"prompt_total": pt, "completion_total": ct,
                   "prompt_mean": round(pt / len(answered)) if answered else 0,
                   "completion_mean": round(ct / len(answered)) if answered else 0,
                   "completion_max": max((r["completion_tokens"] for r in answered), default=0)},
        "latency_s": {"mean": round(statistics.mean(r["latency"] for r in answered), 1) if answered else 0,
                      "max": max((r["latency"] for r in answered), default=0)},
        "per_tier": per_tier,
    }
    new = [r for r in answered if r["pmid"] in new_pmids]
    if new and wall_s > 0:
        stats["throughput_this_session"] = {
            "requests": len(new_pmids), "answered": len(new), "wall_s": round(wall_s),
            "abstracts_per_s": round(len(new) / wall_s, 3),
            "prompt_tokens_per_s": round(sum(r["prompt_tokens"] for r in new) / wall_s),
            "completion_tokens_per_s": round(sum(r["completion_tokens"] for r in new) / wall_s)}
    return stats


def projection(stats):
    """Time for the full run (silver + discovery) at this session's abstracts/s."""
    tp = stats.get("throughput_this_session")
    if not tp:
        return None
    full = {r["pmid"] for r in read_jsonl(INTERIM / "candidates.jsonl")
            if {"silver", "discovery"} & set(r["tiers"])}
    hours = len(full) / tp["abstracts_per_s"] / 3600
    return {"full_run_abstracts": len(full), "projected_hours": round(hours, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="dev", help="comma-separated tiers (new run)")
    ap.add_argument("--run-id", help="resume this run")
    ap.add_argument("--limit", type=int, help="first N abstracts only (smoke test)")
    ap.add_argument("--sample", type=int, help="random N abstracts of the tiers (seed from config; prompt tuning)")
    ap.add_argument("--concurrency", type=int, default=L["concurrency"])
    a = ap.parse_args()

    if a.run_id:
        run_dir = RUNS / a.run_id
        meta = json.loads((run_dir / "run.json").read_text())
        tiers = meta["tiers"]
        a.sample = a.sample or meta.get("sample")
        if meta["prompt_sha256"] != prompt.prompt_sha256() or meta["schema_version"] != schema.SCHEMA_VERSION:
            raise SystemExit("prompt or schema changed since this run started; start a new run instead")
    else:
        tiers = a.tiers.split(",")
        run_id = f"{L['served_name']}_{datetime.now():%Y%m%d-%H%M}"
        run_dir = RUNS / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            vllm_version = requests.get(L["endpoint"].rsplit("/v1", 1)[0] + "/version", timeout=10).json()["version"]
        except Exception:
            vllm_version = "unknown"
        meta = {"run_id": run_id, "tiers": tiers, "model": L["model"], "served_name": L["served_name"],
                "vllm_version": vllm_version, "endpoint": L["endpoint"], "gpu": L["gpu"],
                "prompt_version": prompt.PROMPT_VERSION, "prompt_sha256": prompt.prompt_sha256(),
                "schema_version": schema.SCHEMA_VERSION, "temperature": L["temperature"],
                "max_tokens": L["max_tokens"], "concurrency": a.concurrency, "retries": RETRIES,
                "input": "data/interim/candidates.jsonl",
                "input_sha256": sha256_file(INTERIM / "candidates.jsonl"), "sample": a.sample,
                "started": datetime.now().isoformat(timespec="seconds"), "sessions": []}

    recs_all = [r for r in read_jsonl(INTERIM / "candidates.jsonl") if set(tiers) & set(r["tiers"])]
    if a.sample:
        recs_all = sorted(random.Random(CFG["corpus"]["seed"]).sample(recs_all, a.sample), key=lambda r: int(r["pmid"]))
    if a.limit:
        recs_all = recs_all[:a.limit]
    done = done_pmids(run_dir / "raw.jsonl")
    todo = [r for r in recs_all if r["pmid"] not in done]
    print(f"[extract] run {meta['run_id']} | tiers {tiers} | {len(recs_all)} abstracts, "
          f"{len(recs_all) - len(todo)} done, {len(todo)} to do | concurrency {a.concurrency}")
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2))

    input_sha = sha256_file(INTERIM / "candidates.jsonl")  # hash what this session reads, at its start
    t0 = time.time()
    if todo:
        asyncio.run(run_all(todo, run_dir / "raw.jsonl", a.concurrency))
    wall = time.time() - t0

    stats = summarize(run_dir, recs_all, tiers, wall, {r["pmid"] for r in todo})
    proj = projection(stats)
    if proj:
        stats["projection"] = proj
    meta["sessions"].append({"started": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
                             "ended": datetime.now().isoformat(timespec="seconds"), "requests": len(todo),
                             "input_abstracts": len(recs_all),
                             "input_sha256": input_sha})
    meta["ended"] = datetime.now().isoformat(timespec="seconds")
    meta["counts"] = {"abstracts": stats["abstracts"], **stats["status"],
                      "claims": sum(v["claims"] for v in stats["per_tier"].values())}
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"extract_{meta['run_id']}.json").write_text(json.dumps(stats, indent=2))

    print(f"[extract] status {stats['status']} | error rate {stats['error_rate']:.2%} | "
          f"bad JSON {stats['bad_json_rate']:.2%} | truncated {stats['truncated_max_tokens']} | retried {stats['retried']}")
    print(f"[extract] tokens/abstract: prompt {stats['tokens']['prompt_mean']}, completion "
          f"{stats['tokens']['completion_mean']} (max {stats['tokens']['completion_max']}) | latency mean "
          f"{stats['latency_s']['mean']} s, max {stats['latency_s']['max']} s")
    for t, v in stats["per_tier"].items():
        print(f"  {t:10s} abstracts {v['abstracts']:5d}  ok {v['ok']:5d}  claims {v['claims']:6d}  "
              f"per abstract {v['claims_per_abstract']}  with >=1 claim {v['share_with_claim']:.0%}")
    if "throughput_this_session" in stats:
        tp = stats["throughput_this_session"]
        print(f"[throughput] {tp['abstracts_per_s']} abstracts/s | prompt {tp['prompt_tokens_per_s']} tok/s | "
              f"completion {tp['completion_tokens_per_s']} tok/s | wall {tp['wall_s']} s")
    if proj:
        print(f"[projection] full run {proj['full_run_abstracts']} abstracts ≈ {proj['projected_hours']} h")
    print(f"[extract] -> {run_dir}/raw.jsonl, run.json, reports/extract_{meta['run_id']}.json")


if __name__ == "__main__":
    main()
