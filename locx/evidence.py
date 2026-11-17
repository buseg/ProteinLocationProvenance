"""GO evidence codes: what each GOA evidence code means and how strong it is.

One table used by the verdict rules (strongest evidence group behind a verdict), the report and the demo.
Codes and names follow the GO Consortium's guide to GO evidence codes (geneontology.org/docs/guide-go-evidence-codes).
Groups are ordered from strongest to weakest; a verdict is labelled with the strongest group among the GOA rows
behind it.
"""

GROUPS = [  # (key, label, plain explanation)
    ("experimental", "Experimental", "shown in a lab experiment on this protein (e.g. microscopy, fractionation)"),
    ("high_throughput", "High-throughput", "from a large screen (e.g. the Human Protein Atlas antibody imaging)"),
    ("author_statement", "Author statement", "a paper or review states it; the curator did not see the data "
                                             "(TAS mostly from Reactome)"),
    ("curator", "Curator inference", "a curator inferred it from other annotations"),
    ("computational", "Phylogenetic / computational", "inferred from related proteins, sequence or structure"),
    ("electronic", "Electronic", "assigned automatically; no curator reviewed it"),
]
GROUP_LABEL = {k: label for k, label, _ in GROUPS}
GROUP_HELP = {k: h for k, _, h in GROUPS}
RANK = {k: i for i, (k, _, _) in enumerate(GROUPS)}

CODES = {  # code: (group, name)
    "EXP": ("experimental", "Inferred from Experiment"),
    "IDA": ("experimental", "Inferred from Direct Assay"),
    "IPI": ("experimental", "Inferred from Physical Interaction"),
    "IMP": ("experimental", "Inferred from Mutant Phenotype"),
    "IGI": ("experimental", "Inferred from Genetic Interaction"),
    "IEP": ("experimental", "Inferred from Expression Pattern"),
    "HTP": ("high_throughput", "Inferred from High Throughput Experiment"),
    "HDA": ("high_throughput", "Inferred from High Throughput Direct Assay"),
    "HMP": ("high_throughput", "Inferred from High Throughput Mutant Phenotype"),
    "HGI": ("high_throughput", "Inferred from High Throughput Genetic Interaction"),
    "HEP": ("high_throughput", "Inferred from High Throughput Expression Pattern"),
    "TAS": ("author_statement", "Traceable Author Statement"),
    "NAS": ("author_statement", "Non-traceable Author Statement"),
    "IC": ("curator", "Inferred by Curator"),
    "ND": ("curator", "No biological Data available"),
    "IBA": ("computational", "Inferred from Biological aspect of Ancestor"),
    "IBD": ("computational", "Inferred from Biological aspect of Descendant"),
    "IKR": ("computational", "Inferred from Key Residues"),
    "IRD": ("computational", "Inferred from Rapid Divergence"),
    "ISS": ("computational", "Inferred from Sequence or structural Similarity"),
    "ISO": ("computational", "Inferred from Sequence Orthology"),
    "ISA": ("computational", "Inferred from Sequence Alignment"),
    "ISM": ("computational", "Inferred from Sequence Model"),
    "IGC": ("computational", "Inferred from Genomic Context"),
    "RCA": ("computational", "Inferred from Reviewed Computational Analysis"),
    "IEA": ("electronic", "Inferred from Electronic Annotation"),
}


def group(code: str) -> str:
    return CODES[code][0] if code in CODES else "unknown"


def strongest(codes) -> str | None:
    """The strongest evidence group among a set of codes (None if empty)."""
    gs = [group(c) for c in codes if c in CODES]
    return min(gs, key=RANK.get) if gs else None


def sparql_code_values() -> str:
    """VALUES rows (?ev ?evRank) for the verdict rules."""
    return " ".join(f'("{c}" {RANK[g]})' for c, (g, _) in CODES.items())


def sparql_group_values() -> str:
    """VALUES rows (?evGroup ?evRank) for the verdict rules."""
    return " ".join(f'("{k}" {RANK[k]})' for k, _, _ in GROUPS)
