"""How the demo shows GO evidence codes: one grey ramp from strong (dark) to weak (light), always with the group
name written next to it, plus tooltips with the full code names. The table itself lives in locx/evidence.py."""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locx import evidence as E  # noqa: E402

# ordinal grey ramp (strongest = darkest); the lightest step still clears 2:1 on the light surface
EV_COLOR = dict(zip([k for k, _, _ in E.GROUPS], ["#2b2a27", "#4a4945", "#66655f", "#807f79", "#9a9993", "#b0afa8"]))
EV_TEXT = {k: ("#fcfcfb" if i < 4 else "#0b0b0b") for i, k in enumerate(EV_COLOR)}
LABEL = E.GROUP_LABEL
SHORT = {"experimental": "exp.", "high_throughput": "HTP", "author_statement": "author", "curator": "curator",
         "computational": "comp.", "electronic": "IEA"}   # inside the cell drawing, where space is short
HELP = E.GROUP_HELP
GROUPS = [k for k, _, _ in E.GROUPS]


def code_title(codes) -> str:
    return "; ".join(f"{c}: {E.CODES[c][1]}" for c in sorted(codes) if c in E.CODES)


def badge(group, codes=(), small=False) -> str:
    """Grey pill with the group name (and the codes); the tooltip spells the codes out."""
    if not group or group not in EV_COLOR:
        return ""
    tip = f"{LABEL[group]}: {HELP[group]}" + (f" · {code_title(codes)}" if codes else "")
    txt = LABEL[group] + (f" · {', '.join(sorted(codes))}" if codes else "")
    return (f"<span title='{html.escape(tip)}' style='background:{EV_COLOR[group]};color:{EV_TEXT[group]};"
            f"padding:{'0 6px' if small else '1px 8px'};border-radius:10px;font-size:{'0.75em' if small else '0.85em'};"
            f"white-space:nowrap'>{html.escape(txt)}</span>")


def groups_of(codes):
    """{group: sorted codes}, strongest group first."""
    out = {}
    for c in codes:
        out.setdefault(E.group(c), set()).add(c)
    return {g: sorted(out[g]) for g in sorted(out, key=lambda g: E.RANK.get(g, 99))}


def legend_rows():
    """Rows for a 'what do the codes mean' table."""
    return [{"group": LABEL[E.CODES[c][0]], "code": c, "name": E.CODES[c][1], "means": HELP[E.CODES[c][0]]}
            for c in sorted(E.CODES, key=lambda c: (E.RANK[E.CODES[c][0]], c))]


def legend_html() -> str:
    return "<div style='display:flex;flex-wrap:wrap;gap:6px 14px;font-size:0.85em;color:#52514e'>" + "".join(
        f"<span>{badge(g, small=True)} {html.escape(HELP[g])}</span>" for g in GROUPS) + "</div>"
