"""M3: corpus tiers (dev, silver, discovery) -> data/interim/papers.jsonl.

Canonical text = PubTator title + abstract (so gene offsets line up); metadata from Europe PMC.
Usage: python -m locx.corpus
"""
import json
import random
import time
from collections import Counter, defaultdict

from locx.config import CFG, INTERIM, RAW, REPORTS
from locx.fetch import europepmc, goa, pubtator, uniprot
from locx.io import write_jsonl

C = CFG["corpus"]
LOC = ('(translocat* OR localiz* OR localis* OR relocaliz* OR subcellular OR shuttl* OR sequest* '
       'OR "nuclear accumulation" OR "nuclear import" OR "nuclear export")')
BASE = "SRC:MED AND HAS_ABSTRACT:y AND LANG:eng"
TIERS = ("dev", "silver", "discovery")


def dev_tier():
    y0, y1 = C["dev_years"]
    chosen, per_seed, queries = [], {}, {}
    for symbol, names in C["dev_seeds"].items():
        q = f'ABSTRACT:({" OR ".join(json.dumps(n, ensure_ascii=False) for n in names)}) AND ABSTRACT:{LOC} AND {BASE} AND PUB_YEAR:[{y0} TO {y1}]'
        hits, recs = europepmc.search(q, limit=100, page_size=100)
        new = [r for r in recs if r.get("pmid") and r["pmid"] not in {c["pmid"] for c in chosen}][:C["dev_per_protein"]]
        chosen += new
        per_seed[symbol] = {"hits": hits, "taken": len(new)}
        queries[symbol] = q
        print(f"[dev] {symbol}: {hits} hits, took {len(new)}")
    return chosen, {"per_seed": per_seed, "queries": queries}


def goa_index():
    """PMIDs cited by any GOA CC row, and low-throughput experimental pairs per PMID."""
    low = set(CFG["silver"]["evidence_low_throughput"])
    any_pmids, pairs = set(), defaultdict(set)
    for _, r in goa.rows(RAW / "goa" / "goa_human.gaf.gz"):
        if r["db"] != "UniProtKB":
            continue
        pmids = {x[5:] for x in r["refs"].split("|") if x.startswith("PMID:")}
        any_pmids |= pmids
        if r["evidence"] in low:
            negated = "NOT" in r["qualifier"].split("|")
            for p in pmids:
                pairs[p].add((r["acc"], r["go_id"], r["evidence"], negated))
    return any_pmids, pairs


def nested_sample(pool, k, seed):
    """Random sample whose smaller sizes are subsets of the larger ones. random.sample(pool, k) is a
    prefix-stable draw only while it uses its set-based branch (k <= 5000 for this pool, so the 1,000
    sample is inside the 5,000 one); above that, keep the 5,000 sample and add the rest from the remainder."""
    if k <= 5000:
        return random.Random(seed).sample(pool, k)
    base = random.Random(seed).sample(pool, 5000)
    rest = sorted(set(pool) - set(base), key=int)
    return base + random.Random(seed + 1).sample(rest, min(k - 5000, len(rest)))


def silver_tier(pairs):
    pool = sorted(pairs, key=int)
    sample = sorted(nested_sample(pool, C["silver_sample"], C["seed"]), key=int)
    print(f"[silver] {len(pool)} PMIDs with low-throughput experimental evidence; sampled {len(sample)} (seed {C['seed']})")
    recs = europepmc.by_pmids(sample)
    print(f"[silver] Europe PMC records: {len(recs)}/{len(sample)}")
    return sample, recs, {"pool": len(pool), "sampled": len(sample), "seed": C["seed"]}


def discovery_tier(gene2acc, step: int = 250, max_screen: int | None = None):
    """Per year: walk down Europe PMC's relevance ranking and keep the first papers that have an
    abstract in PubTator and >= 1 gene mapping to human Swiss-Prot, until discovery_cap / n_years."""
    y0, y1 = C["discovery_years"]
    years = list(range(y0, y1 + 1))
    if C["discovery_cap"] == 0:          # no cap: walk each year's whole ranking (decisions 2026-11-16)
        per_year, max_screen, step = 10 ** 9, 10 ** 9, 1000
    else:
        per_year = C["discovery_cap"] // len(years)
        max_screen = max_screen or C.get("discovery_max_screen_per_year", 4000)
    protein = " AND ABSTRACT:(protein*)" if C.get("discovery_protein_filter", True) else ""
    recs, meta = [], {"order": "Europe PMC relevance within each year; kept if >= 1 human Swiss-Prot gene",
                      "per_year": {}, "queries": {}}
    seen = set()  # a paper can rank in two year queries (e.g. online vs print year); keep it once
    for y in years:
        q = f"ABSTRACT:{LOC}{protein} AND {BASE} AND PUB_YEAR:{y}"
        kept, skipped, screened = [], Counter(), 0
        while len(kept) < per_year and screened < max_screen:
            hits, ranked = europepmc.search(q, limit=screened + step)
            batch = [r for r in ranked[screened:screened + step] if r.get("pmid")]
            if not batch:
                break
            docs = pubtator.fetch([r["pmid"] for r in batch])
            for r in batch:
                screened += 1
                if len(kept) == per_year:
                    break
                if r["pmid"] in seen:
                    skipped["kept_in_earlier_year"] += 1
                    continue
                doc = docs.get(r["pmid"])
                if doc is None:
                    skipped["not_in_pubtator"] += 1
                    continue
                pt = pubtator.parse(doc)
                if not pt["has_abstract"]:
                    skipped["no_abstract"] += 1
                elif not any(g in gene2acc for m in pt["genes"] for g in m["gene_ids"]):
                    skipped["no_human_gene"] += 1
                else:
                    kept.append(r)
                    seen.add(r["pmid"])
        recs += kept
        meta["per_year"][y] = {"hits": hits, "screened": screened, "kept": len(kept), "skipped": dict(skipped)}
        meta["queries"][y] = q
        print(f"[discovery] {y}: {hits} hits; screened top {screened}, kept {len(kept)}, skipped {dict(skipped)}")
    meta["taken"] = len(recs)
    return recs, meta


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver", type=int, help="silver sample size (default config)")
    ap.add_argument("--discovery", type=int, help="discovery cap (default config)")
    ap.add_argument("--max-screen", type=int, help="discovery: max papers screened per year")
    ap.add_argument("--suffix", help="write papers.<suffix>.jsonl etc. instead of the active files")
    ap.add_argument("--years", type=int, nargs=2, metavar=("FIRST", "LAST"), help="discovery years")
    ap.add_argument("--no-protein-filter", action="store_true", help="discovery query without ABSTRACT:(protein*) (V1)")
    ap.add_argument("--no-silver", action="store_true", help="skip the silver tier (per-year discovery slices)")
    a = ap.parse_args()
    if a.silver:
        C["silver_sample"] = a.silver
    if a.discovery is not None:
        C["discovery_cap"] = a.discovery
    if a.years:
        C["discovery_years"] = a.years
    if a.no_protein_filter:
        C["discovery_protein_filter"] = False
    if a.max_screen:
        C["discovery_max_screen_per_year"] = a.max_screen
    sfx = f".{a.suffix}" if a.suffix else ""
    t0 = time.time()
    dev_recs, dev_meta = dev_tier()
    disc_recs, disc_meta = discovery_tier(uniprot.gene_to_accessions())
    in_goa, pairs = goa_index()
    if a.no_silver:   # per-year slices for incremental extraction: discovery only, no new API calls
        silver_pmids, silver_recs, silver_meta = [], [], {"skipped": "--no-silver"}
    else:
        silver_pmids, silver_recs, silver_meta = silver_tier(pairs)

    tiers, records = defaultdict(list), {}
    for r in dev_recs:
        tiers[r["pmid"]].append("dev"); records[r["pmid"]] = r
    for r in disc_recs:
        if r.get("pmid"):
            tiers[r["pmid"]].append("discovery"); records[r["pmid"]] = r
    for p in silver_pmids:
        tiers[p].append("silver")
        if p in silver_recs:
            records[p] = silver_recs[p]

    docs = pubtator.fetch(list(tiers))
    selected, kept, dropped = Counter(), Counter(), defaultdict(Counter)
    papers = []
    for pmid in sorted(tiers, key=int):
        ts = tiers[pmid]
        for t in ts:
            selected[t] += 1
        reason = None
        if pmid not in records:
            reason = "no_europepmc_record"
        elif pmid not in docs:
            reason = "not_in_pubtator"
        else:
            pt = pubtator.parse(docs[pmid])
            if not pt["has_abstract"]:
                reason = "no_abstract_in_pubtator"
        if reason:
            for t in ts:
                dropped[t][reason] += 1
            continue
        meta = europepmc.metadata(records[pmid])
        paper = {**meta, "title": pt["title"], "text": pt["text"], "genes": pt["genes"], "tiers": ts,
                 "in_goa": pmid in in_goa}
        if "silver" in ts:
            paper["goa_cc_pairs"] = [{"uniprot": a, "go_id": g, "evidence": e, "negated": n}
                                     for a, g, e, n in sorted(pairs[pmid])]
        papers.append(paper)
        for t in ts:
            kept[t] += 1

    write_jsonl(INTERIM / f"papers{sfx}.jsonl", papers)

    def share(f, rows):
        return round(sum(map(f, rows)) / len(rows), 3) if rows else 0
    per_tier = {}
    for t in TIERS:
        rows = [p for p in papers if t in p["tiers"]]
        per_tier[t] = {"selected": selected[t], "kept": kept[t], "dropped": dict(dropped[t]),
                       "share_with_orcid": share(lambda p: any(a["orcid"] for a in p["authors"]), rows),
                       "share_with_gene_mention": share(lambda p: bool(p["genes"]), rows),
                       "mean_gene_mentions": round(sum(len(p["genes"]) for p in rows) / max(len(rows), 1), 1),
                       "years": dict(sorted(Counter(p["year"] for p in rows).items(), key=lambda kv: kv[0] or 0))}
    overlap = Counter(tuple(p["tiers"]) for p in papers if len(p["tiers"]) > 1)
    stats = {"papers": len(papers), "per_tier": per_tier,
             "overlap": {"+".join(k): v for k, v in overlap.items()},
             "share_with_orcid_all": share(lambda p: any(a["orcid"] for a in p["authors"]), papers)}
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "dev": dev_meta, "silver": silver_meta,
            "discovery": disc_meta, "localization_clause": LOC, "base_filter": BASE}
    (INTERIM / f"corpus_meta{sfx}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    (REPORTS / f"corpus_stats{sfx}.json").write_text(json.dumps(stats, indent=1))

    print(f"[corpus] {len(papers)} papers -> data/interim/papers{sfx}.jsonl ({time.time() - t0:.0f} s)")
    for t in TIERS:
        s = per_tier[t]
        print(f"  {t:9s} selected {s['selected']:5d}  kept {s['kept']:5d}  dropped {s['dropped']}  "
              f"ORCID {s['share_with_orcid']:.0%}  with genes {s['share_with_gene_mention']:.0%}")
    print(f"  overlap: {stats['overlap']}")


if __name__ == "__main__":
    main()
