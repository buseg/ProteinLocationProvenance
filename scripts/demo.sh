#!/usr/bin/env bash
# Streamlit demo (SPEC M11): start | stop | status. Binds 127.0.0.1:8501 only (Buse: SSH tunnel, laptop port 8502).
set -euo pipefail
cd "$(dirname "$0")/.."
MM="${MAMBA_EXE:-$HOME/.local/bin/micromamba}"
PIDFILE=data/demo.pid
LOG=logs/demo.log
running() { [[ -f $PIDFILE ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; }
case "${1:-}" in
  start)
    if running; then echo "[demo] already running (pid $(cat $PIDFILE))"; exit 0; fi
    mkdir -p logs data
    setsid nohup "$MM" run -n locx streamlit run app/v2.py --server.address 127.0.0.1 --server.port 8501 \
      --server.headless true --browser.gatherUsageStats false >> $LOG 2>&1 < /dev/null &
    echo $! > $PIDFILE
    for _ in $(seq 30); do
      curl -sf http://127.0.0.1:8501/_stcore/health >/dev/null && { echo "[demo] up on 127.0.0.1:8501 (pid $(cat $PIDFILE))"; exit 0; }
      running || { echo "[demo] died on start, see $LOG"; tail -20 $LOG; exit 1; }
      sleep 1
    done
    echo "[demo] not up after 30 s, see $LOG"; exit 1 ;;
  stop)
    if ! running; then echo "[demo] not running"; rm -f $PIDFILE; exit 0; fi
    pkill -TERM -P "$(cat $PIDFILE)" 2>/dev/null || true; kill "$(cat $PIDFILE)" 2>/dev/null || true
    rm -f $PIDFILE; echo "[demo] stopped" ;;
  status) running && echo "[demo] running (pid $(cat $PIDFILE))" || echo "[demo] not running" ;;
  *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac
