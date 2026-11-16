"""Human Swiss-Prot entries as TSV (one streamed request, cached)."""
from locx.config import RAW
from locx.io import download

URL = "https://rest.uniprot.org/uniprotkb/stream"
FIELDS = "accession,id,gene_primary,gene_synonym,protein_name,xref_geneid,cc_subcellular_location,ft_transmem,ft_signal"


def fetch():
    params = {"query": "organism_id:9606 AND reviewed:true", "format": "tsv", "fields": FIELDS, "compressed": "true"}
    return download(URL, RAW / "uniprot" / "human_swissprot.tsv.gz", params=params)


def gene_to_accessions() -> dict[str, list[str]]:
    """NCBI GeneID -> human Swiss-Prot accessions (a GeneID can map to several entries)."""
    import csv
    import gzip
    from collections import defaultdict
    out = defaultdict(list)
    with gzip.open(fetch(), "rt", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            for g in r["GeneID"].split(";"):
                if g.strip():
                    out[g.strip()].append(r["Entry"])
    return dict(out)
