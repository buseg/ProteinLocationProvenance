#!/usr/bin/env bash
# vLLM without Docker: start | stop | smoke. Env "vllm" (scripts/setup_vllm_env.sh), one GPU per server.
# Second server: GPU=2 PORT=8001 scripts/serve_vllm.sh start.
set -euo pipefail
cd "$(dirname "$0")/.."
MM="${MAMBA_EXE:-$HOME/.local/bin/micromamba}"
cfg() { sed -n "s/^ *$1: *\([^ #]*\).*/\1/p" config.yaml | head -1; }
GPU="${GPU:-$(cfg gpu)}"
MODEL="$(cfg model)"
NAME="$(cfg served_name)"
PORT="${PORT:-$(cfg endpoint | sed -n 's#.*:\([0-9]*\)/v1#\1#p')}"
SUFFIX=""; [[ "$PORT" != 8000 ]] && SUFFIX="_$PORT"   # second server (e.g. GPU 2, port 8001)
PIDFILE=data/vllm$SUFFIX.pid
LOG=logs/vllm$SUFFIX.log
set -a; . ./.env; set +a
running() { [[ -f $PIDFILE ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; }

case "${1:-}" in
  start)
    if running; then echo "[vllm] already running (pid $(cat $PIDFILE))"; exit 0; fi
    [[ -n "${VLLM_API_KEY:-}" ]] || { echo "[vllm] set VLLM_API_KEY in .env"; exit 1; }
    mkdir -p logs data
    # VLLM_API_KEY is read from the environment by vllm serve (keeps it out of argv / ps)
    CUDA_VISIBLE_DEVICES="$GPU" nohup "$MM" run -n vllm vllm serve "$MODEL" \
      --served-model-name "$NAME" --host 127.0.0.1 --port "$PORT" \
      --max-model-len 8192 --gpu-memory-utilization 0.90 \
      --limit-mm-per-prompt '{"image": 0}' >> $LOG 2>&1 &
    echo $! > $PIDFILE
    echo "[vllm] starting on GPU $GPU, 127.0.0.1:$PORT (pid $(cat $PIDFILE)); waiting for /v1/models (loading takes minutes)"
    for _ in $(seq 180); do
      curl -sf -H "Authorization: Bearer $VLLM_API_KEY" "http://localhost:$PORT/v1/models" >/dev/null && { echo "[vllm] ready"; exit 0; }
      running || { echo "[vllm] died on start, see $LOG"; tail -30 $LOG; exit 1; }
      sleep 5
    done
    echo "[vllm] not ready after 15 min, see $LOG"; exit 1
    ;;
  stop)
    if ! running; then echo "[vllm] not running"; rm -f $PIDFILE; exit 0; fi
    pkill -TERM -P "$(cat $PIDFILE)" 2>/dev/null || true; kill "$(cat $PIDFILE)" 2>/dev/null || true
    for _ in $(seq 60); do running || { rm -f $PIDFILE; echo "[vllm] stopped"; exit 0; }; sleep 1; done
    echo "[vllm] still running (pid $(cat $PIDFILE))"; exit 1
    ;;
  smoke)
    python3 - "$PORT" "$NAME" <<'PY'
import json, os, sys, time, urllib.request
port, name = sys.argv[1], sys.argv[2]
key = os.environ["VLLM_API_KEY"]
def call(path, body=None):
    req = urllib.request.Request(f"http://localhost:{port}{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))
models = [m["id"] for m in call("/v1/models")["data"]]
print("[smoke] /v1/models:", models); assert name in models
schema = {"type": "object", "properties": {
    "protein": {"enum": ["P1", "P2"]}, "location": {"enum": ["L1", "L2"]},
    "polarity": {"enum": ["present", "absent"]}},
    "required": ["protein", "location", "polarity"], "additionalProperties": False}
body = {"model": name, "temperature": 0, "max_tokens": 100,
        "messages": [{"role": "user", "content":
            "Sentence: 'TFEB translocates to the nucleus upon starvation.'\n"
            "Proteins: P1 = TFEB, P2 = MTOR. Locations: L1 = nucleus, L2 = lysosome.\n"
            "Return the localization claim as JSON."}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "claim", "schema": schema}}}
t = time.time(); r = call("/v1/chat/completions", body); dt = time.time() - t
out = json.loads(r["choices"][0]["message"]["content"])
ok = set(out) == set(schema["required"]) and all(out[k] in schema["properties"][k]["enum"] for k in out)
print(f"[smoke] output: {out}  schema-valid: {ok}  latency: {dt:.2f}s  usage: {r['usage']}")
assert ok
print("[smoke] PASS")
PY
    ;;
  *) echo "usage: $0 start|stop|smoke"; exit 2 ;;
esac
