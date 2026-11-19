"""Loads config.yaml and .env (secrets stay in .env, never in config.yaml)."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
RDF = DATA / "rdf"
REPORTS = ROOT / "reports"
QUERIES = ROOT / "queries"

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
# the Docker demo (compose.yaml) points the app at its own Fuseki container
if os.environ.get("LOCX_FUSEKI_BASE"):
    CFG["fuseki"]["base"] = os.environ["LOCX_FUSEKI_BASE"].rstrip("/")


def secret(name: str) -> str:
    """Value from the environment, else from .env."""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip()
    raise KeyError(f"{name} not set (environment or .env)")
