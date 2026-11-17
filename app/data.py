"""Data access for the demo: every function runs one query from queries/ against Fuseki (read-only) and
returns (rows, sparql). Parameters are validated before they are put into a query, so user input can
never change the query (no SPARQL injection)."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locx.config import CFG, QUERIES  # noqa: E402
from locx.kg import fuseki  # noqa: E402

LOCX = "http://example.org/locx/"
RUN_ID = CFG["extract"]["main_run"]
RUN_GRAPH = CFG["graphs"]["run_prefix"] + RUN_ID
VERDICTS = ["Consistent", "Refinement", "Novel", "Conflicting", "Uninformative", "Error"]
ACC = re.compile(r"^[A-Z0-9]{6,10}$")
AKEY = re.compile(r"^[A-Z0-9]{6,10}_GO_\d{7}_(present|absent)$")
FLAGS = {"protein_not_in_sentence", "location_not_in_sentence", "other_ungrounded", "impossible_location",
         "protein_coref", "location_coref", "other_grounded_exact", "other_grounded_fuzzy", "other_ambiguous",
         "too_generic"}


def sparql(name: str, **params) -> str:
    text = (QUERIES / name).read_text().replace("%RUN_GRAPH%", RUN_GRAPH)
    for k, v in params.items():
        text = text.replace(f"%{k}%", v)
    return text


def run(name: str, **params):
    q = sparql(name, **params)
    t = time.time()
    res = fuseki.query(q)
    rows = [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]
    return rows, q, time.time() - t


def local(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


def protein_iri(acc: str) -> str:
    if not ACC.match(acc or ""):
        raise ValueError(f"not a UniProt accession: {acc!r}")
    return f"http://purl.uniprot.org/uniprot/{acc}"


def assertion_iri(key: str) -> str:
    if not AKEY.match(key or ""):
        raise ValueError(f"not an assertion key: {key!r}")
    return f"{LOCX}assertion/{key}"


def opposite(key: str) -> str:
    return key[:-7] + "absent" if key.endswith("present") else key[:-6] + "present"


# --- one function per panel ------------------------------------------------------------------------
def graph_sizes():
    return run("demo_graph_sizes.rq")


def run_info():
    return run("demo_run.rq")


def run_counts():
    return run("demo_run_counts.rq")


def verdict_distribution():
    return run("verdict_distribution.rq")


def proteins():
    return run("demo_proteins.rq")


def protein_literature(acc):
    return run("demo_protein_literature.rq", PROTEIN=protein_iri(acc))


def protein_goa(acc):
    return run("demo_protein_goa.rq", PROTEIN=protein_iri(acc))


def assertion(key):
    return run("demo_assertion.rq", ASSERTION=assertion_iri(key))


def assertion_mentions(key):
    return run("demo_assertion_mentions.rq", ASSERTION=assertion_iri(key))


def assertion_authors(key):
    return run("demo_assertion_authors.rq", ASSERTION=assertion_iri(key))


def assertion_goa(key):
    return run("demo_assertion_goa.rq", ASSERTION=assertion_iri(key))


def curation_gaps(min_groups: int):
    n = int(min_groups)
    if not 1 <= n <= 1000:
        raise ValueError("min_groups out of range")
    return run("demo_curation_gaps.rq", MIN_GROUPS=str(n))


def conflicts():
    return run("demo_conflicts.rq")


def error_flags():
    return run("demo_error_flags.rq")


def errors(flag: str):
    if flag not in FLAGS:
        raise ValueError(f"unknown flag {flag!r}")
    return run("demo_errors.rq", FLAG=flag)


GO = re.compile(r"^http://purl\.obolibrary\.org/obo/GO_\d{7}$")


def go_parents(terms):
    terms = sorted(set(terms))
    if not terms:
        return [], "", 0.0
    if not all(GO.match(t) for t in terms):
        raise ValueError("not a GO term IRI")
    return run("demo_go_parents.rq", TERMS=" ".join(f"<{t}>" for t in terms))


def neighborhood_papers(acc):
    return run("demo_neighborhood_papers.rq", PROTEIN=protein_iri(acc))


def manifest_sizes():
    """Triples per named graph as counted live by the loader at load time (data/rdf/loaded.json)."""
    import json
    from locx.config import RDF
    m = json.loads((RDF / "loaded.json").read_text())
    return [{"graph": g, "triples": str(e["triples"]), "loaded_at": e.get("loaded_at", "")} for g, e in m.items()]


# --- v2 demo (Home / Protein / Provenance / Explore / Quality) ----------------------------------------
def assertions_all():
    return run("demo_assertions_all.rq")


def corpus_size():
    return run("demo_corpus_size.rq")


def slims(terms):
    """{GO IRI: sorted goslim_agr labels above it} (empty list = no slim term above it)."""
    terms = sorted(set(terms))
    if not terms:
        return {}, "", 0.0
    if not all(GO.match(t) for t in terms):
        raise ValueError("not a GO term IRI")
    rows, q, s = run("demo_slims.rq", TERMS=" ".join(f"<{t}>" for t in terms))
    out = {t: [] for t in terms}
    for r in rows:
        out[r["term"]].append(r["slimLabel"])
    return {t: sorted(set(v)) for t, v in out.items()}, q, s


def protein_years(acc):
    return run("demo_protein_years.rq", PROTEIN=protein_iri(acc))


def provenance_goa(key):
    return run("demo_provenance_goa.rq", ASSERTION=assertion_iri(key))


def provenance_authors(key):
    return run("demo_provenance_authors.rq", ASSERTION=assertion_iri(key))


def report(name):
    """A JSON report written by the pipeline under reports/ (None if missing)."""
    import json
    from locx.config import REPORTS
    if not re.match(r"^[a-z0-9_]+$", name):
        raise ValueError("bad report name")
    p = REPORTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def protein_mentions(acc):
    return run("demo_protein_mentions.rq", PROTEIN=protein_iri(acc))


def protein_authors(acc):
    return run("demo_protein_authors.rq", PROTEIN=protein_iri(acc))


PMID = re.compile(r"^\d{1,9}$")


def abstract(pmid):
    """Full text the LLM read for one paper (abstracts graph)."""
    if not PMID.match(str(pmid)):
        raise ValueError(f"not a PMID: {pmid!r}")
    return run("demo_abstract.rq", PAPER=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}")
