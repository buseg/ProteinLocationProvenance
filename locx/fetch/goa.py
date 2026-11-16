"""GOA human GAF 2.2: download and parse the cellular component (aspect C) rows."""
import gzip

from locx.config import RAW
from locx.io import download

# current.geneontology.org is fast here; the EBI FTP mirror took ~11 s per request in M0
URL = "http://current.geneontology.org/annotations/goa_human.gaf.gz"
MIRROR = "https://ftp.ebi.ac.uk/pub/databases/GO/goa/HUMAN/goa_human.gaf.gz"

COLS = ["db", "acc", "symbol", "qualifier", "go_id", "refs", "evidence", "with_from", "aspect",
        "name", "synonyms", "type", "taxon", "date", "assigned_by", "extension", "product_form"]


def fetch():
    dest = RAW / "goa" / "goa_human.gaf.gz"
    try:
        return download(URL, dest)
    except Exception as e:  # noqa: BLE001 - fall back to the mirror on any network error
        print(f"[goa] primary failed ({e}); trying EBI mirror")
        return download(MIRROR, dest)


def header(path):
    """The '!' header lines (release date, GO version)."""
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            if not line.startswith("!"):
                break
            out.append(line[1:].strip())
    return out


def rows(path):
    """Yields (raw_line, dict) for every aspect-C row."""
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("!") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            parts += [""] * (len(COLS) - len(parts))
            row = dict(zip(COLS, parts))
            if row["aspect"] == "C":
                yield line.rstrip("\n"), row
