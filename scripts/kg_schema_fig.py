"""Draw the knowledge graph schema from reports/kg_schema.json (scripts/kg_schema.py):

- reports/fig_kg_<part>.png/.svg for four parts of the graph (papers, claims, curation, uniprot): classes as boxes,
  links between them as arrows, coloured by the named graph that stores the link; each box gives an example IRI and
  how many fields each graph adds. Individuals typed with a class of an outside ontology (a location: a GO class; an
  evidence: an ECO class) are linked to that class with a dashed "is a" arrow (slides).
- reports/fig_kg_schema.png/.svg: one card per class with every field and what it points to (report).

Box positions are layout only (PARTS below); classes, fields, links and graphs all come from the JSON.
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx.config import REPORTS  # noqa: E402

SURFACE, INK, INK2, MUTED, LINE = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#d6d5d0"
# one fixed categorical slot per named graph (dataviz reference palette, light mode)
GRAPH_COLOR = {"assertions": "#2a78d6", "run": "#eb6834", "goa-human": "#1baf7a", "uniprot-human": "#eda100",
               "abstracts": "#e87ba4", "support": "#008300", "verdicts": "#6250d6", "papers": "#e34948"}
# (the outside ontologies GO, ECO and UniProt locations are drawn as dashed boxes, not coloured by graph)
NAME = {"fabio:JournalArticle": "Paper", "foaf:Person": "Person", "locx:Authorship": "Authorship",
        "locx:Claim": "Claim", "prov:SoftwareAgent": "Model (agent)", "locx:Assertion": "Assertion", "locx:CuratedAnnotation": "GOA annotation",
        "up:Protein": "Protein (UniProt)", "fabio:Journal": "Journal",
        "locx:Support": "Support", "locx:AuthorGroup": "Author group", "locx:Verdict": "Verdict",
        "oa:SpecificResource": "Evidence sentence",
        "fabio:Abstract": "Abstract", "foaf:Organization": "Institution (ROR)", "up:Gene": "Gene",
        "up:Subcellular_Location_Annotation": "UniProt location", "rdf:Statement": "UniProt evidence",
        "c4o:GlobalCitationCount": "Citation count", "prov:Collection": "Corpus sample",
        "locx:CorpusBuilding": "Corpus building", "locx:ExtractionRun": "Extraction run",
        "locx:SupportComputation": "Support computation", "locx:VerdictComputation": "Verdict computation",
        "locx:GOAContext": "GOA context", "locx:ContextPart": "Context part",
        "locx:FreeTextContext": "Free-text context", "GO class individual": "Location (an individual)",
        "ECO class individual": "Evidence (an individual)", "up:Structured_Name": "Protein names",
        "up:Resource": "GeneID link", "up:Attribution": "Evidence attribution", "up:Journal_Citation": "Citation",
        "UniProt located-in node": "Located-in node"}
# the four parts: title, box centres (inches, 4 columns x 3 rows on a 17.6 x 10 canvas), outside classes drawn as
# extra boxes, and "is a" links from individuals to them
C1, C2, C3, C4, R1, R2, R3 = 1.9, 6.4, 10.9, 15.4, 8.4, 5.0, 1.5
GO_BOX = ("GO term", "a class of GO (graph go)", "obo:GO_0005634 (nucleus)")
ECO_BOX = ("ECO term", "a class of ECO (graph eco)", "obo:ECO_0000314 (direct assay ...)")
PARTS = {
    "papers": ("Papers, people and the corpus", {
        "locx:CorpusBuilding": (C1, R1), "prov:Collection": (C2, R1), "fabio:JournalArticle": (C3, R1),
        "fabio:Journal": (C4, R1), "fabio:Abstract": (C2, R2), "locx:Authorship": (C3, R2),
        "c4o:GlobalCitationCount": (C4, R2), "foaf:Organization": (C2, R3), "foaf:Person": (C3, R3),
        "locx:AuthorGroup": (C4, R3)}, {}, []),
    "claims": ("Claims and their evidence", {
        "prov:SoftwareAgent": (C1, R1), "locx:ExtractionRun": (C2, R1), "fabio:JournalArticle": (C3, R1),
        "fabio:Abstract": (C4, R1), "locx:Claim": (C2, R2), "locx:Assertion": (C3, R2), "oa:SpecificResource": (C4, R2),
        "up:Protein": (C2, R3), "GO class individual": (C3, R3), "locx:FreeTextContext": (C1, R2)},
        {"GO term": ((C4, R3), GO_BOX)}, [("GO class individual", "GO term", "is a (rdf:type)")]),
    "curation": ("Curation (GOA) and the comparison with it", {
        "locx:VerdictComputation": (C1, R1), "locx:Verdict": (C2, R1), "locx:Assertion": (C3, R1),
        "locx:Support": (C4, R1), "locx:GOAContext": (C1, R2), "locx:CuratedAnnotation": (C2, R2),
        "up:Protein": (C3, R2), "locx:SupportComputation": (C4, R2), "ECO class individual": (C1, R3),
        "GO class individual": (C3, R3)},
        {"ECO term": ((C2, R3), ECO_BOX), "GO term": ((C4, R3), GO_BOX)},
        [("ECO class individual", "ECO term", "is a (rdf:type)"), ("GO class individual", "GO term", "is a (rdf:type)")]),
    "uniprot": ("Proteins (UniProt's own RDF)", {
        "up:Gene": (C1, R1), "up:Protein": (C2, R1), "up:Structured_Name": (C3, R1), "up:Resource": (C4, R1),
        "up:Subcellular_Location_Annotation": (C2, R2), "UniProt located-in node": (C3, R2),
        "rdf:Statement": (C2, R3), "up:Attribution": (C1, R2), "up:Journal_Citation": (C1, R3)},
        {"UniProt location term": ((C4, R2), ("UniProt location term", "graph uniprot-locations",
                                                                        "uplocation:191 (exactMatch GO)"))},
        [("UniProt located-in node", "UniProt location term", "cellularComponent")]),
}
W_IN, H_IN = 17.6, 10.0
BW = 3.0
MONO = "DejaVu Sans Mono"


def load():
    s = json.loads((REPORTS / "kg_schema.json").read_text())
    classes = {}                                    # class -> {"home": graph, "example": iri, "parts": [(graph, fields)]}
    for g in s["graphs"]:
        for c in g["classes"]:
            key = c["class"]
            if key == "(untyped)" and g["name"] == "uniprot-human":   # UniProt gives its located-in nodes no class
                key = "UniProt located-in node"
            k = classes.setdefault(key, {"home": None, "example": None, "parts": []})
            if c["typed_here"]:
                k["home"], k["example"] = g["name"], c["example_subject"]
            if c["fields"]:
                fields = c["fields"]
                if g["name"] == "uniprot-human":   # values that are located-in nodes point to that box
                    fields = [{**f, "range": ["UniProt located-in node" if r == "(untyped)" else r for r in f["range"]]}
                              for f in fields]
                k["parts"].append((g["name"], fields))
    return s, classes


def links(classes):
    """(from class, to class, graph) -> predicates, for fields whose values are instances of a drawn class."""
    out = {}
    for c, k in classes.items():
        for g, fields in k["parts"]:
            for f in fields:
                for r in f["range"]:
                    if r in classes:
                        out.setdefault((c, r, g), []).append(f["predicate"].split(":", 1)[1])
    return out


def box_h(k):
    return 0.88 + 0.24 * len(k["parts"])


def overview(classes, title, pos, extra_boxes, extra_links):
    fig, ax = plt.subplots(figsize=(W_IN, H_IN))
    fig.set_facecolor(SURFACE)
    ax.set_xlim(0, W_IN)
    ax.set_ylim(0, H_IN)
    ax.axis("off")
    ax.set_title(f"locx knowledge graph, {title} (colour = named graph that stores the triples)",
                 loc="left", color=INK, fontsize=15, pad=6)
    POS = dict(pos)
    classes = {c: k for c, k in classes.items() if c in POS}   # this part's classes only; fig_kg_schema has them all
    rect = {}
    for c, k in classes.items():
        x, y = POS[c]
        h = box_h(k)
        rect[c] = (x - BW / 2, y - h / 2, BW, h)
        ax.add_patch(FancyBboxPatch((x - BW / 2, y - h / 2), BW, h, boxstyle="round,pad=0,rounding_size=0.08",
                                    fc="white", ec=LINE, lw=1.2, zorder=3))
        ax.add_patch(Rectangle((x - BW / 2, y - h / 2), 0.1, h, fc=GRAPH_COLOR.get(k["home"], MUTED), ec="none",
                               zorder=4))
        top = y + h / 2
        ax.text(x - BW / 2 + 0.22, top - 0.2, f"{NAME.get(c, c)}", fontsize=12, weight="bold", color=INK,
                va="center", zorder=5)
        ax.text(x - BW / 2 + 0.22, top - 0.44, c, fontsize=8.4, color=MUTED, va="center", zorder=5)
        ex = k["example"] or ""
        ax.text(x - BW / 2 + 0.22, top - 0.66, ex if len(ex) <= 39 else ex[:38] + "…", fontsize=7.4,
                family=MONO, color=INK2, va="center", zorder=5)
        for i, (g, fields) in enumerate(k["parts"]):
            yy = top - 0.92 - 0.24 * i
            ax.add_patch(Rectangle((x - BW / 2 + 0.22, yy - 0.06), 0.12, 0.12, fc=GRAPH_COLOR.get(g, MUTED),
                                   ec="none", zorder=5))
            ax.text(x - BW / 2 + 0.42, yy, f"{g}: {len(fields)} field{'s' if len(fields) != 1 else ''}",
                    fontsize=8.6, color=INK2, va="center", zorder=5)

    for key, ((x, y), (label, sub, ex)) in extra_boxes.items():   # outside classes (not in our data graphs)
        h = 0.95
        rect[key] = (x - BW / 2, y - h / 2, BW, h)
        POS[key] = (x, y)
        ax.add_patch(FancyBboxPatch((x - BW / 2, y - h / 2), BW, h, boxstyle="round,pad=0,rounding_size=0.08",
                                    fc=SURFACE, ec=MUTED, lw=1.2, ls="--", zorder=3))
        top = y + h / 2
        ax.text(x - BW / 2 + 0.22, top - 0.2, label, fontsize=12, weight="bold", color=INK, va="center", zorder=5)
        ax.text(x - BW / 2 + 0.22, top - 0.44, sub, fontsize=8.4, color=MUTED, va="center", zorder=5)
        ax.text(x - BW / 2 + 0.22, top - 0.66, ex, fontsize=7.4, family=MONO, color=INK2, va="center", zorder=5)

    def anchor(c, toward):
        x0, y0, w, h = rect[c]
        cx, cy = x0 + w / 2, y0 + h / 2
        tx, ty = toward
        dx, dy = tx - cx, ty - cy
        if dx == 0 and dy == 0:
            return cx, cy
        sx = (w / 2) / abs(dx) if dx else float("inf")
        sy = (h / 2) / abs(dy) if dy else float("inf")
        s = min(sx, sy)
        return cx + dx * s, cy + dy * s

    for (a, b, g), preds in sorted(links(classes).items()):
        col = GRAPH_COLOR.get(g, MUTED)
        label = ", ".join(preds) if len(preds) <= 2 else ", ".join(preds[:2]) + f" +{len(preds) - 2}"
        if a == b:                                  # GO term -> GO term (is_a, part_of): loop on the right
            x0, y0, w, h = rect[a]
            p1, p2 = (x0 + w, y0 + h * 0.7), (x0 + w, y0 + h * 0.3)
            ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle="arc3,rad=-1.6", arrowstyle="-|>",
                                         mutation_scale=12, color=col, lw=1.4, zorder=2))
            ax.text(x0 + w + 0.55, y0 + h / 2, label, fontsize=8.6, color=INK2, va="center")
            continue
        pa, pb = POS[a], POS[b]
        if abs(pa[0] - pb[0]) < 0.01 and abs(pa[1] - pb[1]) > 4:   # same column, skipping a box: curve to the right
            p1 = (rect[a][0] + rect[a][2], rect[a][1] + rect[a][3] / 2)
            p2 = (rect[b][0] + rect[b][2], rect[b][1] + rect[b][3] / 2)
            rad = -0.28 if p2[1] < p1[1] else 0.28   # bend to the right (arc3 bends left of p1 -> p2 for rad > 0)
            ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>",
                                         mutation_scale=13, color=col, lw=1.5, shrinkA=2, shrinkB=2, zorder=2))
            ax.text(p1[0] + 0.14 * abs(p2[1] - p1[1]), (p1[1] + p2[1]) / 2, label, fontsize=8.6, color=INK,
                    ha="center", va="center", zorder=6, bbox=dict(boxstyle="round,pad=0.18", fc=SURFACE, ec="none"))
            continue
        if abs(pa[1] - pb[1]) < 0.01 and abs(pa[0] - pb[0]) > BW * 1.6:   # same row, skipping a box: curve above
            p1 = (rect[a][0] + (rect[a][2] if pb[0] > pa[0] else 0), rect[a][1] + rect[a][3])
            p2 = (rect[b][0] + (rect[b][2] if pa[0] > pb[0] else 0), rect[b][1] + rect[b][3])
            rad = -0.25 if p2[0] > p1[0] else 0.25   # bend upward (matplotlib bends to the left of p1 -> p2 for rad > 0)
            ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>",
                                         mutation_scale=13, color=col, lw=1.5, shrinkA=2, shrinkB=2, zorder=2))
            ax.text((p1[0] + p2[0]) / 2, p1[1] + 0.125 * abs(p2[0] - p1[0]), label, fontsize=8.6, color=INK,
                    ha="center", va="center", zorder=6, bbox=dict(boxstyle="round,pad=0.18", fc=SURFACE, ec="none"))
            continue
        p1, p2 = anchor(a, pb), anchor(b, pa)
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=13, color=col, lw=1.5,
                                     shrinkA=2, shrinkB=2, zorder=2))
        if abs(p1[1] - p2[1]) < 0.01:              # horizontal: label above the arrow, one predicate per line
            ax.text((p1[0] + p2[0]) / 2, p1[1] + 0.08, "\n".join(preds) if len(", ".join(preds)) > 14
                    else ", ".join(preds), fontsize=8.6, color=INK, ha="center", va="bottom", zorder=6,
                    linespacing=1.15)
            continue
        t = 0.5 if abs(p1[0] - p2[0]) < 0.01 else 0.3   # crossing diagonals: label near the source
        mx, my = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t
        ax.text(mx, my, label, fontsize=8.6, color=INK, ha="center", va="center", zorder=6,
                bbox=dict(boxstyle="round,pad=0.18", fc=SURFACE, ec="none"))
    for a, b, how in extra_links:                   # a node -> the outside term it is an instance of, or points to
        if a in rect and b in rect:
            p1, p2 = anchor(a, POS[b]), anchor(b, POS[a])
            ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=13, color=MUTED, lw=1.5, ls="--",
                                         shrinkA=2, shrinkB=2, zorder=2))
            ax.text((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2 + 0.12, how, fontsize=8.6, color=INK2,
                    ha="center", va="bottom", zorder=6)
    # legend: graphs, in a row at the bottom left
    x = 0.4
    used = {g for c in classes.values() for g, _ in c["parts"]} | {c["home"] for c in classes.values()}
    for g, col in ((g, c) for g, c in GRAPH_COLOR.items() if g in used):
        ax.add_patch(Rectangle((x, 0.18), 0.16, 0.16, fc=col, ec="none"))
        ax.text(x + 0.24, 0.26, g, fontsize=9, color=INK2, va="center")
        x += 0.5 + 0.095 * len(g)
    return fig


def card_rows(fields):
    out = []
    for f in fields:
        rng = f["range"][0]
        typ = f"→ {NAME.get(rng, rng)}" if ":" in rng and not rng.startswith(("xsd", "text")) else rng
        if "values" in f and rng in ("IRI", "boolean") and len(f["values"]) <= 6:   # a small fixed set: list it
            typ = " | ".join(v.split(":", 1)[-1] for v in f["values"])
        if len(f["range"]) > 1:
            typ += " / " + " / ".join(f["range"][1:])
        out.append((f["predicate"], typ if len(typ) <= 34 else typ[:33] + "…"))
    return out


def cards(classes):
    order = ["fabio:JournalArticle", "locx:Authorship", "foaf:Person", "locx:Claim", "oa:SpecificResource",
             "locx:FreeTextContext", "locx:CorpusBuilding", "locx:ExtractionRun", "prov:SoftwareAgent", "locx:Assertion",
             "locx:Support", "locx:AuthorGroup", "locx:Verdict", "locx:SupportComputation", "locx:VerdictComputation",
             "locx:CuratedAnnotation", "locx:GOAContext", "locx:ContextPart", "up:Protein", "GO class individual",
             "ECO class individual"]
    order = [c for c in order if c in classes] + [c for c in classes if c not in order]
    W, RH, GAP, COLS = 5.0, 0.205, 0.35, 4
    cols = [0.0] * COLS
    placed = []
    for c in order:
        k = classes[c]
        n = sum(len(f) + 1 for _, f in k["parts"]) or 1
        h = 0.75 + RH * n
        i = cols.index(min(cols))
        placed.append((c, i, cols[i], h))
        cols[i] += h + GAP
    H = max(cols) + 0.9
    fig, ax = plt.subplots(figsize=(COLS * (W + 0.3) + 0.3, H))
    fig.set_facecolor(SURFACE)
    ax.set_xlim(0, COLS * (W + 0.3) + 0.3)
    ax.set_ylim(H, 0)
    ax.axis("off")
    ax.text(0.3, 0.35, "locx knowledge graph: every class and its fields, grouped by the named graph that stores them",
            fontsize=15, color=INK, va="center")
    for c, i, y, h in placed:
        k = classes[c]
        x = 0.3 + i * (W + 0.3)
        y += 0.8
        ax.add_patch(FancyBboxPatch((x, y), W, h, boxstyle="round,pad=0,rounding_size=0.06", fc="white", ec=LINE,
                                    lw=1.1))
        ax.add_patch(Rectangle((x, y), 0.09, h, fc=GRAPH_COLOR.get(k["home"], MUTED), ec="none"))
        ax.text(x + 0.22, y + 0.24, NAME.get(c, c), fontsize=12, weight="bold", color=INK, va="center")
        title = NAME.get(c, c)
        if title != c and 0.14 * len(title) + 0.075 * len(c) < W - 0.45:   # class name at the right, if it fits
            ax.text(x + W - 0.12, y + 0.24, c, fontsize=8.5, color=MUTED, va="center", ha="right")
        ax.text(x + 0.22, y + 0.5, k["example"] or "", fontsize=7.6, family=MONO, color=INK2, va="center")
        yy = y + 0.75
        for g, fields in k["parts"]:
            ax.add_patch(Rectangle((x + 0.22, yy + 0.03), 0.13, 0.13, fc=GRAPH_COLOR.get(g, MUTED), ec="none"))
            ax.text(x + 0.42, yy + 0.095, f"in {g}", fontsize=8.4, color=INK2, va="center", style="italic")
            yy += RH
            for pred, typ in card_rows(fields):
                ax.text(x + 0.42, yy + 0.095, pred, fontsize=7.9, family=MONO, color=INK, va="center")
                ax.text(x + W - 0.12, yy + 0.095, typ, fontsize=7.9, color=INK2, va="center", ha="right")
                yy += RH
    return fig


def main():
    _, classes = load()
    figs = [(f"fig_kg_{key}", overview(classes, title, pos, boxes, extra))
            for key, (title, pos, boxes, extra) in PARTS.items()]
    for name, fig in figs + [("fig_kg_schema", cards(classes))]:
        for ext in ("png", "svg"):
            fig.savefig(REPORTS / f"{name}.{ext}", dpi=170, facecolor=SURFACE, bbox_inches="tight")
        plt.close(fig)
        print(f"[schema-fig] -> {REPORTS / name}.png/.svg")


if __name__ == "__main__":
    main()
