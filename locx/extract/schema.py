"""Per-abstract JSON schema: enums hold only this abstract's sentence and candidate IDs,
so constrained decoding cannot produce an unknown ID. Property order = generation order
(sentence first: the model commits to evidence before choosing the claim)."""

SCHEMA_VERSION = "1"  # bump whenever enums or fields change

ORGANISMS = ["human", "mouse", "rat", "other", "not_stated"]
METHODS = ["immunofluorescence", "fluorescent_protein_imaging", "fractionation_western_blot",
           "immunohistochemistry", "electron_microscopy", "proximity_labeling_or_proteomics",
           "other", "not_stated"]


def build(rec: dict, max_items: int = 30) -> dict:
    claim = {
        "type": "object",
        "properties": {
            "sentence": {"enum": [s["id"] for s in rec["sentences"]]},
            "protein": {"enum": [p["cid"] for p in rec["proteins"]]},
            "location": {"enum": [l["cid"] for l in rec["locations"]] + ["OTHER"]},
            "other_location_text": {"type": ["string", "null"]},
            "polarity": {"enum": ["present", "absent"]},
            "certainty": {"enum": ["stated", "hedged"]},
            "source_type": {"enum": ["finding", "background"]},
            "condition": {"type": ["string", "null"]},
            "cell_type": {"type": ["string", "null"]},
            "organism": {"enum": ORGANISMS},
            "method": {"enum": METHODS},
        },
        "additionalProperties": False,
    }
    claim["required"] = list(claim["properties"])
    return {
        "type": "object",
        "properties": {"claims": {"type": "array", "maxItems": max_items, "items": claim}},
        "required": ["claims"],
        "additionalProperties": False,
    }
