#!/bin/sh
# Fuseki container: on the first start, load the exported graphs (data/demo_export/*.nq.gz) into TDB2 and
# check the counts against graphs.tsv; then serve the dataset read-only. Paths can be overridden for testing.
set -eu
FUSEKI_HOME=${FUSEKI_HOME:-/opt/fuseki}
DATA=${DATA:-/data}
DB=${DB:-/fuseki/databases/locx}
RUN=${RUN:-/fuseki/run}
CONF=${CONF:-/fuseki/config.ttl}
PORT=${PORT:-3030}
FUSEKI_ARGS=${FUSEKI_ARGS:-}          # extra server flags, e.g. --localhost when testing outside Docker
JVM_ARGS=${JVM_ARGS:--Xmx4g}
HERE=$(cd "$(dirname "$0")" && pwd)

if [ ! -f "$DB.loaded" ]; then
  [ -f "$DATA/graphs.tsv" ] || { echo "[fuseki] $DATA/graphs.tsv missing: put the export in data/demo_export (see docker/demo/README.md)"; exit 1; }
  if [ -d "$DB" ] && [ -n "$(ls -A "$DB")" ]; then
    echo "[fuseki] $DB holds an unfinished load; reset with 'docker compose down -v' and start again"; exit 1
  fi
  mkdir -p "$DB"
  echo "[fuseki] first start: loading $(wc -l < "$DATA/graphs.tsv") graphs into TDB2 (takes a few minutes) ..."
  # shellcheck disable=SC2086
  java $JVM_ARGS -cp "$FUSEKI_HOME/fuseki-server.jar" tdb2.tdbloader --loc "$DB" $(cut -f2 "$DATA/graphs.tsv" | sed "s|^|$DATA/|")
  echo "[fuseki] checking triple counts ..."
  T=$(mktemp -d)
  # shellcheck disable=SC2086
  java $JVM_ARGS -cp "$FUSEKI_HOME/fuseki-server.jar" tdb2.tdbquery --loc "$DB" --results=tsv \
    'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g' \
    | tail -n +2 | tr -d '<>' | sort > "$T/loaded"
  cut -f1,3 "$DATA/graphs.tsv" | sort > "$T/expected"
  if ! cmp -s "$T/loaded" "$T/expected"; then
    echo "[fuseki] loaded counts differ from graphs.tsv:"; diff "$T/expected" "$T/loaded" || true; exit 1
  fi
  rm -rf "$T"
  touch "$DB.loaded"
  echo "[fuseki] loaded and checked: $(awk -F'\t' '{s+=$3} END {print s}' "$DATA/graphs.tsv") triples"
fi

mkdir -p "$RUN"
PW=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
( umask 077; sed "s|@ADMIN_PASSWORD@|$PW|" "$HERE/shiro.ini.template" > "$RUN/shiro.ini" )
export FUSEKI_BASE="$RUN" JVM_ARGS
# shellcheck disable=SC2086
exec "$FUSEKI_HOME/fuseki-server" --config="$CONF" --shiro="$RUN/shiro.ini" --port "$PORT" $FUSEKI_ARGS
