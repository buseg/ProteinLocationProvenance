#!/usr/bin/env bash
# Pack the Docker demo into one file to copy to another machine (docker/demo/README.md):
#   code the demo needs + compose files + reports/ + the graph export (scripts/demo_export.py).
# Never includes .env, data/raw, data/interim or logs.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-data/demo_bundle/locx_demo.tar.gz}
[[ -f data/demo_export/graphs.tsv ]] || { echo "[bundle] run 'make demo-export' first"; exit 1; }
cut -f2 data/demo_export/graphs.tsv | while read -r f; do
  [[ -f data/demo_export/$f ]] || { echo "[bundle] data/demo_export/$f missing"; exit 1; }
done
mkdir -p "$(dirname "$OUT")"
tar czf "$OUT" --exclude=__pycache__ --exclude='*.pyc' --transform 's|^|locx_demo/|' \
  compose.yaml .dockerignore docker/demo config.yaml .streamlit locx queries app reports data/rdf/loaded.json \
  data/demo_export/graphs.tsv $(cut -f2 data/demo_export/graphs.tsv | sed 's|^|data/demo_export/|')
echo "[bundle] $OUT ($(( $(stat -c %s "$OUT") / 1000000 )) MB); on the other machine: tar xzf $(basename "$OUT") && cd locx_demo && docker compose up --build"
