#!/usr/bin/env bash
# Fuseki without Docker: build (download + verify) | up | down | status. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
FUSEKI_VERSION=6.2.0
DIST=data/fuseki/dist/apache-jena-fuseki-$FUSEKI_VERSION
BASE=data/fuseki/base
PIDFILE=data/fuseki/fuseki.pid
LOG=logs/fuseki.log
PORT=$(sed -n 's#^ *base: *http://localhost:\([0-9]*\).*#\1#p' config.yaml)

running() { [[ -f $PIDFILE ]] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; }

case "${1:-}" in
  build)
    if [[ -x $DIST/fuseki-server ]]; then echo "[fuseki] $FUSEKI_VERSION already installed"; exit 0; fi
    mkdir -p data/fuseki/dist && cd data/fuseki/dist
    T=apache-jena-fuseki-$FUSEKI_VERSION.tar.gz
    # dlcdn is fast; the checksum comes from downloads.apache.org (archive.apache.org is throttled)
    curl -sSfL -o $T https://dlcdn.apache.org/jena/binaries/$T \
      || curl -sSfL -o $T https://archive.apache.org/dist/jena/binaries/$T
    curl -sSfL -o $T.sha512 https://downloads.apache.org/jena/binaries/$T.sha512 \
      || curl -sSfL -o $T.sha512 https://archive.apache.org/dist/jena/binaries/$T.sha512
    echo "$(awk '{print $1}' $T.sha512)  $T" | sha512sum -c
    tar xzf $T && echo "[fuseki] installed $FUSEKI_VERSION"
    ;;
  up)
    if running; then echo "[fuseki] already running (pid $(cat $PIDFILE))"; exit 0; fi
    [[ -f .env ]] || { echo "[fuseki] .env missing (copy .env.example)"; exit 1; }
    set -a; . ./.env; set +a
    [[ -n "${FUSEKI_ADMIN_PASSWORD:-}" && "$FUSEKI_ADMIN_PASSWORD" != change-me ]] \
      || { echo "[fuseki] set FUSEKI_ADMIN_PASSWORD in .env"; exit 1; }
    mkdir -p $BASE data/fuseki/databases logs
    ( umask 077; sed "s|\${FUSEKI_ADMIN_PASSWORD}|$FUSEKI_ADMIN_PASSWORD|" docker/fuseki/shiro.ini.template > $BASE/shiro.ini )
    FUSEKI_BASE=$PWD/$BASE JVM_ARGS="${JVM_ARGS:--Xmx8g}" nohup $DIST/fuseki-server \
      --config=docker/fuseki/config.ttl --shiro=$BASE/shiro.ini --localhost --port "$PORT" \
      >> $LOG 2>&1 &
    echo $! > $PIDFILE
    for _ in $(seq 60); do
      curl -sf "http://localhost:$PORT/\$/ping" >/dev/null && { echo "[fuseki] up on 127.0.0.1:$PORT (pid $(cat $PIDFILE))"; exit 0; }
      running || { echo "[fuseki] died on start, see $LOG"; tail -20 $LOG; exit 1; }
      sleep 1
    done
    echo "[fuseki] no ping after 60 s, see $LOG"; exit 1
    ;;
  down)
    if ! running; then echo "[fuseki] not running"; rm -f $PIDFILE; exit 0; fi
    kill "$(cat $PIDFILE)"
    for _ in $(seq 30); do running || { rm -f $PIDFILE; echo "[fuseki] stopped"; exit 0; }; sleep 1; done
    echo "[fuseki] still running after 30 s (pid $(cat $PIDFILE))"; exit 1
    ;;
  status)
    if running; then echo "[fuseki] running (pid $(cat $PIDFILE)) on 127.0.0.1:$PORT"; else echo "[fuseki] not running"; fi
    ;;
  *) echo "usage: $0 build|up|down|status"; exit 2 ;;
esac
