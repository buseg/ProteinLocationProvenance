"""Second protein layer (decisions 2026-11-16): check every PubTator gene mention against an index of
human Swiss-Prot gene symbols and synonyms. When the mention text names several human proteins, or a
different protein than PubTator chose, all readings become candidates, marked as alternatives for that
name; the LLM picks the one the context means (prompt v3). PubTator still finds the mentions and decides
the species; this layer only widens the choice for human mentions.

Index keys are normalized (lower case, no spaces/hyphens/underscores). Readings per name are capped
(tagger's choice first, then the rest by accession) so families like AMPK do not flood the candidates.
"""
import csv
import gzip
import re
from collections import defaultdict

from locx.fetch import uniprot

MAX_READINGS = 4


def norm(text: str) -> str:
    return re.sub(r"[\s\-_]", "", (text or "").lower())


class SynonymIndex:
    def __init__(self):
        self.index = defaultdict(set)   # normalized symbol/synonym -> {accession}
        self.names = {}                 # accession -> recommended protein name
        with gzip.open(uniprot.fetch(), "rt", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                acc = r["Entry"]
                self.names[acc] = re.split(r"\s*[\(\[]", r["Protein names"], maxsplit=1)[0].strip()
                for field in (r["Gene Names (primary)"], r["Gene Names (synonym)"]):
                    for tok in re.split(r"[;\s]+", field):
                        if tok:
                            self.index[norm(tok)].add(acc)

    def readings(self, text: str, tagger_accs) -> list[str] | None:
        """Accessions to offer for this mention, tagger's choice first; None if there is nothing to add."""
        hits = self.index.get(norm(text), set())
        tagger = [a for a in dict.fromkeys(tagger_accs)]
        if len(hits) > 1 or (len(hits) == 1 and not hits & set(tagger)):
            rest = sorted(hits - set(tagger))
            out = tagger + rest
            return out[:max(MAX_READINGS, len(tagger))]
        return None
