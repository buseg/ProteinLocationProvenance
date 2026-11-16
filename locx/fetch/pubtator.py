"""PubTator3 BioC JSON: canonical text (title + abstract) and gene annotations. Cached per PMID.

Annotation offsets are document-level (title at 0, abstract at len(title) + 1), so text built by
placing each passage at its offset lines up with them exactly.
"""
import json
import time

import requests

from locx.config import RAW
from locx.io import get_json

URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
CACHE = RAW / "pubtator"
MISSING = CACHE / "_missing.txt"
PAUSE = 2.5  # PubTator3 guidance ~30 requests/min


def fetch(pmids, batch: int = 100) -> dict[str, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = set(MISSING.read_text().split()) if MISSING.exists() else set()
    todo = [p for p in sorted(set(pmids), key=int) if not (CACHE / f"{p}.json").exists() and p not in missing]
    print(f"[pubtator] {len(set(pmids))} PMIDs: {len(set(pmids)) - len(todo)} cached/known-missing, {len(todo)} to fetch "
          f"(~{len(todo) // batch + 1} requests, ~{(len(todo) // batch + 1) * PAUSE / 60:.0f} min)")
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        try:
            data = get_json(URL, params={"pmids": ",".join(chunk)})
        except requests.HTTPError as e:
            # PubTator3 answers 400 "Could not retrieve publications" only when NONE of the PMIDs
            # is available (very new papers not yet processed); a mixed batch returns 200.
            if e.response is None or e.response.status_code != 400:
                raise
            data = {"PubTator3": []}
        docs = data.get("PubTator3", []) if isinstance(data, dict) else data
        got = set()
        for doc in docs:
            pmid = str(doc.get("pmid") or doc.get("id"))
            (CACHE / f"{pmid}.json").write_text(json.dumps(doc))
            got.add(pmid)
        new_missing = set(chunk) - got
        if new_missing:
            with open(MISSING, "a") as f:
                f.write("\n".join(sorted(new_missing)) + "\n")
        if (i // batch) % 5 == 4 or i + batch >= len(todo):
            print(f"[pubtator] {min(i + batch, len(todo))}/{len(todo)} fetched")
        time.sleep(PAUSE)
    out = {}
    for p in set(pmids):
        path = CACHE / f"{p}.json"
        if path.exists():
            out[p] = json.loads(path.read_text())
    return out


def parse(doc: dict) -> dict:
    """{'title', 'text', 'has_abstract', 'genes': [{gene_ids, text, start, end, homologene}]}"""
    text, title, has_abstract = "", "", False
    for p in sorted(doc["passages"], key=lambda p: p["offset"]):
        kind = p.get("infons", {}).get("type", "")
        if kind not in ("title", "abstract"):
            continue
        if p["offset"] > len(text):
            text += " " * (p["offset"] - len(text))
        text += p["text"]
        if kind == "title":
            title = p["text"]
        elif p["text"].strip():
            has_abstract = True
    genes = []
    for p in doc["passages"]:
        for a in p.get("annotations", []):
            inf = a.get("infons", {})
            if inf.get("type") != "Gene":
                continue
            ids = [x for x in str(inf.get("identifier") or "").replace(",", ";").split(";") if x.strip().isdigit()]
            for loc in a.get("locations", []):
                start, end = loc["offset"], loc["offset"] + loc["length"]
                if end <= len(text):
                    genes.append({"gene_ids": ids, "text": a.get("text"), "start": start, "end": end,
                                  "homologene": inf.get("ncbi_homologene")})
    return {"title": title, "text": text, "has_abstract": has_abstract, "genes": genes}
