"""How the demo shows GOA evidence: one grey ramp from strong (dark) to weak (light) per GO evidence category, always
with the category name written next to it, plus tooltips with ECO's labels. The categories come from the locx
ontology (locx/evidence.py); each GOA row's category is computed in SPARQL from its ECO term."""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx import evidence as E  # noqa: E402

# ordinal grey ramp (strongest = darkest); the lightest step still clears 2:1 on the light surface
# one grey step per category, strongest = darkest; as many steps as the ontology has categories
_RAMP = ["#2b2a27", "#46453f", "#5f5e58", "#77766f", "#8f8e87", "#a5a49d", "#b8b7b0", "#c8c7c0"]
EV_COLOR = dict(zip([k for k, _, _ in E.GROUPS], _RAMP))
if len(EV_COLOR) < len(E.GROUPS):
    raise SystemExit("[evidence_ui] more GO evidence categories in the ontology than grey steps; extend _RAMP")
EV_TEXT = {k: ("#fcfcfb" if i < 4 else "#0b0b0b") for i, k in enumerate(EV_COLOR)}
LABEL = E.GROUP_LABEL
SHORT = {"experimental": "exp.", "high_throughput": "HTP", "author_statement": "author", "curator": "curator",
         "phylogenetic": "phylo.", "computational": "comp.", "electronic": "IEA"}   # inside the cell drawing, where space is short
HELP = E.GROUP_HELP
GROUPS = [k for k, _, _ in E.GROUPS]


def code_title(evidence) -> str:
    """Tooltip: the ECO labels (evidence = (ECO label, category) pairs or plain labels)."""
    return "; ".join(sorted({e[0] if isinstance(e, tuple) else e for e in evidence}))


def badge(group, evidence=(), small=False) -> str:
    """Grey pill with the category name; the tooltip gives the definition and the ECO labels."""
    if not group or group not in EV_COLOR:
        return ""
    tip = f"{LABEL[group]}: {HELP[group]}" + (f" · {code_title(evidence)}" if evidence else "")
    return (f"<span title='{html.escape(tip)}' style='background:{EV_COLOR[group]};color:{EV_TEXT[group]};"
            f"padding:{'0 6px' if small else '1px 8px'};border-radius:10px;font-size:{'0.75em' if small else '0.85em'};"
            f"white-space:nowrap'>{html.escape(LABEL[group])}</span>")


def groups_of(evidence):
    """{category: sorted ECO labels}, strongest category first. evidence = (ECO label, category key) pairs, as the
    GOA queries return them (the category is computed from ECO's hierarchy and the locx ontology)."""
    out = {}
    for label, group in evidence:
        out.setdefault(group or "", set()).add(label)
    return {g: sorted(out[g]) for g in sorted(out, key=lambda g: E.RANK.get(g, 99))}


def legend_rows():
    """Rows for a 'what do the categories mean' table (GO guide categories, locx ontology)."""
    return [{"category": LABEL[k], "rank": E.RANK[k], "means": HELP[k]} for k in GROUPS]


def legend_html() -> str:
    return "<div style='display:flex;flex-wrap:wrap;gap:6px 14px;font-size:0.85em;color:#52514e'>" + "".join(
        f"<span>{badge(g, small=True)} {html.escape(HELP[g])}</span>" for g in GROUPS) + "</div>"
