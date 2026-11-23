# ProteinLocationProvenance (locx)

Provenance-aware protein localization claims from the biomedical literature.

A local large language model reads PubMed abstracts and extracts statements about where human proteins are found in
the cell (nucleus, mitochondrion, plasma membrane, ...). Every claim is grounded to UniProt (protein) and the Gene
Ontology cellular-component branch (location), stored as RDF with its provenance (paper, evidence sentence, authors,
journal, year, extraction run), and compared with curated knowledge from the GO annotation database (GOA). Each
protein-location statement gets a verdict (consistent, refinement, novel, conflicting, uninformative) and a support
count (claims, papers, independent author groups). A Streamlit demo queries the knowledge graph live and shows the
SPARQL behind every page.

Course project for CMPE 58H Social Semantic Web, by Buse Giledereli.

## How it works

1. **Reference graphs.** The official GO, ECO, RO and UniProt core releases are loaded unmodified, one named graph
   each, into Apache Jena Fuseki. GOA human (cellular-component rows) and UniProt human Swiss-Prot are converted to RDF.
2. **Corpus.** Abstracts from Europe PMC in two tiers: *silver* (abstracts GOA curators cited, used to measure recall)
   and *discovery* (localization papers per year). PubTator3 normalizes gene mentions to NCBI GeneIDs, mapped to
   UniProt.
3. **Candidates.** Each abstract gets a list of candidate proteins and candidate locations (a dictionary of GO
   cellular-component names and synonyms).
4. **Extraction.** Gemma 4 31B (Google's 4-bit checkpoint) on vLLM returns JSON constrained by a per-abstract JSON
   schema. **The model never writes an ID**: proteins and locations are enums of the candidates, so it can only pick
   from what grounding offered. It also gives polarity, certainty, source type (own result or background), method,
   organism, conditions, cell type and the evidence sentence.
5. **Validation.** Python checks (is the protein / location in the cited sentence?) and SHACL shapes (structure,
   impossible and too-generic locations). Invalid claims are flagged, not dropped.
6. **Knowledge graph.** A hand-written OWL 2 ontology (`ontology/locx.owl.ttl`) defines claims, assertions, curated
   annotations, contexts, support, verdicts and the activities that produce them (PROV-O). Evidence sentences use
   W3C Web Annotation, papers FaBiO, authors OpenAlex persons. Locations and evidence are individuals typed with
   their GO / ECO class (no punning).
7. **Reasoning.** HermiT checks the ontology (with ECO, UniProt core and GO's cellular-component module); OWL 2 RL
   rules run as SPARQL updates over all data into a separate `inferred` graph.
8. **Support and verdicts.** Claims with the same protein, location and polarity form an assertion; each assertion
   gets its support (papers, independent author groups) and a verdict against GOA using the GO hierarchy, linked to
   the GOA rows and their evidence.
9. **Evaluation and demo.** Recall on the silver tier against GOA (with a co-occurrence baseline and a ceiling),
   precision on a random sample, and the Streamlit demo.

## Repository layout

| Path | What |
|---|---|
| `ontology/` | the locx OWL 2 ontology (hand-maintained source of truth for the code), Protégé catalog, sample |
| `shapes/` | SHACL shapes (gate shapes before loading, quality shapes) |
| `queries/` | every SPARQL query and update the pipeline and demo run (`.rq` select, `.ru` update) |
| `locx/` | the pipeline: `fetch` (APIs), `corpus`, `extract` (candidates, prompt, schema, extraction, validation), `kg` (RDF builders, Fuseki loading), `analysis` (support, verdicts, evaluation, report) |
| `app/` | Streamlit demo (`app/v2.py`) and its data access |
| `scripts/` | service wrappers (Fuseki, vLLM, demo), reasoning, ontology checks, schema figures, Docker export |
| `docker/` | Fuseki configuration; `docker/demo/` is a Docker version of the demo for other machines |
| `config.yaml` | models, ports, named graphs, corpus settings |

## Running it

Requirements: Linux, micromamba, Java 21 (for Fuseki), an Ampere or newer GPU with about 48 GB for the model. All
services bind to `127.0.0.1`; reach them through an SSH tunnel. Secrets go in `.env` (copy `.env.example`; never
commit it).

```bash
make env                                      # pipeline env "locx" (Python 3.11)
make fuseki-build && make fuseki-up && make fuseki-smoke
make vllm-env && make serve                   # vLLM in its own env, GPU from config.yaml
make kg && make ontology                      # reference graphs and the locx ontology -> Fuseki
make corpus && make candidates
make extract-dev                              # small dev run for prompt review
make extract                                  # full run (resumable)
make validate && make rdf && make load && make abstracts
make support && make verdicts && make reason && make check-ontology
make silver-eval && make report && make schema
make demo                                     # Streamlit on 127.0.0.1:8501
```

Every stage is file-based, idempotent and resumable: raw API responses are cached under `data/raw/`, and outputs go
to `data/` and `reports/` (neither is in the repository).

## Docker demo

`docker/demo/` runs the demo (read-only Fuseki plus the Streamlit app) on any machine with Docker. It is built from a
bundle made on a machine that has run the pipeline (`make demo-export && make demo-bundle`, which includes the graph
export and the generated reports); see `docker/demo/README.md`.
