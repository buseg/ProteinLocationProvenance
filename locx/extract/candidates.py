"""M4: sentences, protein + location candidates, prefilter -> data/interim/candidates.jsonl.

Proteins: PubTator gene mentions -> NCBI GeneID -> human Swiss-Prot (non-human GeneIDs drop out).
Locations: GO CC dictionary; case-insensitive, word boundaries, longest match wins, simple plurals;
matches inside a gene mention (e.g. "nuclear" in "nuclear factor erythroid 2") are skipped.
Usage: python -m locx.extract.candidates [--papers PATH] [--tiers dev,silver]
"""
import argparse
import csv
import gzip
import json
import re
import statistics
from collections import Counter, defaultdict

from locx.config import CFG, INTERIM, REPORTS
from locx.extract.sentences import sentence_of, split
from locx.fetch import uniprot
from locx.io import read_jsonl, write_jsonl

MAX_P, MAX_L = CFG["candidates"]["max_proteins"], CFG["candidates"]["max_locations"]
# When one text maps to several GO terms, prefer the most curated source.
SOURCE_RANK = {"adjective_map": 0, "label": 1, "exact": 2, "related": 3}


def load_dictionary():
    best = {}  # lower text -> (rank, {go_id: label})
    with open(INTERIM / "go_cc_dictionary.tsv") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            key, rank = r["text"].lower(), SOURCE_RANK[r["source"]]
            cur = best.get(key)
            if cur is None or rank < cur[0]:
                best[key] = (rank, {r["go_id"]: r["label"]})
            elif rank == cur[0]:
                cur[1][r["go_id"]] = r["label"]
    terms = {k: v[1] for k, v in best.items()}
    # Longest alternatives first so the regex prefers the longest match at a position.
    alts = "|".join(re.escape(k) for k in sorted(terms, key=len, reverse=True))
    rx = re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?:es|s)?(?![A-Za-z0-9])", re.IGNORECASE)
    return terms, rx


def lookup(terms, matched: str):
    m = matched.lower()
    for key in (m, m[:-2] if m.endswith("es") else None, m[:-1] if m.endswith("s") else None):
        if key and key in terms:
            return terms[key]
    return None


def load_symbols():
    with gzip.open(uniprot.fetch(), "rt", newline="") as f:
        return {r["Entry"]: (r["Gene Names (primary)"].split(";")[0].strip() or r["Entry"])
                for r in csv.DictReader(f, delimiter="\t")}


def cap(cands: dict, limit: int):
    """Keep the `limit` most-mentioned candidates; then order by first mention."""
    items = sorted(cands.items(), key=lambda kv: (-len(kv[1]["mentions"]), kv[1]["mentions"][0]["start"]))
    kept = sorted(items[:limit], key=lambda kv: kv[1]["mentions"][0]["start"])
    return [v for _, v in kept], max(0, len(items) - limit)


def process(paper, gene2acc, symbols, terms, rx, c, match_counter, multi_acc, syn=None):
    text = paper["text"]
    sents = split(paper["title"], text)
    proteins = {}
    gene_spans = []
    for g in paper["genes"]:
        gene_spans.append((g["start"], g["end"]))
        if not g["gene_ids"]:
            c["gene_mentions_unnormalized"] += 1
            continue
        accs = [a for gid in g["gene_ids"] for a in gene2acc.get(gid, [])]
        if not accs:
            c["gene_mentions_non_human"] += 1
            continue
        c["gene_mentions_human"] += 1
        for gid in g["gene_ids"]:
            if len(gene2acc.get(gid, [])) > 1:
                multi_acc[gid] = gene2acc[gid]
        mention = {"text": g["text"], "start": g["start"], "end": g["end"], "sentence": sentence_of(sents, g["start"])}
        tagger_accs = list(dict.fromkeys(accs))
        readings = syn.readings(g["text"], accs) if syn else None
        if readings:                      # second layer: offer every reading of an ambiguous name
            c["synonym_mentions_with_alternatives"] += 1
            c["synonym_alternatives_added"] += len(set(readings) - set(accs))
            accs = readings
        for acc in dict.fromkeys(accs):
            cand = proteins.setdefault(acc, {"uniprot": acc, "symbol": symbols.get(acc, acc),
                                             "gene_ids": sorted({x for x in g["gene_ids"] if acc in gene2acc.get(x, [])}),
                                             "mentions": []})
            cand["mentions"].append(mention)
            if readings:
                cand.setdefault("alt", {})[g["text"]] = "tagger" if acc in tagger_accs else "alternative"
                cand["name"] = syn.names.get(acc, "")
    locations = {}
    for m in rx.finditer(text):
        s, e = m.span()
        if any(gs < e and s < ge for gs, ge in gene_spans):
            c["location_matches_inside_gene_mention"] += 1
            continue
        go = lookup(terms, m.group(0))
        if not go:
            continue
        match_counter[m.group(0).lower()] += 1
        mention = {"text": m.group(0), "start": s, "end": e, "sentence": sentence_of(sents, s)}
        for go_id, label in go.items():
            locations.setdefault(go_id, {"go_id": go_id, "label": label, "mentions": []})["mentions"].append(mention)
        c["location_matches"] += 1
        c["location_matches_ambiguous"] += len(go) > 1
    for cands in (proteins, locations):
        for v in cands.values():
            v["mentions"].sort(key=lambda x: x["start"])
    plist, p_cut = cap(proteins, MAX_P)
    llist, l_cut = cap(locations, MAX_L)
    for i, p in enumerate(plist, 1):
        p["cid"] = f"P{i}"
    for i, l in enumerate(llist, 1):
        l["cid"] = f"L{i}"
    return {"pmid": paper["pmid"], "tiers": paper["tiers"], "sentences": sents,
            "proteins": plist, "locations": llist,
            "truncated": {"proteins": p_cut, "locations": l_cut}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--papers", default=str(INTERIM / "papers.jsonl"))
    ap.add_argument("--tiers", default="dev,silver,discovery")
    ap.add_argument("--suffix", help="write candidates.<suffix>.jsonl etc. instead of the active files")
    ap.add_argument("--synonyms", action="store_true", help="add the second protein layer (synonym alternatives)")
    args = ap.parse_args()
    sfx = f".{args.suffix}" if args.suffix else ""
    tiers = args.tiers.split(",")

    gene2acc, symbols = uniprot.gene_to_accessions(), load_symbols()
    terms, rx = load_dictionary()
    syn = None
    if args.synonyms:
        from locx.extract.synonyms import SynonymIndex
        syn = SynonymIndex()
    c, match_counter, multi_acc = Counter(), Counter(), {}
    per_tier = {t: Counter() for t in tiers}
    n_p, n_l = defaultdict(list), defaultdict(list)
    out = []
    for paper in read_jsonl(args.papers):
        ts = [t for t in paper["tiers"] if t in tiers]
        if not ts:
            continue
        rec = process(paper, gene2acc, symbols, terms, rx, c, match_counter, multi_acc, syn)
        has_p, has_l = bool(rec["proteins"]), bool(rec["locations"])
        reason = None if has_p and has_l else ("no_protein_and_no_location" if not (has_p or has_l)
                                               else "no_protein" if not has_p else "no_location")
        for t in ts:
            per_tier[t]["in"] += 1
            per_tier[t][reason or "kept"] += 1
            if not reason:
                n_p[t].append(len(rec["proteins"]))
                n_l[t].append(len(rec["locations"]))
                per_tier[t]["truncated_proteins"] += rec["truncated"]["proteins"] > 0
                per_tier[t]["truncated_locations"] += rec["truncated"]["locations"] > 0
        if not reason:
            out.append(rec)
    write_jsonl(INTERIM / f"candidates{sfx}.jsonl", out)

    def dist(xs):
        if not xs:
            return {}
        hist = Counter(xs)
        return {"mean": round(statistics.mean(xs), 1), "median": statistics.median(xs), "max": max(xs),
                "histogram": {str(k): hist[k] for k in range(1, max(xs) + 1)}}
    human = c["gene_mentions_human"]
    total_g = human + c["gene_mentions_non_human"] + c["gene_mentions_unnormalized"]
    stats = {"input": args.papers, "tiers": tiers, "kept_papers": len(out),
             "per_tier": {t: {**dict(per_tier[t]), "proteins_per_paper": dist(n_p[t]), "locations_per_paper": dist(n_l[t])}
                          for t in tiers},
             "gene_mentions": {"total": total_g, "human": human, "non_human": c["gene_mentions_non_human"],
                               "unnormalized": c["gene_mentions_unnormalized"],
                               "share_non_human": round(c["gene_mentions_non_human"] / max(total_g, 1), 3)},
             "location_matches": {"total": c["location_matches"], "ambiguous": c["location_matches_ambiguous"],
                                  "skipped_inside_gene_mention": c["location_matches_inside_gene_mention"]},
             "geneids_with_several_accessions": len(multi_acc)}
    (REPORTS / f"candidates_stats{sfx}.json").write_text(json.dumps(stats, indent=1))
    with open(REPORTS / f"location_matches_top{sfx}.tsv", "w") as f:
        f.write("rank\tmatched_text\tcount\tgo_terms\n")
        for i, (t, n) in enumerate(match_counter.most_common(100), 1):
            go = lookup(terms, t) or {}
            f.write(f"{i}\t{t}\t{n}\t{'; '.join(f'{k} {v}' for k, v in go.items())}\n")

    print(f"[candidates] kept {len(out)} papers -> data/interim/candidates{sfx}.jsonl")
    for t in tiers:
        s = per_tier[t]
        print(f"  {t:9s} in {s['in']:5d}  kept {s['kept']:5d}  no_protein {s['no_protein']:4d}  no_location {s['no_location']:4d}  "
              f"neither {s['no_protein_and_no_location']:4d} | P/paper {dist(n_p[t]).get('mean')}  L/paper {dist(n_l[t]).get('mean')}  "
              f"truncated P {s['truncated_proteins']} L {s['truncated_locations']}")
    print(f"  gene mentions: {human} human, {c['gene_mentions_non_human']} non-human ({stats['gene_mentions']['share_non_human']:.0%}), "
          f"{c['gene_mentions_unnormalized']} without ID | location matches {c['location_matches']} "
          f"({c['location_matches_ambiguous']} ambiguous, {c['location_matches_inside_gene_mention']} skipped inside gene names) | "
          f"{len(multi_acc)} GeneIDs map to several accessions")


if __name__ == "__main__":
    main()
