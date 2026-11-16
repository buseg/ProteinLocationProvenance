"""Human Swiss-Prot entries as TSV (one streamed request, cached)."""
from locx.config import RAW
from locx.io import download

URL = "https://rest.uniprot.org/uniprotkb/stream"
FIELDS = "accession,id,gene_primary,gene_synonym,protein_name,xref_geneid,cc_subcellular_location,ft_transmem,ft_signal"


def fetch():
    params = {"query": "organism_id:9606 AND reviewed:true", "format": "tsv", "fields": FIELDS, "compressed": "true"}
    return download(URL, RAW / "uniprot" / "human_swissprot.tsv.gz", params=params)
