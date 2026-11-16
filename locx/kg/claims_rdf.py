"""M7: papers, run, mentions and assertions to RDF (SPEC §6), SHACL, load into Fuseki.

  python -m locx.kg.claims_rdf build [--run-id ID]   # Turtle + SHACL (quality flags, then gate)
  python -m locx.kg.claims_rdf load  [--run-id ID] [--replace]   # PUT graphs + sanity queries

build:
  1. run graph with provisional validity -> quality shapes (shapes/quality.shacl.ttl) on run + GO graph
     -> V5 impossible_location (invalidates) / V6 too_generic (warning) written back as flags
  2. final run graph (all mentions, flags, `locx:asserts` only when valid), assertions graph
     (one node per protein + GO term + polarity), papers graph (all corpus papers, authors)
  3. gate shapes (shapes/claims.shacl.ttl) on papers + run + assertions + GO + UniProt; must conform
Outputs: data/rdf/{papers,assertions,run_<id>}.ttl, data/runs/<id>/claims_final.jsonl,
reports/shacl_quality_report.txt, reports/shacl_report.txt, reports/rdf_stats.json.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter

import rdflib
from pyshacl import validate
from rdflib.namespace import SH

from locx.config import CFG, DATA, INTERIM, QUERIES, RDF, REPORTS, ROOT
from locx.io import read_jsonl, write_jsonl
from locx.kg import fuseki
from locx.kg.go_cc import NON_HUMAN_ROOTS, TOO_GENERIC
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
@prefix foaf:     <http://xmlns.com/foaf/0.1/> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

"""
POLARITY = {"present": "locx:Present", "absent": "locx:Absent"}
CERTAINTY = {"stated": "locx:Stated", "hedged": "locx:Hedged"}
SOURCE = {"finding": "locx:Finding", "background": "locx:Background"}
QUALITY_FLAGS = {LOCX + "ImpossibleLocationShape": "impossible_location", LOCX + "TooGenericShape": "too_generic"}
INVALIDATING = {"impossible_location"}


def iri(path: str) -> str:
    return f"<{LOCX}{path}>"


def integer(x) -> str:
    return f'"{int(x)}"^^xsd:integer'


def boolean(x) -> str:
    return "true" if x else "false"


def block(subject: str, pairs) -> str:
    pairs = [(p, o) for p, o in pairs if o is not None]
    return subject + " " + " ;\n    ".join(f"{p} {o}" for p, o in pairs) + " .\n"


def author_key(a: dict) -> str:
    base = f"{a.get('last_name') or a.get('name') or ''}_{a.get('initials') or ''}"
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


def check_shape_ids():
    """The GO IDs written in the shapes must be the label-verified ones from go_cc.py."""
    text = (SHAPES / "quality.shacl.ttl").read_text() + (SHAPES / "claims.shacl.ttl").read_text()
    for go_id in list(NON_HUMAN_ROOTS) + TOO_GENERIC:
        if go_iri(go_id) not in text:
            raise SystemExit(f"[rdf] shapes do not contain {go_id}; keep them in sync with locx/kg/go_cc.py")
    found = set(re.findall(r"obo:GO_\d{7}", text))
    expected = {go_iri(g) for g in list(NON_HUMAN_ROOTS) + TOO_GENERIC}
    if found - expected:
        raise SystemExit(f"[rdf] shapes contain GO IDs not verified in go_cc.py: {sorted(found - expected)}")


# --- papers --------------------------------------------------------------------------------------
def papers_ttl(papers, path):
    persons, c = {}, Counter()
    with open(path, "w") as f:
        f.write(PREFIXES)
        for p in papers:
            subj = f"pubmed:{p['pmid']}"
            ships = []
            for k, a in enumerate(p.get("authors") or [], 1):
                if a.get("collective"):
                    c["collective_authors_skipped"] += 1
                    continue
                key = author_key(a)
                if not key:
                    continue
                person = f"<https://orcid.org/{a['orcid']}>" if a.get("orcid") else iri(f"author/{key}")
                if person not in persons:
                    persons[person] = (a.get("name") or key, key, bool(a.get("orcid")))
                ship = iri(f"authorship/{p['pmid']}/{k}")
                ships.append(ship)
                f.write(block(ship, [("a", "locx:Authorship"), ("locx:author", person), ("locx:position", integer(k))]))
                c["authorships"] += 1
            date = p.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.get("date") or "") else None
            pairs = [("a", "fabio:JournalArticle"), ("dcterms:title", lit(p.get("title") or p.get("epmc_title") or "")),
                     ("locx:year", integer(p["year"]) if p.get("year") else None),
                     ("dcterms:date", f'"{date}"^^xsd:date' if date else None),
                     ("locx:journal", lit(p["journal"]) if p.get("journal") else None),
                     ("locx:doi", lit(p["doi"]) if p.get("doi") else None),
                     ("locx:citedByCount", integer(p["cited_by"]) if p.get("cited_by") is not None else None),
                     ("locx:inGOA", boolean(p.get("in_goa")))]
            pairs += [("locx:tier", lit(t)) for t in p["tiers"]]
            pairs += [("locx:hasAuthorship", s) for s in ships]
            f.write(block(subj, pairs))
            c["papers"] += 1
        for person, (name, key, has_orcid) in persons.items():
            f.write(block(person, [("a", "foaf:Person"), ("foaf:name", lit(name)), ("locx:authorKey", lit(key))]))
            c["persons_orcid" if has_orcid else "persons_name_key"] += 1
    return dict(c)


# --- run + mentions --------------------------------------------------------------------------------
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
    rid = meta["run_id"]
    run, agent = iri(f"run/{rid}"), iri(f"agent/{meta['served_name']}")
    mention_iri = {}
    with open(path, "w") as f:
        f.write(PREFIXES)
        f.write(block(run, [("a", "prov:Activity"), ("rdfs:label", lit(f"extraction run {rid}")),
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
            m = iri(f"mention/{rid}/{cl['pmid']}/{k_per_pmid[cl['pmid']]}")
            mention_iri[cl["claim_id"]] = m
            loc = cl["location"]
            prot_txt, loc_txt = mention_texts(cands[cl["pmid"]], cl)
            pairs = [("a", "locx:Mention"), ("locx:claimId", lit(cl["claim_id"])),
                     ("prov:wasDerivedFrom", f"pubmed:{cl['pmid']}"), ("prov:wasGeneratedBy", run),
                     ("locx:sentenceId", lit(cl["sentence"])), ("locx:sentenceText", lit(cl["sentence_text"])),
                     ("locx:sentenceStart", integer(cl["sentence_start"])), ("locx:sentenceEnd", integer(cl["sentence_end"])),
                     ("locx:protein", f"uniprot:{cl['protein']['uniprot']}"),
                     ("locx:location", go_iri(loc["go_id"]) if loc["go_id"] else None),
                     ("locx:otherLocationText", lit(loc["other_location_text"]) if loc.get("other_location_text") else None),
                     ("locx:groundingMethod", lit(loc["grounding"]["method"]) if loc.get("grounding") else None),
                     ("locx:polarity", POLARITY[cl["polarity"]]), ("locx:certainty", CERTAINTY[cl["certainty"]]),
                     ("locx:sourceType", SOURCE[cl["source_type"]]),
                     ("locx:cellType", lit(cl["cell_type"]) if cl["cell_type"] else None),
                     ("locx:organism", lit(cl["organism"])), ("locx:method", lit(cl["method"])),
                     ("locx:duplicateCount", integer(cl["duplicate_count"])),
                     ("locx:valid", boolean(cl["valid"])), ("locx:repairRound", integer(0))]
            pairs += [("locx:proteinMention", lit(t)) for t in prot_txt]
            pairs += [("locx:locationMention", lit(t)) for t in loc_txt]
            pairs += [("locx:condition", lit(t)) for t in cl["conditions"]]
            pairs += [("locx:flag", lit(fl)) for fl in cl["flags"]]
            if cl["valid"]:
                pairs.append(("locx:asserts", iri(assertion_key(cl))))
            f.write(block(m, pairs))
    return mention_iri


def assertion_key(cl) -> str:
    return f"assertion/{cl['protein']['uniprot']}_{cl['location']['go_id'].replace(':', '_')}_{cl['polarity']}"


def assertions_ttl(claims, path):
    seen = {}
    for cl in claims:
        if cl["valid"]:
            seen.setdefault(assertion_key(cl), cl)
    with open(path, "w") as f:
        f.write(PREFIXES)
        for key, cl in sorted(seen.items()):
            f.write(block(iri(key), [("a", "locx:Assertion"), ("locx:protein", f"uniprot:{cl['protein']['uniprot']}"),
                                     ("locx:location", go_iri(cl["location"]["go_id"])),
                                     ("locx:polarity", POLARITY[cl["polarity"]])]))
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


def build(run_id):
    t0 = time.time()
    check_shape_ids()
    run_dir = RUNS / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    claims = list(read_jsonl(run_dir / "claims.jsonl"))
    cands = {r["pmid"]: r for r in read_jsonl(INTERIM / "candidates.jsonl")}
    papers = list(read_jsonl(INTERIM / "papers.jsonl"))
    run_path = RDF / f"run_{run_id}.ttl"

    # 1. quality shapes on the provisional run graph
    for cl in claims:
        cl["valid"] = cl["valid_provisional"]
    mention_iri = run_ttl(meta, claims, cands, run_path)
    _, hits = shacl([run_path, RDF / "go_cc.ttl"], SHAPES / "quality.shacl.ttl",
                    REPORTS / "shacl_quality_report.txt", "quality shapes (V5, V6)")
    by_mention = {}
    for shape, focus, _, _ in hits:
        if shape in QUALITY_FLAGS:
            by_mention.setdefault(focus, set()).add(QUALITY_FLAGS[shape])
    q = Counter()
    for cl in claims:
        new = by_mention.get(mention_iri[cl["claim_id"]].strip("<>"), set())
        for fl in sorted(new):
            cl["flags"].append(fl)
            q[fl] += 1
        cl["valid"] = cl["valid_provisional"] and not (new & INVALIDATING)
        q["invalidated_by_shacl"] += cl["valid_provisional"] and not cl["valid"]

    # 2. final graphs
    run_ttl(meta, claims, cands, run_path)
    n_assert = assertions_ttl(claims, RDF / "assertions.ttl")
    pstats = papers_ttl(papers, RDF / "papers.ttl")
    write_jsonl(run_dir / "claims_final.jsonl", claims)

    # 3. gate shapes
    conforms, gate_hits = shacl([RDF / "papers.ttl", run_path, RDF / "assertions.ttl", RDF / "go_cc.ttl",
                                 RDF / "uniprot_human.ttl"], SHAPES / "claims.shacl.ttl",
                                REPORTS / "shacl_report.txt", "gate shapes (SPEC M7)")
    triples = {}
    for name in ("papers.ttl", run_path.name, "assertions.ttl"):
        g = rdflib.Graph().parse(RDF / name, format="turtle")
        triples[name] = len(g)
    valid = sum(cl["valid"] for cl in claims)
    per_tier = {}
    for t in meta["tiers"]:
        tc = [cl for cl in claims if t in cl["tiers"]]
        per_tier[t] = {"mentions": len(tc), "valid": sum(cl["valid"] for cl in tc),
                       "share_valid": round(sum(cl["valid"] for cl in tc) / len(tc), 3) if tc else None}
    stats = {"run_id": run_id, "mentions": len(claims), "valid": valid, "share_valid": round(valid / len(claims), 3),
             "assertions": n_assert, "quality_flags": dict(q), "per_tier": per_tier, "papers": pstats,
             "triples": triples, "gate_conforms": conforms,
             "gate_results": Counter(f"{s.rsplit('/', 1)[-1]} {sev}" for s, _, sev, _ in gate_hits),
             "files": [f"data/rdf/{n}" for n in triples]}
    (REPORTS / "rdf_stats.json").write_text(json.dumps(stats, indent=2, default=dict))
    print(f"[rdf] quality flags {dict(q)}")
    print(f"[rdf] mentions {len(claims)}, valid {valid} ({stats['share_valid']:.1%}), assertions {n_assert}")
    for t, v in per_tier.items():
        print(f"  {t:10s} mentions {v['mentions']:5d}  valid {v['valid']:5d} ({v['share_valid']:.1%})")
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
