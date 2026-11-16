"""GO basic (go-basic.obo)."""
from locx.config import RAW
from locx.io import download

URL = "http://purl.obolibrary.org/obo/go/go-basic.obo"


def fetch():
    return download(URL, RAW / "go" / "go-basic.obo")
