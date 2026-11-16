"""Sentence splitting with character offsets into the canonical text. S1 = title."""
import pysbd

_seg = pysbd.Segmenter(language="en", clean=False)


def split(title: str, text: str) -> list[dict]:
    """[{id, start, end, text}]; offsets index into `text` (title at 0, abstract after it)."""
    sents = []
    if title.strip():
        sents.append({"id": "S1", "start": 0, "end": len(title), "text": title})
    cursor = len(title)
    for s in _seg.segment(text[cursor:]):
        s = s.strip()
        if not s:
            continue
        start = text.find(s, cursor)
        if start < 0:          # pysbd changed the string; fall back to the cursor position
            start = cursor
        end = start + len(s)
        sents.append({"id": f"S{len(sents) + 1}", "start": start, "end": end, "text": text[start:end]})
        cursor = end
    return sents


def sentence_of(sents: list[dict], start: int) -> str | None:
    for s in sents:
        if s["start"] <= start < s["end"]:
            return s["id"]
    return None
