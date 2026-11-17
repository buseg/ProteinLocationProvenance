"""Incremental expansion-3 pipeline in two independent loops (decisions 2026-11-16):

  python scripts/years_pipeline.py prep    2015 2026   # CPU: corpus slice (from cache) + synonym candidates
  python scripts/years_pipeline.py extract 2015 2026   # GPU: prompt v3 extraction, one year at a time

prep waits until the running corpus build (logs/expand3.log) has finished year Y, rebuilds Y's slice from the
cache (no API calls), builds candidates with the synonym layer and writes data/interim/years/Y.ready.
extract waits for Y.ready, skips a year whose run has ended, waits while any extraction is running (GPUs 1+2
are shared by one run at a time), resumes an interrupted run, else starts a run seeded per abstract.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MM = str(Path.home() / ".local/bin/micromamba")
PY = [MM, "run", "-n", "locx", "python", "-u"]
SEED = "gemma4-31b_20261116-2038"
YEARS = ROOT / "data/interim/years"
LOGS = ROOT / "logs/years"


def log(msg):
    print(f"[{time.strftime('%H:%M')}] {msg}", flush=True)


def corpus_done(y):
    p = ROOT / "logs/expand3.log"
    return p.exists() and any(line.startswith(f"[discovery] {y}:") for line in p.open())


def run(cmd, logfile):
    with open(logfile, "a") as f:
        return subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode


def cands(y):
    return f"data/interim/candidates.expanded3_y{y}.jsonl"


def prep(y0, y1):
    YEARS.mkdir(parents=True, exist_ok=True)
    for y in range(y0, y1 + 1):
        ready = YEARS / f"{y}.ready"
        if ready.exists():
            log(f"prep {y}: already ready")
            continue
        while not corpus_done(y):
            time.sleep(60)
        log(f"prep {y}: corpus slice + candidates")
        lf = LOGS / f"{y}.prep.log"
        if run(PY + ["-m", "locx.corpus", "--no-silver", "--discovery", "0", "--years", str(y), str(y),
                     "--no-protein-filter", "--suffix", f"expanded3_y{y}"], lf) or \
           run(PY + ["-m", "locx.extract.candidates", "--papers", f"data/interim/papers.expanded3_y{y}.jsonl",
                     "--synonyms", "--suffix", f"expanded3_y{y}"], lf):
            log(f"prep {y}: FAILED, see {lf}")
            sys.exit(1)
        ready.touch()
        log(f"prep {y}: ready")


def run_for(y):
    """The extraction run whose input is year y's candidates, if any: (run_id, ended)."""
    found = None
    for d in sorted((ROOT / "data/runs").iterdir()):
        m = d / "run.json"
        if m.exists():
            meta = json.loads(m.read_text())
            if meta.get("input") == cands(y):
                found = (meta["run_id"], bool(meta.get("ended")))
    return found


def extraction_running():
    return subprocess.run(["pgrep", "-u", "buse", "-f", r"^python -u -m locx\.extract\.run"],
                          stdout=subprocess.DEVNULL).returncode == 0


def extract(y0, y1):
    for y in range(y0, y1 + 1):
        while not (YEARS / f"{y}.ready").exists():
            time.sleep(60)
        while True:
            r = run_for(y)
            if r and r[1]:
                log(f"extract {y}: done ({r[0]})")
                break
            if extraction_running():
                time.sleep(60)
                continue
            lf = LOGS / f"{y}.extract.log"
            if r:
                log(f"extract {y}: resuming {r[0]}")
                cmd = PY + ["-m", "locx.extract.run", "--run-id", r[0]]
            else:
                log(f"extract {y}: starting (seeded from {SEED})")
                cmd = PY + ["-m", "locx.extract.run", "--tiers", "silver,discovery", "--candidates", cands(y),
                            "--seed-from", SEED]
            if run(cmd, lf):
                log(f"extract {y}: FAILED, see {lf}")
                sys.exit(1)
    log("extract: all years done")


if __name__ == "__main__":
    mode, y0, y1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    LOGS.mkdir(parents=True, exist_ok=True)
    prep(y0, y1) if mode == "prep" else extract(y0, y1)
