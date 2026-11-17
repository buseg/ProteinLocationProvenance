"""M11 acceptance (demo v2 v2.py on 8501, and the old v1 streamlit_app_v1.py): time every page's queries (cold, no cache) for TP53 and TFEB, check the verdicts shown,
and run each page headlessly with streamlit's AppTest to catch exceptions. -> reports/demo_check.json"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402
from locx.config import REPORTS  # noqa: E402


def timed(fns):
    t = time.time()
    for f in fns:
        f()
    return round(time.time() - t, 2)


def main():
    out = {"pages_seconds": {}, "proteins": {}}
    out["pages_seconds"]["overview"] = timed([D.run_info, D.run_counts, D.verdict_distribution, D.manifest_sizes])
    out["pages_seconds"]["curation_gaps(min 2)"] = timed([lambda: D.curation_gaps(2)])
    out["pages_seconds"]["conflicts"] = timed([D.conflicts])
    out["pages_seconds"]["errors(other_ungrounded)"] = timed([D.error_flags, lambda: D.errors("other_ungrounded")])
    prot = {r["symbol"]: D.local(r["protein"]) for r in D.proteins()[0]}
    for sym in ("TP53", "TFEB"):
        acc = prot[sym]
        t = time.time()
        lit = D.protein_literature(acc)[0]
        D.protein_goa(acc)
        D.proteins()
        explorer = round(time.time() - t, 2)
        details = {}
        for x in lit:
            k = D.local(x["a"])
            details[k] = timed([lambda k=k: D.assertion(k), lambda k=k: D.assertion_goa(k),
                                lambda k=k: D.assertion_mentions(k), lambda k=k: D.assertion_authors(k),
                                lambda k=k: D.assertion(D.opposite(k)), lambda k=k: D.assertion_mentions(D.opposite(k)),
                                lambda k=k: D.assertion_authors(D.opposite(k))])
        t = time.time()
        D.protein_literature(acc)
        D.protein_goa(acc)
        terms = {x["term"] for x in lit} | {g["term"] for g in D.protein_goa(acc)[0]}
        D.go_parents(tuple(terms))
        D.neighborhood_papers(acc)
        graph_s = round(time.time() - t, 2)
        verdicts = sorted({D.local(x["verdict"]) for x in lit})
        out["proteins"][sym] = {"accession": acc, "assertions": len(lit), "verdicts": verdicts,
                                "explorer_seconds": explorer, "graph_seconds": graph_s, "detail_seconds_max": max(details.values()) if details else None,
                                "has_consistent": "Consistent" in verdicts, "has_novel": "Novel" in verdicts,
                                "has_conflicting": "Conflicting" in verdicts}
    # headless render of every page
    from streamlit.testing.v1 import AppTest
    rendered = {}
    app = str(Path(__file__).resolve().parent / "streamlit_app_v1.py")
    first_key = D.local(D.protein_literature(prot["TP53"])[0][0]["a"])
    for page, state in [("overview", {}), ("protein_explorer", {"protein": prot["TP53"]}),
                        ("assertion_detail", {"assertion": first_key}), ("curation_gaps", {}), ("conflicts", {}), ("errors", {}),
                        ("graph_neighborhood", {"protein": prot["TP53"]})]:
        at = AppTest.from_file(app, default_timeout=60)
        for k, v in {**state, "_test_page": page}.items():
            at.session_state[k] = v
        at.run()
        rendered[page] = {"exceptions": [str(e.value) for e in at.exception], "titles": [t.value for t in at.title]}
    out["headless"] = rendered
    # demo v2 (app/v2.py): cold query timings per page and a headless render of every page
    v2s = {"home": timed([D.corpus_size, D.run_counts, D.run_info, D.assertions_all])}
    for sym in ("TP53", "TFEB"):
        acc = prot[sym]
        lit = D.protein_literature(acc)[0]
        t = time.time()
        D.protein_literature(acc)
        D.protein_goa(acc)
        D.protein_years(acc)
        D.compartments(tuple(sorted({x["term"] for x in lit} | {g["term"] for g in D.protein_goa(acc)[0]})))
        v2s[f"protein({sym})"] = round(time.time() - t, 2)
        v2s[f"evidence+provenance({sym}, max)"] = max(
            timed([lambda k=k: D.assertion(k), lambda k=k: D.assertion_mentions(k),
                   lambda k=k: D.provenance_authors(k), lambda k=k: D.provenance_goa(k),
                   lambda k=k: D.assertion(D.opposite(k))])
            for k in [D.local(x["a"]) for x in lit])
    v2s["explore"] = timed([D.assertions_all])
    v2s["quality"] = timed([D.error_flags, D.run_info])
    v2r = {}
    app2 = str(Path(__file__).resolve().parent / "v2.py")
    for page, state in [("home", {}), ("protein_page", {"protein": prot["TP53"]}),
                        ("protein_page", {"protein": prot["TP53"], "assertion": first_key}),
                        ("provenance_page", {"protein": prot["TP53"], "assertion": first_key}),
                        ("explore", {}), ("quality", {})]:
        at = AppTest.from_file(app2, default_timeout=120)
        for k, v in {**state, "_test_page": page}.items():
            at.session_state[k] = v
        at.run()
        v2r[page + ("+assertion" if "assertion" in state and page == "protein_page" else "")] = {
            "exceptions": [str(e.value) for e in at.exception]}
    out["v2"] = {"pages_seconds": v2s, "headless": v2r, "worst_page_seconds": max(v2s.values())}
    worst = max(list(out["pages_seconds"].values()) + [v["explorer_seconds"] for v in out["proteins"].values()]
                + [v["detail_seconds_max"] for v in out["proteins"].values()]
                + [v["graph_seconds"] for v in out["proteins"].values()])
    out["worst_page_seconds"] = worst
    out["acceptance"] = {"pages_under_3s": worst < 3,
                         "no_exceptions": all(not v["exceptions"] for v in rendered.values()),
                         "tp53_tfeb_consistent": all(v["has_consistent"] for v in out["proteins"].values()),
                         "tp53_tfeb_conflicting": all(v["has_conflicting"] for v in out["proteins"].values()),
                         "tp53_tfeb_novel": all(v["has_novel"] for v in out["proteins"].values()),
                         "v2_pages_under_3s": out["v2"]["worst_page_seconds"] < 3,
                         "v2_no_exceptions": all(not v["exceptions"] for v in v2r.values())}
    (REPORTS / "demo_check.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
