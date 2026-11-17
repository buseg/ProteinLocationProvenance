#!/usr/bin/env bash
# Incremental expansion-3 extraction (decisions 2026-11-16): as soon as the corpus build (logs/expand3.log)
# has finished a discovery year, rebuild that year's slice from the cache (no API calls), add the synonym
# layer and extract it with prompt v3 on both GPUs. Years run one after another.
#   scripts/extract_years.sh 2015 2026
set -uo pipefail
cd "$(dirname "$0")/.."
MM="${MAMBA_EXE:-$HOME/.local/bin/micromamba}"
PY="$MM run -n locx python -u"
SEED=gemma4-31b_20261116-2038
mkdir -p logs/years
for Y in $(seq "${1:-2015}" "${2:-2026}"); do
  until grep -q "^\[discovery\] $Y:" logs/expand3.log; do sleep 60; done
  if grep -q "^\[extract\] run .* -> \|^\[years\] $Y done" logs/years/$Y.log 2>/dev/null && grep -q "^\[years\] $Y done" logs/years/$Y.log; then
    echo "[years] $Y already done, skipping"; continue
  fi
  echo "[years] $Y: corpus slice + candidates + extraction ($(date +%H:%M))"
  { $PY -m locx.corpus --no-silver --discovery 0 --years $Y $Y --no-protein-filter --suffix expanded3_y$Y &&
    $PY -m locx.extract.candidates --papers data/interim/papers.expanded3_y$Y.jsonl --synonyms --suffix expanded3_y$Y &&
    $PY -m locx.extract.run --tiers silver,discovery --candidates data/interim/candidates.expanded3_y$Y.jsonl --seed-from $SEED &&
    echo "[years] $Y done ($(date +%H:%M))"; } >> logs/years/$Y.log 2>&1 || { echo "[years] $Y FAILED, see logs/years/$Y.log"; exit 1; }
  grep "^\[extract\] run \|^\[extract\] status\|^\[throughput\]\|^\[years\]" logs/years/$Y.log | tail -4
done
echo "[years] all years done ($(date +%H:%M))"
