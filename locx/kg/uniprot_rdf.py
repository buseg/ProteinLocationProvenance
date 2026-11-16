"""Human Swiss-Prot TSV -> Turtle (proteins with names, gene symbols, NCBI GeneIDs)."""
import csv
import gzip

from locx.config import RDF
from locx.kg.ttl import PREFIXES, block, lit

COLS = {"Entry": "acc", "Entry Name": "entry_name", "Gene Names (primary)": "gene",
        "Gene Names (synonym)": "synonyms", "Protein names": "protein_names", "GeneID": "gene_ids",
        "Subcellular location [CC]": "location_text"}


def read(tsv_gz):
    with gzip.open(tsv_gz, "rt", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        missing = set(COLS) - set(reader.fieldnames)
        if missing:
            raise SystemExit(f"[uniprot] FAIL: TSV columns missing: {missing}; got {reader.fieldnames}")
        for r in reader:
            yield {v: r[k] for k, v in COLS.items()}


def build(tsv_gz):
    out = RDF / "uniprot_human.ttl"
    n = n_gene = n_multi = 0
    with open(out, "w") as f:
        f.write(PREFIXES)
        for r in read(tsv_gz):
            n += 1
            gene_ids = [g for g in r["gene_ids"].split(";") if g.strip()]
            n_gene += bool(gene_ids)
            n_multi += len(gene_ids) > 1
            main_name = r["protein_names"].split(" (")[0]
            pairs = [("a", "locx:Protein"),
                     ("locx:entryName", lit(r["entry_name"])),
                     ("locx:geneSymbol", lit(r["gene"].split(";")[0].strip()) if r["gene"] else None),
                     ("locx:proteinName", lit(main_name) if main_name else None),
                     ("locx:proteinNamesFull", lit(r["protein_names"]) if r["protein_names"] else None),
                     ("locx:uniprotLocationText", lit(r["location_text"]) if r["location_text"] else None)]
            pairs += [("locx:geneSynonym", lit(s)) for s in r["synonyms"].split() if s]
            pairs += [("locx:ncbiGene", lit(g.strip())) for g in gene_ids]
            f.write(block(f"uniprot:{r['acc']}", pairs))
    print(f"[uniprot] {n} Swiss-Prot entries, {n_gene} with an NCBI GeneID ({n_multi} with several)")
    return {"entries": n, "with_gene_id": n_gene, "with_several_gene_ids": n_multi}
