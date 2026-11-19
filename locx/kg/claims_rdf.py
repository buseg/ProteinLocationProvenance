"""M7: papers, run, claims and assertions to RDF, SHACL, load into Fuseki. Every class, property and value comes from
the locx ontology (ontology/locx.owl.ttl, read by locx/ontology.py); a term the ontology does not declare stops the build.

  python -m locx.kg.claims_rdf build [--run-id ID]   # Turtle + SHACL (quality flags, then gate)
  python -m locx.kg.claims_rdf load  [--run-id ID] [--replace]   # PUT graphs + sanity queries

build:
  1. run graph with provisional validity -> quality shapes (shapes/quality.shacl.ttl, with the ontology and the GO CC
     module) -> V5 impossible location (invalidates) / V6 too generic (warning) written back as flags
  2. final graphs: run (the run, the model, every claim with its Web Annotation evidence sentence; `locx:asserts`
     only when valid), assertions (one per protein + relation + GO term + polarity), papers (papers, journals, dated
     citation counts, OpenAlex authorships with persons and ROR institutions, corpus samples as PROV collections)
  3. gate shapes (shapes/claims.shacl.ttl) on papers + run + assertions + ontology + GO module + protein types
Outputs: data/rdf/{papers,assertions,run_<id>}.ttl, data/runs/<id>/claims_final.jsonl,
reports/shacl_quality_report.txt, reports/shacl_report.txt, reports/rdf_stats.json.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from collections import Counter

import rdflib
from pyshacl import validate
from rdflib.namespace import SH

from locx import ontology as O
from locx.config import CFG, DATA, INTERIM, QUERIES, RDF, REPORTS, ROOT
from locx.io import read_jsonl, write_jsonl
from locx.kg import fuseki, releases
from locx.kg.ttl import LOCX, go_iri, lit

RUNS = DATA / "runs"
SHAPES = ROOT / "shapes"
G = CFG["graphs"]
PREFIXES = """\
@prefix locx:     <http://example.org/locx/> .
@prefix obo:      <http://purl.obolibrary.org/obo/> .
@prefix uniprot:  <http://purl.uniprot.org/uniprot/> .
@prefix pubmed:   <https://pubmed.ncbi.nlm.nih.gov/> .
@prefix prov:     <http://www.w3.org/ns/prov#> .
@prefix dcterms:  <http://purl.org/dc/terms/> .
@prefix fabio:    <http://purl.org/spar/fabio/> .
@prefix frbr:     <http://purl.org/vocab/frbr/core#> .
@prefix prism:    <http://prismstandard.org/namespaces/basic/2.0/> .
@prefix c4o:      <http://purl.org/spar/c4o/> .
@prefix oa:       <http://www.w3.org/ns/oa#> .
@prefix foaf:     <http://xmlns.com/foaf/0.1/> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

"""
NLM = "https://www.ncbi.nlm.nih.gov/nlmcatalog/"   # journal IRI = NLM Catalog record
EUROPE_PMC = "https://europepmc.org/"               # source of the citation counts
QUALITY_FLAGS = {LOCX + "ImpossibleLocationShape": "impossible_location", LOCX + "TooGenericShape": "too_generic"}
TERMS = ("locx:Claim", "locx:Assertion", "locx:Authorship", "locx:evidenceSentence", "locx:relation", "locx:asserts",
         "locx:authorName", "locx:affiliation", "locx:orcid", "locx:query", "fabio:JournalArticle", "fabio:Journal",
         "c4o:GlobalCitationCount", "c4o:BibliographicInformationSource", "oa:SpecificResource",
         "oa:TextPositionSelector", "oa:TextQuoteSelector", "prov:Collection", "foaf:Person", "foaf:Organization",
         "locx:ExtractionRun", "locx:CorpusBuilding", "locx:FreeTextContext", "locx:hasContext", "locx:contextText",
         "locx:contextKind")


def iri(path: str) -> str:
    return f"<{LOCX}{path}>"


def integer(x) -> str:
    return f'"{int(x)}"^^xsd:integer'


def boolean(x) -> str:
    return "true" if x else "false"


TRIPLES = [0]   # triples written by block() since the last reset (avoids re-parsing big files to count)


def block(subject: str, pairs) -> str:
    pairs = [(p, o) for p, o in pairs if o is not None]
    TRIPLES[0] += len(pairs)
    return subject + " " + " ;\n    ".join(f"{p} {o}" for p, o in pairs) + " .\n"


def invalidating() -> set[str]:
    """Tokens of the quality flags the ontology marks as invalidating (locx:invalidates true)."""
    g = O.graph()
    inv = O.expand("locx:invalidates")
    return {tok for tok, v in O.values("QualityFlag").items() if (rdflib.URIRef(v), inv, rdflib.Literal(True)) in g}


# --- papers --------------------------------------------------------------------------------------------------------
def citation_date(rec, cited_by):
    """The latest fetch date of a cached Europe PMC record that carries this citation count (None if none does)."""
    days = [d for d, n in (rec or {}).get("counts", []) if n == cited_by]
    return max(days) if days else None


def papers_ttl(papers, path, records, works, c=None):
    """records: PMID -> Europe PMC journal + dated counts (europepmc.record_index); works: PMID -> OpenAlex work."""
    c = Counter() if c is None else c
    persons, orgs, journals = {}, {}, {}
    with open(path, "w") as f:
        f.write(PREFIXES)
        f.write(block(f"<{EUROPE_PMC}>", [("a", "c4o:BibliographicInformationSource"), ("rdfs:label", lit("Europe PMC"))]))
        for p in papers:
            pmid, subj = p["pmid"], f"pubmed:{p['pmid']}"
            ships = []
            w = works.get(pmid)
            if w:
                c["papers_with_openalex"] += 1
                oa_orcids = set()
                for k, a in enumerate(w.get("authorships") or [], 1):
                    au = a.get("author") or {}
                    ship = iri(f"authorship/{pmid}/{k}")
                    pairs = [("a", "locx:Authorship"), ("locx:position", integer(k)),
                             ("locx:authorName", lit(a.get("raw_author_name") or au.get("display_name") or ""))]
                    if au.get("id"):
                        pairs.append(("locx:author", f"<{au['id']}>"))
                        persons.setdefault(au["id"], (au.get("display_name"), au.get("orcid")))
                        oa_orcids.add((au.get("orcid") or "").rsplit("/", 1)[-1])
                    else:
                        c["authorships_without_person"] += 1
                    for inst in a.get("institutions") or []:
                        org = inst.get("ror") or inst.get("id")
                        if org:
                            pairs.append(("locx:affiliation", f"<{org}>"))
                            orgs.setdefault(org, inst.get("display_name"))
                    f.write(block(ship, pairs))
                    ships.append(ship)
                    c["authorships"] += 1
                epmc = {a["orcid"] for a in p.get("authors") or [] if a.get("orcid")}
                c["epmc_orcids"] += len(epmc)
                c["epmc_orcids_also_in_openalex"] += len(epmc & oa_orcids)
            else:   # not in OpenAlex: authorships with the printed name only (no person is identified)
                c["papers_without_openalex"] += 1
                for k, a in enumerate((a for a in p.get("authors") or [] if not a.get("collective")), 1):
                    ship = iri(f"authorship/{pmid}/{k}")
                    f.write(block(ship, [("a", "locx:Authorship"), ("locx:position", integer(k)),
                                         ("locx:authorName", lit(a.get("name") or ""))]))
                    ships.append(ship)
                    c["authorships"] += 1
                    c["authorships_without_person"] += 1
            rec = records.get(pmid) or {}
            j = rec.get("journal")
            jnode = f"<{NLM}{j['nlmid']}>" if j and j.get("nlmid") else None
            if jnode:
                journals.setdefault(jnode, j)
            else:
                c["papers_without_nlm_journal"] += 1
            cnode = None
            if p.get("cited_by") is not None:
                cnode = iri(f"citationCount/{pmid}")
                day = citation_date(rec, p["cited_by"])
                c["citation_counts_without_date"] += day is None
                f.write(block(cnode, [("a", "c4o:GlobalCitationCount"),
                                      ("c4o:hasGlobalCountValue", integer(p["cited_by"])),
                                      ("c4o:hasGlobalCountDate", f'"{day}"^^xsd:date' if day else None),
                                      ("c4o:hasGlobalCountSource", f"<{EUROPE_PMC}>")]))
            date = p.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.get("date") or "") else None
            pairs = [("a", "fabio:JournalArticle"), ("dcterms:title", lit(p.get("title") or p.get("epmc_title") or "")),
                     ("dcterms:date", f'"{date}"^^xsd:date' if date else None),
                     ("frbr:partOf", jnode), ("prism:doi", lit(p["doi"]) if p.get("doi") else None),
                     ("c4o:hasGlobalCitationFrequency", cnode)]
            pairs += [("locx:hasAuthorship", s_) for s_ in ships]
            f.write(block(subj, pairs))
            c["papers"] += 1
        for person, (name, orcid) in persons.items():
            f.write(block(f"<{person}>", [("a", "foaf:Person"), ("foaf:name", lit(name)) if name else (None, None),
                                         ("locx:orcid", f"<{orcid}>" if orcid else None)]))
            c["persons"] += 1
            c["persons_with_orcid"] += bool(orcid)
        for org, name in orgs.items():
            f.write(block(f"<{org}>", [("a", "foaf:Organization"), ("foaf:name", lit(name)) if name else (None, None)]))
            c["organizations"] += 1
        for jn, j in journals.items():
            f.write(block(jn, [("a", "fabio:Journal"), ("dcterms:title", lit(j["title"]) if j.get("title") else None),
                               ("fabio:hasNationalLibraryOfMedicineJournalId", lit(j["nlmid"])),
                               ("fabio:hasNLMJournalTitleAbbreviation", lit(j["abbrev"]) if j.get("abbrev") else None),
                               ("prism:issn", lit(j["issn"]) if j.get("issn") else None),
                               ("prism:eIssn", lit(j["essn"]) if j.get("essn") else None)]))
            c["journals"] += 1
    return dict(c)


def corpus_ttl(papers, path):
    """The corpus samples as PROV collections, each generated by the corpus-building activity that selected its papers
    (queries rebuilt with locx/corpus.py's own functions and config)."""
    from locx import corpus as K
    C = CFG["corpus"]
    members = {t: [p["pmid"] for p in papers if t in p["tiers"]] for t in K.TIERS}
    y0, y1 = C["dev_years"]
    dev_q = [f'ABSTRACT:({" OR ".join(json.dumps(n, ensure_ascii=False) for n in names)}) AND ABSTRACT:{K.LOC} AND '
             f'{K.BASE} AND PUB_YEAR:[{y0} TO {y1}]' for names in C["dev_seeds"].values()]
    protein = " AND ABSTRACT:(protein*)" if C.get("discovery_protein_filter", True) else ""
    d0, d1 = C["discovery_years"]
    disc_q = [f"ABSTRACT:{K.LOC}{protein} AND {K.BASE} AND PUB_YEAR:{y}" for y in range(d0, d1 + 1)]
    about = {
        "dev": ("dev sample", f"Prompt development: up to {C['dev_per_protein']} Europe PMC hits per seed protein "
                              f"({', '.join(C['dev_seeds'])}), {y0}-{y1}.", dev_q),
        "silver": ("silver sample", f"Evaluation: a random sample (seed {C['seed']}, {C['silver_sample']} PMIDs) of the "
                                    "papers GOA cites for a cellular component annotation with low-throughput "
                                    f"experimental evidence ({', '.join(CFG['silver']['evidence_low_throughput'])}).", []),
        "discovery": ("discovery sample", f"New claims: Europe PMC relevance ranking per publication year {d0}-{d1}, "
                                          "kept when PubTator finds at least one human Swiss-Prot gene.", disc_q)}
    with open(path, "a") as f:
        for t, (label, comment, queries) in about.items():
            act = iri(f"corpusBuilding/{t}")
            f.write(block(act, [("a", "locx:CorpusBuilding"), ("rdfs:label", lit(f"corpus building: {label}")),
                                ("rdfs:comment", lit(comment))] + [("locx:query", lit(q)) for q in queries]))
            f.write(block(iri(f"corpus/{t}"), [("a", "prov:Collection"), ("rdfs:label", lit(label)),
                                               ("prov:wasGeneratedBy", act)]
                          + [("prov:hadMember", f"pubmed:{m}") for m in members[t]]))
    return {t: len(m) for t, m in members.items()}


# --- run + claims ----------------------------------------------------------------------------------------------------
def mention_texts(cand, claim):
    """Surface strings of the protein / candidate location in the cited sentence (else the earlier ones)."""
    order = {s["id"]: i for i, s in enumerate(cand["sentences"])}
    sid = order[claim["sentence"]]

    def pick(mentions):
        same = [m["text"] for m in mentions if order.get(m["sentence"]) == sid]
        earlier = [m["text"] for m in mentions if order.get(m["sentence"], 99999) < sid]
        return list(dict.fromkeys(same or earlier))
    P = {p["cid"]: p for p in cand["proteins"]}
    L = {l["cid"]: l for l in cand["locations"]}
    prot = pick(P[claim["protein"]["cid"]]["mentions"])
    loc = pick(L[claim["location"]["cid"]]["mentions"]) if claim["location"]["cid"] != "OTHER" else []
    return prot, loc


def run_ttl(meta, claims, cands, path):
    for t in TERMS:
        O.term(t)
    rid = meta["run_id"]
    run, agent = iri(f"run/{rid}"), iri(f"agent/{meta['served_name']}")
    relation = f"<{O.class_annotation('Claim', 'statesRelation')}>"     # every claim: the relation the ontology fixes for claims
    claim_iri, sentences = {}, set()
    with open(path, "w") as f:
        f.write(PREFIXES)
        f.write(block(run, [("a", "locx:ExtractionRun"), ("rdfs:label", lit(f"extraction run {rid}")),
                            ("prov:wasAssociatedWith", agent),
                            ("prov:startedAtTime", f'"{meta["started"]}"^^xsd:dateTime'),
                            ("prov:endedAtTime", f'"{meta["ended"]}"^^xsd:dateTime' if meta.get("ended") else None),
                            ("locx:promptVersion", lit(meta["prompt_version"])),
                            ("locx:promptSha256", lit(meta["prompt_sha256"])),
                            ("locx:schemaVersion", lit(meta["schema_version"])),
                            ("locx:temperature", f'"{meta["temperature"]}"^^xsd:decimal'),
                            ("locx:maxTokens", integer(meta["max_tokens"])),
                            ("locx:inputSha256", lit(meta["input_sha256"])),
                            ("locx:gpu", integer(meta["gpu"]))]))
        f.write(block(agent, [("a", "prov:SoftwareAgent"), ("rdfs:label", lit(meta["model"])),
                              ("locx:servedName", lit(meta["served_name"])),
                              ("locx:servedBy", lit(f"vLLM {meta['vllm_version']} (pip)"))]))
        k_per_pmid = Counter()
        for cl in claims:
            k_per_pmid[cl["pmid"]] += 1
            m = iri(f"claim/{rid}/{cl['pmid']}/{k_per_pmid[cl['pmid']]}")
            if cl["location"]["go_id"]:   # the claim's location: an individual typed with the GO class (no punning)
                f.write(block(m[:-1] + "/location>", [("a", go_iri(cl["location"]["go_id"]))]))
            claim_iri[cl["claim_id"]] = m
            sent = iri(f"sentence/{cl['pmid']}/{cl['sentence']}")
            if sent not in sentences:    # the sentence as a Web Annotation span of the abstract, written once
                sentences.add(sent)
                pos, quote = iri(f"sentence/{cl['pmid']}/{cl['sentence']}/position"), \
                    iri(f"sentence/{cl['pmid']}/{cl['sentence']}/quote")
                f.write(block(sent, [("a", "oa:SpecificResource"), ("oa:hasSource", iri(f"abstract/{cl['pmid']}")),
                                     ("oa:hasSelector", pos), ("oa:hasSelector", quote)]))
                f.write(block(pos, [("a", "oa:TextPositionSelector"), ("oa:start", integer(cl["sentence_start"])),
                                    ("oa:end", integer(cl["sentence_end"]))]))
                f.write(block(quote, [("a", "oa:TextQuoteSelector"), ("oa:exact", lit(cl["sentence_text"]))]))
            loc = cl["location"]
            prot_txt, loc_txt = mention_texts(cands[cl["pmid"]], cl)
            pairs = [("a", "locx:Claim"), ("locx:claimId", lit(cl["claim_id"])),
                     ("prov:wasDerivedFrom", f"pubmed:{cl['pmid']}"), ("prov:wasGeneratedBy", run),
                     ("locx:sentenceId", lit(cl["sentence"])), ("locx:evidenceSentence", sent),
                     ("locx:protein", f"uniprot:{cl['protein']['uniprot']}"), ("locx:relation", relation),
                     ("locx:location", m[:-1] + "/location>" if loc["go_id"] else None),
                     ("locx:otherLocationText", lit(loc["other_location_text"]) if loc.get("other_location_text") else None),
                     ("locx:groundingMethod", O.ttl("GroundingMethod", loc["grounding"]["method"]) if loc.get("grounding") else None),
                     ("locx:polarity", O.ttl("Polarity", cl["polarity"])), ("locx:certainty", O.ttl("Certainty", cl["certainty"])),
                     ("locx:sourceType", O.ttl("SourceType", cl["source_type"])),
                     ("locx:organism", O.ttl("Organism", cl["organism"])), ("locx:method", O.ttl("Method", cl["method"])),
                     ("locx:duplicateCount", integer(cl["duplicate_count"])),
                     ("locx:valid", boolean(cl["valid"])), ("locx:repairRound", integer(0))]
            pairs += [("locx:proteinMention", lit(t)) for t in prot_txt]
            pairs += [("locx:locationMention", lit(t)) for t in loc_txt]
            # the sentence's conditions and cell type as free-text contexts (kind from the ontology's ContextKind)
            texts = [("condition", t) for t in cl["conditions"]] + ([("cell_type", cl["cell_type"])] if cl["cell_type"] else [])
            for n, (kind, t) in enumerate(texts, 1):
                ctx = m[:-1] + f"/context{n}>"
                f.write(block(ctx, [("a", "locx:FreeTextContext"), ("locx:contextKind", O.ttl("ContextKind", kind)),
                                    ("locx:contextText", lit(t))]))
                pairs.append(("locx:hasContext", ctx))
            pairs += [("locx:flag", O.ttl("QualityFlag", fl)) for fl in cl["flags"]]
            if cl["valid"]:
                pairs.append(("locx:asserts", iri(assertion_key(cl))))
            f.write(block(m, pairs))
    return claim_iri


def assertion_key(cl) -> str:
    return f"assertion/{cl['protein']['uniprot']}_{cl['location']['go_id'].replace(':', '_')}_{cl['polarity']}"


def assertions_ttl(claims, path):
    relation = f"<{O.class_annotation('Claim', 'statesRelation')}>"
    seen = {}
    for cl in claims:
        if cl["valid"]:
            seen.setdefault(assertion_key(cl), cl)
    with open(path, "w") as f:
        f.write(PREFIXES)
        for key, cl in sorted(seen.items()):
            f.write(block(iri(key + "/location"), [("a", go_iri(cl["location"]["go_id"]))]))
            f.write(block(iri(key), [("a", "locx:Assertion"), ("locx:protein", f"uniprot:{cl['protein']['uniprot']}"),
                                     ("locx:relation", relation), ("locx:location", iri(key + "/location")),
                                     ("locx:polarity", O.ttl("Polarity", cl["polarity"]))]))
    return len(seen)


def shacl(data_paths, shapes_path, report_path, title):
    t = time.time()
    g = rdflib.Graph()
    for p in data_paths:
        g.parse(p, format="turtle")
    conforms, results, text = validate(g, shacl_graph=str(shapes_path), shacl_graph_format="turtle",
                                       inference="none", advanced=True, allow_warnings=True)
    report_path.write_text(f"# {title}\n# data: {', '.join(p.name for p in data_paths)}\n"
                           f"# shapes: {shapes_path.relative_to(ROOT)}\n# conforms: {conforms}\n\n{text}")
    hits = []
    for r in results.subjects(rdflib.RDF.type, SH.ValidationResult):
        hits.append((str(results.value(r, SH.sourceShape)), str(results.value(r, SH.focusNode)),
                     str(results.value(r, SH.resultSeverity)).rsplit("#", 1)[-1], str(results.value(r, SH.resultMessage))))
    print(f"[shacl] {title}: {len(g)} triples, conforms={conforms}, {len(hits)} results ({time.time() - t:.0f} s)")
    return conforms, hits


CHUNK_PAPERS = 2000
WORKERS = 16
_BASE = {}


def _validate_chunk(args):
    """Worker: base graphs (ontology, GO CC module, protein types; parsed once per process) + one chunk -> results."""
    chunk_paths, base_paths, shapes_path = args
    key = tuple(base_paths)
    if key not in _BASE:
        b = rdflib.Graph()
        for p in base_paths:
            b.parse(p, format=rdflib.util.guess_format(str(p)) or "turtle")
        _BASE[key] = b
    g = rdflib.Graph()
    for t in _BASE[key]:
        g.add(t)
    for p in chunk_paths:
        g.parse(p, format="turtle")
    conforms, results, _ = validate(g, shacl_graph=str(shapes_path), shacl_graph_format="turtle",
                                    inference="none", advanced=True, allow_warnings=True)
    hits = [(str(results.value(r, SH.sourceShape)), str(results.value(r, SH.focusNode)),
             str(results.value(r, SH.resultSeverity)).rsplit("#", 1)[-1], str(results.value(r, SH.resultMessage)))
            for r in results.subjects(rdflib.RDF.type, SH.ValidationResult)]
    return conforms, hits, len(g)


def shacl_chunked(chunks, base_paths, shapes_path, report_path, title):
    """Validate chunk by chunk in parallel. Every shape is local to a claim, assertion, paper or run, and a
    chunk holds whole papers with their claims and the assertions those claims make, so the union of the
    chunk results equals one big validation (assertions nobody asserts are checked separately)."""
    from concurrent.futures import ProcessPoolExecutor
    t = time.time()
    conforms, hits, sizes = True, [], []
    with ProcessPoolExecutor(max_workers=min(WORKERS, len(chunks))) as ex:
        for c, h, n in ex.map(_validate_chunk, [(ch, base_paths, shapes_path) for ch in chunks]):
            conforms &= c
            hits += h
            sizes.append(n)
    hits = sorted(set(hits))
    lines = [f"# {title}", f"# chunks: {len(chunks)} (up to {CHUNK_PAPERS} papers each, {WORKERS} workers); "
             f"base: {', '.join(Path(p).name for p in base_paths)}", f"# shapes: {shapes_path.relative_to(ROOT)}",
             f"# conforms: {conforms}", f"# results: {len(hits)}", ""]
    lines += [f"{sev}\t{s.rsplit('/', 1)[-1]}\t{f_}\t{msg}" for s, f_, sev, msg in hits]
    report_path.write_text("\n".join(lines) + "\n")
    print(f"[shacl] {title}: {len(chunks)} chunks, largest {max(sizes)} triples, conforms={conforms}, "
          f"{len(hits)} results ({time.time() - t:.0f} s)")
    return conforms, hits


def write_chunks(kind, meta, claims, cands, papers, with_papers, records=None, works=None):
    """data/rdf/chunks/<kind>/NNNN_*.ttl: whole papers (by PMID) with their claims and assertions."""
    import shutil
    d = RDF / "chunks" / kind
    if d.exists():
        shutil.rmtree(d)   # our own scratch files from a previous build
    d.mkdir(parents=True)
    by_pmid = {}
    for cl in claims:
        by_pmid.setdefault(cl["pmid"], []).append(cl)
    pmids = [p["pmid"] for p in papers] if with_papers else sorted(by_pmid, key=int)
    chunks = []
    for i in range(0, len(pmids), CHUNK_PAPERS):
        part = pmids[i:i + CHUNK_PAPERS]
        cs = [cl for p in part for cl in by_pmid.get(p, [])]
        files = []
        if cs:
            run_ttl(meta, cs, cands, d / f"{i // CHUNK_PAPERS:04d}_run.ttl")
            files.append(str(d / f"{i // CHUNK_PAPERS:04d}_run.ttl"))
        if with_papers:
            sub = set(part)
            papers_ttl([p for p in papers if p["pmid"] in sub], d / f"{i // CHUNK_PAPERS:04d}_papers.ttl", records, works)
            assertions_ttl(cs, d / f"{i // CHUNK_PAPERS:04d}_assertions.ttl")
            files += [str(d / f"{i // CHUNK_PAPERS:04d}_papers.ttl"), str(d / f"{i // CHUNK_PAPERS:04d}_assertions.ttl")]
        if files:
            chunks.append(files)
    return chunks


def record_index(papers):
    """PMID -> Europe PMC journal identity + dated citation counts, cached in data/interim/epmc_records.json
    (read from the Europe PMC cache once, no requests)."""
    from locx.fetch import europepmc
    path = INTERIM / "epmc_records.json"
    pmids = {p["pmid"] for p in papers}
    idx = json.loads(path.read_text()) if path.exists() else {}
    if not pmids <= set(idx) | set(idx.get("_none", [])):
        idx = europepmc.record_index(pmids)
        idx["_none"] = sorted(pmids - set(idx))
        path.write_text(json.dumps(idx))
    print(f"[rdf] Europe PMC records for {len(idx) - 1}/{len(pmids)} papers (data/interim/epmc_records.json)")
    return idx


def build(run_id):
    t0 = time.time()
    from locx.fetch import openalex
    run_dir = RUNS / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    claims = list(read_jsonl(run_dir / "claims.jsonl"))
    cands = {r["pmid"]: r for r in read_jsonl(INTERIM / "candidates.jsonl")}
    papers = list(read_jsonl(INTERIM / "papers.jsonl"))
    records, works = record_index(papers), openalex.fetch([p["pmid"] for p in papers])
    ontology, go_module = str(O.PATH), str(releases.go_cc_module())
    inval = invalidating()
    run_path = RDF / f"run_{run_id}.ttl"

    # 1. quality shapes on the provisional run graph
    for cl in claims:
        cl["valid"] = cl["valid_provisional"]
    claim_iri = run_ttl(meta, claims, cands, run_path)
    _, hits = shacl_chunked(write_chunks("quality", meta, claims, cands, papers, with_papers=False),
                            [ontology, go_module], SHAPES / "quality.shacl.ttl",
                            REPORTS / "shacl_quality_report.txt", "quality shapes (V5, V6)")
    by_claim = {}
    for shape, focus, _, _ in hits:
        if shape in QUALITY_FLAGS:
            by_claim.setdefault(focus, set()).add(QUALITY_FLAGS[shape])
    q = Counter()
    for cl in claims:
        new = by_claim.get(claim_iri[cl["claim_id"]].strip("<>"), set())
        for fl in sorted(new):
            cl["flags"].append(fl)
            q[fl] += 1
        cl["valid"] = cl["valid_provisional"] and not (new & inval)
        q["invalidated_by_shacl"] += cl["valid_provisional"] and not cl["valid"]

    # 2. final graphs
    triples = {}
    TRIPLES[0] = 0
    run_ttl(meta, claims, cands, run_path)
    triples[run_path.name] = TRIPLES[0]
    TRIPLES[0] = 0
    n_assert = assertions_ttl(claims, RDF / "assertions.ttl")
    triples["assertions.ttl"] = TRIPLES[0]
    TRIPLES[0] = 0
    pstats = papers_ttl(papers, RDF / "papers.ttl", records, works)
    pstats["corpus_samples"] = corpus_ttl(papers, RDF / "papers.ttl")
    triples["papers.ttl"] = TRIPLES[0]
    write_jsonl(run_dir / "claims_final.jsonl", claims)
    asserted = {assertion_key(cl) for cl in claims if cl["valid"]}
    assert len(asserted) == n_assert, "every assertion must come from a valid claim"

    # 3. gate shapes
    conforms, gate_hits = shacl_chunked(write_chunks("gate", meta, claims, cands, papers, with_papers=True,
                                                     records=records, works=works),
                                        [ontology, go_module, str(RDF / "uniprot_proteins.ttl")],
                                        SHAPES / "claims.shacl.ttl", REPORTS / "shacl_report.txt",
                                        "gate shapes (SPEC M7)")
    valid = sum(cl["valid"] for cl in claims)
    per_tier = {}
    for t in meta["tiers"]:
        tc = [cl for cl in claims if t in cl["tiers"]]
        per_tier[t] = {"claims": len(tc), "valid": sum(cl["valid"] for cl in tc),
                       "share_valid": round(sum(cl["valid"] for cl in tc) / len(tc), 3) if tc else None}
    stats = {"run_id": run_id, "ontology": O.version(), "claims": len(claims), "valid": valid, "share_valid": round(valid / len(claims), 3),
             "assertions": n_assert, "quality_flags": dict(q), "per_tier": per_tier, "papers": pstats,
             "triples": triples, "gate_conforms": conforms,
             "gate_results": Counter(f"{s.rsplit('/', 1)[-1]} {sev}" for s, _, sev, _ in gate_hits),
             "files": [f"data/rdf/{n}" for n in triples]}
    (REPORTS / "rdf_stats.json").write_text(json.dumps(stats, indent=2, default=dict))
    print(f"[rdf] quality flags {dict(q)}")
    print(f"[rdf] claims {len(claims)}, valid {valid} ({stats['share_valid']:.1%}), assertions {n_assert}")
    for t, v in per_tier.items():
        print(f"  {t:10s} claims {v['claims']:6d}  valid {v['valid']:6d} ({v['share_valid']:.1%})")
    print(f"[rdf] papers {pstats}")
    print(f"[rdf] triples {triples} | gate conforms: {conforms} ({time.time() - t0:.0f} s)")
    if not conforms:
        for s, f_, sev, msg in gate_hits[:15]:
            print(f"  {sev} {s.rsplit('/', 1)[-1]} {f_}: {msg}")
        sys.exit("[rdf] gate shapes do not conform; see reports/shacl_report.txt (not loading)")


def load(run_id, replace):
    stats = json.loads((REPORTS / "rdf_stats.json").read_text())
    if stats["run_id"] != run_id or not stats["gate_conforms"]:
        sys.exit("[load] build this run first (make rdf) and make sure the gate shapes conform")
    run_graph = G["run_prefix"] + run_id
    loaded = {G["papers"]: fuseki.load(G["papers"], RDF / "papers.ttl", replace),
              G["assertions"]: fuseki.load(G["assertions"], RDF / "assertions.ttl", replace),
              run_graph: fuseki.load(run_graph, RDF / f"run_{run_id}.ttl", replace)}
    checks = {}
    for name in sorted(QUERIES.glob("m7_*.rq")):
        text = name.read_text().replace("%RUN_GRAPH%", run_graph)
        res = fuseki.query(text)
        checks[name.name] = res["boolean"] if "boolean" in res else \
            [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]
    stats["loaded"] = loaded
    stats["sanity"] = checks
    (REPORTS / "rdf_stats.json").write_text(json.dumps(stats, indent=2))
    for g_, n in loaded.items():
        print(f"[load] {g_}: {n} triples")
    for k, v in checks.items():
        print(f"[sanity] {k}: {v if not isinstance(v, list) else v[:5]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "load"])
    ap.add_argument("--run-id", default=CFG["extract"]["main_run"])
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    build(a.run_id) if a.step == "build" else load(a.run_id, a.replace)


if __name__ == "__main__":
    main()
