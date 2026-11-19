"""Europe PMC REST: search (cursor paging) and metadata by PMID. All responses cached under data/raw/europepmc/."""
import hashlib
import html
import json
import re
import time

from locx.config import RAW
from locx.io import get_json

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CACHE = RAW / "europepmc"
PAUSE = 1.0


def _cached_page(key: str, page: int, params: dict) -> dict:
    path = CACHE / key / f"page_{page:04d}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = get_json(URL, params=params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    time.sleep(PAUSE)
    return data


def search(query: str, limit: int, page_size: int = 1000) -> tuple[int, list[dict]]:
    """Core records in Europe PMC's default (relevance) order, up to `limit`. Returns (hitCount, records)."""
    key = "search_" + hashlib.sha1(f"{query}|{page_size}".encode()).hexdigest()[:16]
    (CACHE / key).mkdir(parents=True, exist_ok=True)
    (CACHE / key / "query.txt").write_text(query)
    records, cursor, page, hits = [], "*", 0, 0
    while len(records) < limit:
        data = _cached_page(key, page, {"query": query, "format": "json", "resultType": "core",
                                        "pageSize": min(page_size, 1000), "cursorMark": cursor})
        hits = data["hitCount"]
        batch = data["resultList"]["result"]
        records += batch
        nxt = data.get("nextCursorMark")
        if not batch or not nxt or nxt == cursor:
            break
        cursor, page = nxt, page + 1
    return hits, records[:limit]


def by_pmids(pmids: list[str], batch: int = 100) -> dict[str, dict]:
    """Core records for PMIDs (SRC:MED), in batches of `batch` PMIDs per query."""
    out = {}
    pmids = sorted(set(pmids), key=int)
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        key = "pmids_" + hashlib.sha1(",".join(chunk).encode()).hexdigest()[:16]
        q = f"EXT_ID:({' OR '.join(chunk)}) AND SRC:MED"
        data = _cached_page(key, 0, {"query": q, "format": "json", "resultType": "core", "pageSize": 1000})
        for rec in data["resultList"]["result"]:
            if rec.get("pmid") in chunk:
                out[rec["pmid"]] = rec
        if (i // batch) % 10 == 9:
            print(f"[europepmc] metadata {min(i + batch, len(pmids))}/{len(pmids)}")
    return out


TAG = re.compile(r"<[^>]+>")


def clean(text: str | None) -> str | None:
    return html.unescape(TAG.sub("", text)).strip() if text else text


def journal(rec: dict) -> dict | None:
    """Journal identity from a core record: NLM Catalog ID, ISSN, eISSN, title, NLM abbreviation."""
    j = rec.get("journalInfo", {}).get("journal", {})
    if not j:
        return None
    return {"nlmid": j.get("nlmid"), "issn": j.get("issn"), "essn": j.get("essn"), "title": j.get("title"),
            "abbrev": j.get("medlineAbbreviation") or j.get("isoabbreviation")}


def record_index(pmids: set[str]) -> dict[str, dict]:
    """PMID -> {"journal": journal identity, "counts": [[fetch date, citedByCount], ...]}, read from the cached core
    records (no new requests). The fetch date of a record is the date its cached page was written."""
    import datetime
    out = {}
    for page in sorted(CACHE.glob("*/page_*.json")):
        day = datetime.date.fromtimestamp(page.stat().st_mtime).isoformat()
        for rec in json.loads(page.read_text())["resultList"]["result"]:
            p = rec.get("pmid")
            if p not in pmids:
                continue
            e = out.setdefault(p, {"journal": None, "counts": []})
            e["journal"] = e["journal"] or journal(rec)
            if [day, rec.get("citedByCount", 0)] not in e["counts"]:
                e["counts"].append([day, rec.get("citedByCount", 0)])
    return out


def metadata(rec: dict) -> dict:
    authors = []
    for a in rec.get("authorList", {}).get("author", []):
        orcid = a.get("authorId", {}).get("value") if a.get("authorId", {}).get("type") == "ORCID" else None
        affs = [x.get("affiliation") for x in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])]
        authors.append({"name": a.get("fullName") or a.get("collectiveName"), "last_name": a.get("lastName"),
                        "first_name": a.get("firstName"), "initials": a.get("initials"), "orcid": orcid,
                        "affiliations": [x for x in affs if x], "collective": "collectiveName" in a})
    return {"pmid": rec.get("pmid"), "doi": rec.get("doi"), "epmc_title": clean(rec.get("title")),
            "year": int(rec["pubYear"]) if rec.get("pubYear", "").isdigit() else None,
            "date": rec.get("firstPublicationDate"),
            "journal": rec.get("journalInfo", {}).get("journal", {}).get("title"),
            "journal_ids": journal(rec),
            "cited_by": rec.get("citedByCount", 0),
            "pub_types": rec.get("pubTypeList", {}).get("pubType", []),
            "authors": authors}
