#!/usr/bin/env bash
# M0b smoke test: write -> query -> restart -> query -> drop, on urn:locx:graph:test.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
PORT=$(sed -n 's#^ *base: *http://localhost:\([0-9]*\).*#\1#p' config.yaml)
F=http://localhost:$PORT
G=urn:locx:graph:test
auth() { curl -sS -K- "$@" <<< "user = \"admin:$FUSEKI_ADMIN_PASSWORD\""; }   # password via stdin, not argv
count() {
  curl -sS -G "$F/locx/sparql" -H 'Accept: application/sparql-results+json' \
    --data-urlencode "query=SELECT (COUNT(*) AS ?n) WHERE { GRAPH <$G> { ?s ?p ?o } }" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["results"]["bindings"][0]["n"]["value"])'
}
check() { [[ "$2" == "$3" ]] && echo "  ok   $1 ($2)" || { echo "  FAIL $1: got $2, want $3"; exit 1; }; }

echo "[smoke] ping: $(curl -sf $F/\$/ping)"
echo "[smoke] datasets: $(auth $F/\$/datasets | python3 -c 'import sys,json; print([d["ds.name"] for d in json.load(sys.stdin)["datasets"]])')"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$F/locx/data?graph=$G" -H 'Content-Type: text/turtle' --data '<urn:x> <urn:y> "z" .')
check "write without password is refused" "$code" 401
auth -o /dev/null -w '' -X POST "$F/locx/data?graph=$G" -H 'Content-Type: text/turtle' --data '<urn:locx:s> <urn:locx:p> "hello" .'
check "query after write" "$(count)" 1
./scripts/fuseki.sh down && ./scripts/fuseki.sh up
check "query after restart (persistence)" "$(count)" 1
auth -o /dev/null -X DELETE "$F/locx/data?graph=$G"
check "query after drop" "$(count)" 0
echo "[smoke] PASS"
