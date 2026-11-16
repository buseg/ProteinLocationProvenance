"""Small I/O helpers: cached downloads, JSONL."""
import json
import time
from pathlib import Path

import requests


def download(url: str, dest: Path, params: dict | None = None, timeout: int = 600) -> Path:
    """Download once into data/raw/. Writes to a .part file first, so a partial file never counts as done."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[cache] {dest.relative_to(dest.parents[2])} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    t = time.time()
    with requests.get(url, params=params, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    part.rename(dest)
    print(f"[download] {url} -> {dest.name} ({dest.stat().st_size / 1e6:.1f} MB, {time.time() - t:.0f} s)")
    return dest


def read_jsonl(path: Path):
    with open(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n
