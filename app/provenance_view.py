"""Provenance graph for one assertion as a fixed-layout SVG (no physics, same picture every time).

Columns, left to right, follow the RDF:
  author group box ⟶ paper  ⟵ prov:wasDerivedFrom ⟵  claim (mention)  ⟶ locx:asserts ⟶  assertion  ⟶ locx:goaSame/... ⟶  GOA rows
and the extraction run (prov:Activity, its agent = the model) sits above the claims, which were prov:wasGeneratedBy it.
Papers are boxed by independent author group; the box header names the authors that link its papers (shared ORCID or
name key in >= 2 of them, SPEC M8), which is why several papers can count as one group.
All text from papers is escaped; links are built only from validated PMIDs / ORCID IRIs.
"""
import html
import re
from collections import defaultdict

PUBMED = "https://pubmed.ncbi.nlm.nih.gov/"
W = 1300                             # drawn at natural size (no scaling), the page scrolls sideways if narrower
X_PAPER, W_PAPER = 8, 360            # group boxes; paper cards inside are inset by 10
X_CLAIM, W_CLAIM = 440, 340
X_ASSERT, W_ASSERT = 832, 200
X_GOA, W_GOA = 1082, 212
CLAIM_H, GAP = 64, 8
GROUP_HEAD, GROUP_PAD, GROUP_GAP = 40, 8, 16
TOP = 150                            # header + run box
GOA_H = 44

INK, INK2, MUTED, LINE, CARD, BG = "#0b0b0b", "#52514e", "#8b8a85", "#c3c2b7", "#ffffff", "#fcfcfb"
CERTAINTY = {"Finding": "#1baf7a", "Hedged": "#eda100", "Background": "#8b8a85"}
LINK_SHORT = {"same": "same term", "narrower": "more specific", "broader": "broader"}
LINK_TEXT = {"same": "same GO term", "narrower": "GOA term is more specific", "broader": "GOA term is broader"}


def esc(s):
    return html.escape(str(s or ""), quote=True)


def local(iri):
    return (iri or "").rsplit("/", 1)[-1]


def pmid_url(paper_iri):
    p = local(paper_iri)
    return PUBMED + p + "/" if p.isdigit() else None


def snippet(sentence, marks, width=190):
    """Sentence cut around the first mention, mentions in bold (escaped)."""
    s = sentence or ""
    pos = min([s.lower().find(m.lower()) for m in marks if m and m.lower() in s.lower()] or [0])
    start = max(0, min(pos - 60, len(s) - width))
    cut = s[start:start + width]
    out = esc(cut)
    for m in sorted({m for m in marks if m}, key=len, reverse=True):
        out = re.sub(f"(?i)({re.escape(esc(m))})", r"<b>\1</b>", out)
    return ("…" if start > 0 else "") + out + ("…" if start + width < len(s) else "")


def merge_mentions(rows):
    by = {}
    for x in rows:
        m = by.setdefault(x["m"], {**x, "conditions": set(), "marks": set()})
        if x.get("condition"):
            m["conditions"].add(x["condition"])
        m["marks"] |= {x.get("proteinMention"), x.get("locationMention")}
    return list(by.values())


def author_groups(mentions, authors):
    """[(group_id, [paper IRIs], linking author names, all authors by paper)] largest group first."""
    paper_group, cites = {}, {}
    for m in mentions:
        paper_group.setdefault(m["paper"], m.get("group") or ("solo:" + m["paper"]))
        cites[m["paper"]] = int(m.get("citations") or 0)
    by_paper = defaultdict(list)
    for a in authors:
        by_paper[a["paper"]].append(a)
    groups = defaultdict(list)
    for p, g in paper_group.items():
        groups[g].append(p)
    out = []
    for g, papers in groups.items():
        papers.sort(key=lambda p: (-cites.get(p, 0), p))
        ident = defaultdict(set)      # identity (ORCID or name key) -> papers
        names = {}
        for p in papers:
            for a in by_paper.get(p, []):
                ids = {"key:" + a["key"]} | ({"orcid:" + a["person"]} if a["person"].startswith("https://orcid.org/") else set())
                for i in ids:
                    ident[i].add(p)
                    names.setdefault(i, (a["name"], a["person"]))
        link = []
        if len(papers) > 1:
            seen = set()
            for i, ps in sorted(ident.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                if len(ps) >= 2 and names[i][0] not in seen:
                    seen.add(names[i][0])
                    link.append(names[i])
        out.append((g, papers, link, by_paper))
    out.sort(key=lambda t: (-len(t[1]), -max(cites.get(p, 0) for p in t[1])))
    return out


def person_html(name, person):
    if person.startswith("https://orcid.org/"):
        return (f"<a href='{esc(person)}' target='_blank' title='ORCID {esc(local(person))}'>{esc(name)}"
                f"<span class='orcid'>iD</span></a>")
    return esc(name)


def fo(x, y, w, h, inner, cls=""):
    return (f"<foreignObject x='{x}' y='{y}' width='{w}' height='{h}'>"
            f"<div xmlns='http://www.w3.org/1999/xhtml' class='{cls}' style='height:{h}px'>{inner}</div></foreignObject>")


def edge(x1, y1, x2, y2, color=LINE, dash=False, width=1.3):
    mx = (x1 + x2) / 2
    d = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
    dash_attr = 'stroke-dasharray="5 4"' if dash else ""
    return (f"<path d='{d}' fill='none' stroke='{color}' stroke-width='{width}' {dash_attr} "
            f"marker-end='url(#arrow)'/>")


CSS = f"""
<style>
  body {{ margin:0; background:{BG}; font-family: 'Source Sans 3', 'Source Sans Pro', system-ui, sans-serif; color:{INK}; }}
  svg {{ display:block; }}
  .wrap {{ overflow-x:auto; }}
  .card {{ box-sizing:border-box; background:{CARD}; border:1px solid {LINE}; border-radius:8px; padding:6px 9px;
           font-size:12.5px; line-height:1.3; overflow:hidden; }}
  .card:hover {{ border-color:{INK2}; }}
  .claim .s {{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .meta {{ color:{INK2}; font-size:11.5px; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .chip {{ display:inline-block; padding:0 6px; border-radius:9px; font-size:11px; color:#fff; margin-right:4px; }}
  .paper .h, .goa .h {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .paper .t {{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; color:{INK2}; }}
  .paper a, .ghead a, .goa a {{ color:{INK}; text-decoration:none; border-bottom:1px dotted {MUTED}; }}
  .ghead {{ font-size:12.5px; color:{INK2}; padding:7px 10px 0 10px; line-height:1.3; overflow:hidden; }}
  .ghead b {{ color:{INK}; }}
  .orcid {{ background:#a6ce39; color:#fff; border-radius:50%; font-size:8px; padding:1px 2px; margin-left:2px;
            vertical-align:super; }}
  .assert {{ box-sizing:border-box; border-radius:10px; padding:12px; font-size:13px; line-height:1.4; color:{INK};
             background:{CARD}; border:2px solid {INK}; }}
  .assert .big {{ font-size:17px; font-weight:700; }}
  .run {{ box-sizing:border-box; border:1px dashed {INK2}; border-radius:8px; padding:6px 10px; font-size:12px;
          line-height:1.35; background:{BG}; color:{INK2}; }}
  .run b {{ color:{INK}; }}
  .goa {{ font-size:12px; }}
  .goa .not {{ color:#b3261e; font-weight:700; }}
  .colhead {{ font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:{MUTED}; }}
  .pred {{ font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; fill:{MUTED}; }}
  .more {{ font-size:12.5px; color:{INK2}; }}
</style>"""


def build(a, mention_rows, authors, goa_rows, run, max_papers=12, colors=None):
    """Return (html, height, shown) for the provenance graph of one assertion."""
    colors = colors or {}
    mentions = merge_mentions(mention_rows)
    groups = author_groups(mentions, authors)
    by_paper = defaultdict(list)
    for m in mentions:
        by_paper[m["paper"]].append(m)
    paper_meta = {m["paper"]: m for m in mentions}

    # choose papers: whole groups, largest first, until max_papers
    shown_groups, n = [], 0
    for g, papers, link, _ in groups:
        if n >= max_papers:
            break
        take = papers[:max_papers - n]
        shown_groups.append((g, take, link, len(papers)))
        n += len(take)
    hidden_papers = sum(len(p) for _, p, _, _ in groups) - n

    parts, edges = [], []
    y = TOP
    claim_pos = []                     # (y_center) of claims for the assert edges
    for gi, (g, papers, link, total) in enumerate(shown_groups, 1):
        rows_h = []
        for p in papers:
            k = len(by_paper[p])
            rows_h.append(k * CLAIM_H + (k - 1) * GAP)
        box_h = GROUP_HEAD + sum(rows_h) + GAP * (len(papers) - 1) + GROUP_PAD
        # group box + header
        if total > 1:
            linked = ", ".join(person_html(nm, ps) for nm, ps in link[:4]) + (f" +{len(link) - 4}" if len(link) > 4 else "")
            head = (f"<b>Author group {gi}</b> · {total} papers"
                    + (f" (showing {len(papers)})" if len(papers) < total else "")
                    + (f"<br>linked by {linked}" if link else ""))
        else:
            au = sorted(groups_lookup(groups, g), key=lambda a: int(a["position"]))
            lab = (person_html(au[0]["name"], au[0]["person"]) + (" … " + person_html(au[-1]["name"], au[-1]["person"])
                   + " (last)" if len(au) > 1 else "")) if au else "authors unknown"
            head = f"<b>Author group {gi}</b> · 1 paper<br>{lab}"
        parts.append(f"<rect x='{X_PAPER}' y='{y}' width='{W_PAPER}' height='{box_h}' rx='10' fill='#f0efec' "
                     f"stroke='{LINE}'/>")
        parts.append(fo(X_PAPER, y, W_PAPER, GROUP_HEAD, head, "ghead"))
        py = y + GROUP_HEAD
        for p, h in zip(papers, rows_h):
            pm = paper_meta[p]
            url = pmid_url(p)
            pid = esc(local(p))
            ref = f"<a href='{url}' target='_blank'>PMID {pid}</a>" if url else f"PMID {pid}"
            inner = (f"<div class='h'>{ref} · {esc(pm.get('year', '?'))} · cited {esc(pm.get('citations', '?'))}× · "
                     f"<i>{esc(pm.get('journal'))}</i></div><div class='t' title='{esc(pm.get('title'))}'>"
                     f"{esc(pm.get('title'))}</div>")
            parts.append(fo(X_PAPER + 10, py, W_PAPER - 20, h, inner, "card paper"))
            # claims of this paper
            cy = py
            for m in sorted(by_paper[p], key=lambda m: m.get("sentenceId", "")):
                src = local(m.get("sourceType"))
                hedged = local(m.get("certainty")) == "Hedged"
                cond = "; ".join(sorted(m["conditions"]))
                meta = " · ".join(x for x in [m.get("method"), m.get("organism"), m.get("cellType"),
                                              ("condition: " + cond) if cond else ""] if x and x != "not_stated")
                chips = (f"<span class='chip' style='background:{CERTAINTY.get(src, MUTED)}'>{esc(src.lower())}</span>"
                         + (f"<span class='chip' style='background:{CERTAINTY['Hedged']}'>hedged</span>" if hedged else ""))
                inner = (f"<div class='s' title='{esc(m.get('sentence'))}'>{chips}"
                         f"{snippet(m.get('sentence'), m['marks'])}</div><div class='meta'>{esc(m.get('sentenceId'))}"
                         f"{' · ' + esc(meta) if meta else ''}</div>")
                parts.append(fo(X_CLAIM, cy, W_CLAIM, CLAIM_H, inner, "card claim"))
                edges.append(edge(X_CLAIM, cy + CLAIM_H / 2, X_PAPER + W_PAPER - 10, py + h / 2))
                claim_pos.append(cy + CLAIM_H / 2)
                cy += CLAIM_H + GAP
            py += h + GAP
        y += box_h + GROUP_GAP
    content_bottom = y

    # assertion node
    verdict = local(a.get("verdict"))
    vcol = colors.get(verdict, INK2)
    mid = (TOP + content_bottom) / 2 if claim_pos else TOP + 80
    ah = 196
    ay = max(TOP, min(mid - ah / 2, content_bottom - ah))
    pol = local(a.get("polarity")).lower()
    inner = (f"<div class='big'>{esc(a.get('symbol'))} {'NOT ' if pol == 'absent' else ''}in {esc(a.get('label'))}</div>"
             f"<div><span class='chip' style='background:{vcol}'>{esc(verdict)}</span> vs GOA</div>"
             f"<div style='margin-top:6px'>{esc(a.get('nPapers'))} papers · <b>{esc(a.get('nGroups'))} independent "
             f"author groups</b></div><div style='color:{INK2}'>finding {esc(a.get('nFinding'))} · background "
             f"{esc(a.get('nBackground'))} · hedged {esc(a.get('nHedged'))}<br>{esc(a.get('yearFirst', '?'))}–"
             f"{esc(a.get('yearLast', '?'))}{' · context-dependent' if a.get('context') == 'true' else ''}</div>")
    parts.append(fo(X_ASSERT, ay, W_ASSERT, ah, inner, "assert"))
    for cy in claim_pos:
        edges.append(edge(X_CLAIM + W_CLAIM, cy, X_ASSERT, ay + ah / 2, color="#d9d8d3"))

    # GOA cards
    gg = {}
    for r in goa_rows:
        k = (r["link"], r["label"], r["negated"] == "true")
        e = gg.setdefault(k, {"ev": set(), "q": set(), "src": set(), "by": set()})
        e["ev"].add(r["evidence"])
        e["q"].add(r["qualifier"])
        if r.get("source"):
            e["src"].add(r["source"])
        if r.get("assignedBy"):
            e["by"].add(r["assignedBy"])
    order = {"same": 0, "narrower": 1, "broader": 2}
    cards = sorted(gg.items(), key=lambda kv: (order[kv[0][0]], -len(kv[1]["src"]), kv[0][1]))
    max_goa = 9
    gy0 = max(TOP, ay + ah / 2 - (min(len(cards), max_goa) * (GOA_H + GAP)) / 2)
    gy = gy0
    for (link, label, neg), e in cards[:max_goa]:
        srcs = sorted(e["src"])
        src_html = ""
        if srcs:
            first = srcs[0]
            u = pmid_url(first) if "pubmed" in first else None
            src_html = (f" · <a href='{u}' target='_blank'>PMID {esc(local(first))}</a>" if u else f" · {esc(local(first))}") \
                + (f" +{len(srcs) - 1}" if len(srcs) > 1 else "")
        inner = (f"<div class='h' title='{esc(LINK_TEXT[link])}'>{'<span class=not>NOT</span> ' if neg else ''}"
                 f"<b>{esc(label)}</b> · <span style='color:{INK2}'>{esc(LINK_SHORT[link])}</span></div><div class='meta'>"
                 f"{esc(', '.join(sorted(e['ev'])))}{src_html} · {esc(', '.join(sorted(e['by']))[:30])}</div>")
        parts.append(fo(X_GOA, gy, W_GOA, GOA_H, inner, "card goa"))
        edges.append(edge(X_ASSERT + W_ASSERT, ay + ah / 2, X_GOA, gy + GOA_H / 2,
                          color="#b3261e" if neg else INK2, dash=link != "same"))
        gy += GOA_H + GAP
    if len(cards) > max_goa:
        parts.append(fo(X_GOA, gy, W_GOA, 22, f"+{len(cards) - max_goa} more GOA rows", "more"))
        gy += 26
    if not cards:
        parts.append(fo(X_GOA, ay + ah / 2 - 20, W_GOA, 44,
                        "GOA has no annotation in this term's lineage for this protein.", "more"))

    # header: column titles, predicates, the run (prov:Activity) and its agent
    hdr = [fo(X_PAPER, 10, W_PAPER, 20, "Papers, boxed by independent author group", "colhead"),
           fo(X_CLAIM, 10, W_CLAIM, 20, "Claims (one per sentence)", "colhead"),
           fo(X_ASSERT, 10, W_ASSERT, 20, "Assertion", "colhead"),
           fo(X_GOA, 10, W_GOA, 20, "GOA (curated)", "colhead"),
           f"<text class='pred' x='{X_PAPER + W_PAPER + 4}' y='{TOP - 8}'>◀ prov:wasDerivedFrom</text>",
           f"<text class='pred' x='{X_CLAIM + W_CLAIM + 6}' y='{TOP - 8}'>locx:asserts ▶</text>",
           f"<text class='pred' x='{X_ASSERT + W_ASSERT + 6}' y='{TOP - 8}'>locx:goaSame / Narrower / Broader ▶</text>"]
    if run:
        rinner = (f"<b>prov:Activity</b> extraction run <code>{esc(local(run.get('run')))}</code> · started "
                  f"{esc((run.get('started') or '')[:16])}<br><b>prov:wasAssociatedWith</b> {esc(run.get('model'))} · "
                  f"prompt {esc(run.get('promptVersion'))}, temperature {esc(run.get('temperature'))}")
        hdr.append(fo(X_CLAIM, 36, W_CLAIM + 260, 48, rinner, "run"))
        hdr.append(f"<path d='M{X_CLAIM + 40},{TOP - 22} L{X_CLAIM + 40},{88}' stroke='{INK2}' stroke-dasharray='3 3' "
                   f"marker-end='url(#arrowup)' fill='none'/>")
        hdr.append(f"<text class='pred' x='{X_CLAIM + 48}' y='{TOP - 28}'>every claim prov:wasGeneratedBy this run</text>")

    height = max(content_bottom, gy, ay + ah) + 40
    if hidden_papers > 0:
        parts.append(fo(X_PAPER, content_bottom - 6, W_PAPER + 400, 24,
                        f"+ {hidden_papers} more supporting papers not shown (raise “papers shown”)", "more"))
    defs = (f"<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
            f"orient='auto'><path d='M0,0 L10,5 L0,10 z' fill='{MUTED}'/></marker>"
            f"<marker id='arrowup' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto'>"
            f"<path d='M0,0 L10,5 L0,10 z' fill='{INK2}'/></marker></defs>")
    svg = (f"<div class='wrap'><svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{height}' "
           f"viewBox='0 0 {W} {height}'>{defs}" + "".join(edges) + "".join(hdr) + "".join(parts) + "</svg></div>")
    return CSS + svg, height, {"papers_shown": n, "papers_hidden": hidden_papers, "groups": len(groups),
                               "groups_shown": len(shown_groups)}


def groups_lookup(groups, g):
    for gid, papers, _, by_paper in groups:
        if gid == g:
            return [a for p in papers for a in by_paper.get(p, [])]
    return []
