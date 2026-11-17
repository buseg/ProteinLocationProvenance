#!/usr/bin/env bash
# Validate (M6) each expansion-3 year run as soon as the extract loop reports it done; CPU only.
cd "$(dirname "$0")/.."
while true; do
  for r in $(grep -oP 'extract \d+: done \(\K[^)]+' logs/years_extract.log); do
    if [ ! -e reports/validation_$r.json ]; then
      ~/.local/bin/micromamba run -n locx python -u -m locx.extract.validate --run-id $r > logs/years/validate_$r.log 2>&1 \
        && echo "[$(date +%H:%M)] validated $r" || echo "[$(date +%H:%M)] validation FAILED $r"
    fi
  done
  grep -q "extract: all years done" logs/years_extract.log && break
  sleep 300
done
echo "[$(date +%H:%M)] all year runs validated"
