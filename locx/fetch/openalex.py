"""OpenAlex: disambiguated authors (OpenAlex author ID, ORCID when known) and their institutions (ROR IDs) for the
corpus papers, by PMID. Used instead of our own name keys to identify people (DECISIONS 2026-11-19).

One request per 100 PMIDs (`filter=pmid:a|b|...`, only the id/ids/authorships fields), cached as JSON under
data/raw/openalex/ and never fetched twice. No contact details are sent.
"""
import hashlib
import json
import time

import requests

from locx.config import INTERIM, RAW
from locx.io import read_jsonl

URL = "https://api.openalex.org/works"
CACHE = RAW / "openalex"
BATCH = 100
PAUSE = 0.5


def _get(params, retries=5):
    for attempt in range(retries + 1):
        try:
            r = requests.get(URL, params=params, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.ConnectionError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError as e:
            if attempt == retries:
                raise
            wait = 10 * 2 ** attempt
            print(f"[openalex] {e}; waiting {wait} s", flush=True)
            time.sleep(wait)


def fetch(pmids=None) -> dict:
    """PMID -> OpenAlex work record (id, ids, authorships) for every PMID OpenAlex knows."""
    if pmids is None:
        pmids = [p["pmid"] for p in read_jsonl(INTERIM / "papers.jsonl")]
    pmids = sorted(set(pmids), key=int)
    CACHE.mkdir(parents=True, exist_ok=True)
    out, t = {}, time.time()
    for i in range(0, len(pmids), BATCH):
        chunk = pmids[i:i + BATCH]
        path = CACHE / f"works_{hashlib.sha1(','.join(chunk).encode()).hexdigest()[:16]}.json"
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = _get({"filter": "pmid:" + "|".join(chunk), "select": "id,ids,authorships", "per-page": 200})
            part = path.with_name(path.name + ".part")
            part.write_text(json.dumps(data))
            part.rename(path)
            time.sleep(PAUSE)
        for w in data["results"]:
            pm = (w.get("ids") or {}).get("pmid", "").rsplit("/", 1)[-1]
            if pm in chunk and pm not in out:
                out[pm] = w
        if (i // BATCH) % 100 == 99:
            print(f"[openalex] {min(i + BATCH, len(pmids))}/{len(pmids)} PMIDs, {len(out)} found ({time.time() - t:.0f} s)",
                  flush=True)
    print(f"[openalex] {len(out)}/{len(pmids)} papers found in OpenAlex ({time.time() - t:.0f} s)")
    return out


if __name__ == "__main__":
    fetch()
