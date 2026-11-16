"""Fuseki helpers: Graph Store Protocol load, SPARQL select/ask/update. Writes need the admin password."""
import hashlib
import json
import time
from pathlib import Path

import requests

from locx.config import CFG, RDF, secret

BASE = f"{CFG['fuseki']['base']}/{CFG['fuseki']['dataset']}"
MANIFEST = RDF / "loaded.json"


def _auth():
    return (CFG["fuseki"]["user"], secret(CFG["fuseki"]["password_env"]))


def query(q: str) -> dict:
    r = requests.post(f"{BASE}/sparql", data={"query": q},
                      headers={"Accept": "application/sparql-results+json"}, timeout=600)
    r.raise_for_status()
    return r.json()


def select(q: str) -> list[dict]:
    return [{k: v["value"] for k, v in b.items()} for b in query(q)["results"]["bindings"]]


def ask(q: str) -> bool:
    return query(q)["boolean"]


def update(u: str) -> None:
    r = requests.post(f"{BASE}/update", data={"update": u}, auth=_auth(), timeout=3600)
    r.raise_for_status()


def count(graph: str) -> int:
    return int(select(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")[0]["n"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(graph: str, path: Path, replace: bool = False) -> int:
    """PUT a Turtle file into a named graph. Skips if this exact file is already loaded;
    refuses to overwrite a non-empty graph with different content unless replace=True."""
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    digest = sha256(path)
    n = count(graph)
    if n and manifest.get(graph, {}).get("sha256") == digest:
        print(f"[load] {graph}: already loaded ({n} triples), skipped")
        return n
    if n and not replace:
        raise SystemExit(f"[load] {graph} already has {n} triples from a different file; "
                         f"rerun with --replace to overwrite it")
    t = time.time()
    with open(path, "rb") as f:
        r = requests.put(f"{BASE}/data", params={"graph": graph}, data=f, auth=_auth(),
                         headers={"Content-Type": "text/turtle"}, timeout=3600)
    r.raise_for_status()
    n = count(graph)
    manifest[graph] = {"file": path.name, "sha256": digest, "triples": n,
                       "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(f"[load] {graph}: {n} triples from {path.name} ({time.time() - t:.0f} s)")
    return n
