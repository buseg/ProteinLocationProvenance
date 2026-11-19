"""Export the loaded named graphs for the Docker demo (docker/demo/README.md).

  python scripts/demo_export.py [--out data/demo_export]

Reads every graph listed in data/rdf/loaded.json from Fuseki (Graph Store Protocol GET, read-only, no
password), writes it as gzipped N-Quads (one file per graph, graph IRI in the 4th column) and checks the
number of quads against the live triple count. graphs.tsv lists graph, file and count; the Fuseki
container checks its load against it.
"""
import argparse
import gzip
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx.config import DATA, RDF  # noqa: E402
from locx.kg import fuseki  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "demo_export"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    graphs = list(json.loads((RDF / "loaded.json").read_text()))
    rows = []
    for g in graphs:
        t0, n_live = time.time(), fuseki.count(g)
        name = re.sub(r"[^A-Za-z0-9]+", "_", g.removeprefix("urn:locx:graph:")).strip("_") + ".nq.gz"
        tail = f" <{g}> .\n".encode()
        n = 0
        with requests.get(f"{fuseki.BASE}/get", params={"graph": g}, headers={"Accept": "application/n-triples"},
                          stream=True, timeout=3600) as r, gzip.open(out / (name + ".part"), "wb", compresslevel=6) as f:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if not line.endswith(b" ."):
                    sys.exit(f"[export] unexpected N-Triples line in {g}: {line[:120]!r}")
                f.write(line[:-2] + tail)
                n += 1
        if n != n_live:
            sys.exit(f"[export] {g}: wrote {n} quads, Fuseki counts {n_live}")
        (out / (name + ".part")).rename(out / name)
        rows.append((g, name, n))
        print(f"[export] {g}: {n:,} quads -> {name} ({(out / name).stat().st_size / 1e6:.0f} MB, {time.time() - t0:.0f} s)")
    (out / "graphs.tsv").write_text("".join(f"{g}\t{f}\t{n}\n" for g, f, n in rows))
    print(f"[export] {sum(n for *_, n in rows):,} quads in {len(rows)} graphs -> {out}")


if __name__ == "__main__":
    main()
