"""Prompt for one abstract (SPEC §5.1, §5.2). The model sees gene symbols, GO labels and mention
strings only; never UniProt accessions or GO IDs."""
import hashlib

PROMPT_VERSION = "v3"  # v3 = v2 + alternative readings of ambiguous protein names (only in affected user messages)  # bump whenever SYSTEM or the user-message layout changes

SYSTEM = """You extract subcellular localization claims about proteins from a PubMed title and abstract.

You get numbered sentences, candidate proteins (P1, P2, ...) and candidate cellular
locations (L1, L2, ...). Candidates were found automatically and can be wrong (for example
"nuclear" in "nuclear factor"); ignore candidates that are not used as a protein or a location.

A claim says that a protein IS (present) or IS NOT (absent) in a cellular location.

Rules:
1. Extract only what the text states. Do not add outside knowledge.
2. Subcellular locations only: organelles, compartments, membranes, cellular structures,
   extracellular/secreted. Skip tissue- or organ-level expression ("expressed in liver").
3. Translocation ("moves from A to B upon S") gives two claims: A with the condition before or
   without S, and B with condition S.
4. polarity = "absent" only for explicit negative statements that the protein is not there:
   "not detected in", "absent from", "excluded from", "does not localize to".
   A change in amount is NOT absence. "reduced/decreased/impaired/inhibited/prevented/blocked
   nuclear translocation (or accumulation)", "retained in the cytoplasm", "loss of nuclear
   localization" all give polarity = "present"; put the change and its cause in condition
   (e.g. "reduced by JAK2 depletion"). For "retained in A instead of moving to B", give A
   present and B present with the condition that reduces it.
5. certainty = "hedged" for "may", "might", "could", "suggest", "putative", "possibly";
   otherwise "stated".
6. source_type = "background" when the sentence states prior knowledge ("is known to",
   "has been reported", "previous studies"); "finding" when it reports this study's results.
7. If the location is not among the candidates, set location = "OTHER" and copy the location
   phrase into other_location_text. Otherwise other_location_text = null. OTHER must still be a
   subcellular structure (e.g. "nucleoli", "nuclear speckles", "cell cortex"). Never use a cell
   type, tissue, organ, body fluid, culture medium, process ("endocytosis", "release") or
   another protein as a location; then there is no claim.
8. sentence = the ID of the single sentence that best supports the claim. Prefer a sentence that
   names the protein (not only "it" or "the protein") and the location.
9. condition, cell_type: short phrases taken from the text, or null.
   organism and method may come from any sentence of the abstract (often a methods sentence).
   organism: organism of the cells or tissue studied: "human" for human cells, tissue or a
   well-known human cell line (HeLa, HEK293, U2OS...); "mouse"/"rat" for those animals or their
   cells; "other" for any other species (yeast, fly, fish, plants, shrimp...); "not_stated" only
   if the abstract gives no hint. method: the technique that showed the location
   (immunofluorescence or immunostaining with microscopy -> immunofluorescence; GFP/RFP-tagged
   protein imaging -> fluorescent_protein_imaging; nuclear/cytoplasmic or other fractionation
   with western blot -> fractionation_western_blot), or "not_stated".
10. One claim per (protein, location, polarity, condition). If there are no claims, return {"claims": []}.

Example
Sentences:
[S1] Nutrient signalling controls ProtA.
[S2] ProtB has been reported to localize to lysosomes.
[S3] Using immunofluorescence in HeLa cells, we show that ProtA accumulates in the nucleus upon starvation, whereas it remains cytoplasmic in fed cells.
[S4] ProtA was not detected in mitochondria, but it may associate with the Golgi.
[S5] Knockdown of ProtC prevented the nuclear accumulation of ProtA in starved cells.
Candidate proteins: P1 = PROTA ("ProtA"); P2 = PROTB ("ProtB"); P3 = PROTC ("ProtC")
Candidate locations: L1 = lysosome ("lysosomes"); L2 = nucleus ("nucleus"); L3 = cytoplasm ("cytoplasmic"); L4 = mitochondrion ("mitochondria")
Output:
{"claims": [
 {"sentence":"S2","protein":"P2","location":"L1","other_location_text":null,"polarity":"present","certainty":"stated","source_type":"background","condition":null,"cell_type":null,"organism":"not_stated","method":"not_stated"},
 {"sentence":"S3","protein":"P1","location":"L2","other_location_text":null,"polarity":"present","certainty":"stated","source_type":"finding","condition":"starvation","cell_type":"HeLa","organism":"human","method":"immunofluorescence"},
 {"sentence":"S3","protein":"P1","location":"L3","other_location_text":null,"polarity":"present","certainty":"stated","source_type":"finding","condition":"fed cells","cell_type":"HeLa","organism":"human","method":"immunofluorescence"},
 {"sentence":"S4","protein":"P1","location":"L4","other_location_text":null,"polarity":"absent","certainty":"stated","source_type":"finding","condition":null,"cell_type":"HeLa","organism":"human","method":"not_stated"},
 {"sentence":"S4","protein":"P1","location":"OTHER","other_location_text":"Golgi","polarity":"present","certainty":"hedged","source_type":"finding","condition":null,"cell_type":"HeLa","organism":"human","method":"not_stated"},
 {"sentence":"S5","protein":"P1","location":"L2","other_location_text":null,"polarity":"present","certainty":"stated","source_type":"finding","condition":"starvation; reduced by ProtC knockdown","cell_type":"HeLa","organism":"human","method":"immunofluorescence"}
]}"""


def _mentions(cand: dict) -> str:
    seen = []
    for m in cand["mentions"]:
        if m["text"] not in seen:
            seen.append(m["text"])
    return ", ".join(f'"{t}"' for t in seen)


ALT_NOTE = ("Some names can mean different proteins; their readings are marked below. Choose the protein the text "
            "means from the context; if the context does not decide, use the tagger's reading. Never make claims for "
            "two readings of the same name.")


def _protein_line(p: dict) -> str:
    line = f"{p['cid']} = {p['symbol'] or p['uniprot']}"
    if p.get("alt"):
        line += f" ({p.get('name', '')})" if p.get("name") else ""
    line += f" — mentioned as: {_mentions(p)}"
    if p.get("alt"):
        line += " " + " ".join(f"[{'tagger' if role == 'tagger' else 'alternative'} reading of \"{t}\"]"
                               for t, role in p["alt"].items())
    return line


def user_message(rec: dict) -> str:
    lines = ["Sentences:"]
    lines += [f"[{s['id']}] {s['text']}" for s in rec["sentences"]]
    lines += ["", "Candidate proteins (found by a tagger; some may be irrelevant):"]
    if any(p.get("alt") for p in rec["proteins"]):
        lines.append(ALT_NOTE)
    lines += [_protein_line(p) for p in rec["proteins"]]
    lines += ["", "Candidate locations (found by a dictionary; some may be false matches):"]
    lines += [f"{l['cid']} = {l['label']} — mentioned as: {_mentions(l)}" for l in rec["locations"]]
    return "\n".join(lines)


def messages(rec: dict) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_message(rec)}]


def prompt_sha256() -> str:
    """Hash of the system prompt plus a fixed dummy user message (catches layout changes too)."""
    dummy = {"sentences": [{"id": "S1", "text": "x"}],
             "proteins": [{"cid": "P1", "symbol": "X", "uniprot": "X", "mentions": [{"text": "x"}]},
                          {"cid": "P2", "symbol": "Y", "uniprot": "Y", "name": "y", "alt": {"x": "alternative"},
                           "mentions": [{"text": "x"}]}],
             "locations": [{"cid": "L1", "label": "x", "mentions": [{"text": "x"}]}]}
    return hashlib.sha256((SYSTEM + "\n\x00\n" + user_message(dummy)).encode()).hexdigest()
