"""Independent author groups per assertion.

Two supporting papers are in the same group if they share an ORCID or at least two author name
keys (ASCII-folded last name + first initial). Groups are connected components (union-find) over
the supporting papers of ONE assertion, not over the corpus (common names would chain unrelated
labs). Every author contributes a name key; authors with an ORCID also contribute the ORCID, so a
person listed once with and once without an ORCID can still link via names.
Authors without ORCID are not disambiguated: counts are approximate.
"""
import re
import unicodedata


def name_key(a: dict) -> str | None:
    last = a.get("last_name") or (a.get("name") or "").split(" ")[0]
    first = (a.get("initials") or a.get("first_name") or "")[:1]
    key = unicodedata.normalize("NFKD", f"{last}_{first}").encode("ascii", "ignore").decode().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return key or None


def paper_keys(paper: dict) -> tuple[set, set]:
    orcids, names = set(), set()
    for a in paper.get("authors") or []:
        if a.get("collective"):
            continue
        if a.get("orcid"):
            orcids.add(a["orcid"])
        k = name_key(a)
        if k:
            names.add(k)
    return orcids, names


def groups(pmids, papers: dict) -> dict[str, int]:
    """{pmid: group index 1..k}, groups numbered by their earliest PMID (stable)."""
    pmids = sorted(set(pmids), key=int)
    parent = {p: p for p in pmids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    keys = {p: paper_keys(papers.get(p, {})) for p in pmids}
    for i, p in enumerate(pmids):
        for q in pmids[i + 1:]:
            (o1, n1), (o2, n2) = keys[p], keys[q]
            if (o1 & o2) or len(n1 & n2) >= 2:
                parent[find(p)] = find(q)
    roots, out = {}, {}
    for p in pmids:
        r = find(p)
        roots.setdefault(r, len(roots) + 1)
        out[p] = roots[r]
    return out
