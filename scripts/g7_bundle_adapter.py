"""Adapter: a table-cell bundle in the format of Work's PR #103 (read only) -> the input of the merged quarantine staging product code.

Claude-owned, SELF_TEST (author Claude; independent QA is Antigravity's).  It adds NO product behaviour: it only re-shapes a bundle and calls
`src.db_contract.quarantine_staging.evaluate_table_cell_format` (the 12-row refusal matrix) and `src.integration.table_cell_evidence_check.check_entry` (geometry).

The bundle (the `entry` of the contract / PR #103 prototype) holds, per row, three cells (label, pool, count) as {rect, text_sha256} and an integer value.  It holds NO cell text:
the text is supplied by the caller (`texts`, read from the document in memory, never committed) and is verified against the bundle's text_sha256 first.  A text that does not hash
to the bundle's hash is refused here (`ADAPTER_TEXT_HASH_MISMATCH`) - that is not a row of the product's matrix.

What the product's matrix compares are STRINGS and NUMBERS handed to it; which pinned value they are compared with is decided here (see PINS below) and is stated in the report.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db_contract import quarantine_staging as qs  # noqa: E402
from src.integration import table_cell_evidence_check as T  # noqa: E402

ROLES = ("label", "pool", "count")
HEADERS = ["入試区分", "募集枠", "人数"]


def norm(text: str) -> str:
    """The normalisation of PR #103 (NFKC, all whitespace removed); the bundle's text_sha256 is the SHA-256 of this."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def text_sha(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


@dataclass
class Pins:
    """What the reviewed profile fixes OUTSIDE the bundle (the adapter never reads these from the bundle it is checking)."""

    page: int
    title_sha256: str
    guide_page: Optional[int] = None  # the page of the secondary (guide) span that the profile pins
    bundle_sha256: Dict[str, str] = field(default_factory=dict)  # row_id -> pinned product bundle SHA (optional)
    cell_sha256: Dict[tuple, str] = field(default_factory=dict)  # (row_id, role) -> text SHA the reviewed profile pins for that cell (optional)


@dataclass
class Claim:
    """What a submitter claims beyond the bundle's own cells."""

    guide_page_claimed: Optional[int] = None
    source_pool_text: Dict[str, str] = field(default_factory=dict)  # row_id -> pool text re-read from the source at the pool rectangle (row 7)
    extra_context: str = ""  # text found in the title scope next to the title (a footnote, another heading, ...)
    scope_extra: Dict[str, Any] = field(default_factory=dict)  # extra granularity dimensions (row 10)


def verify_texts(entry: dict, texts: Dict[tuple, str]) -> List[str]:
    """Every (row_id, role) text must hash to the bundle's text_sha256."""
    bad = []
    for row in entry["rows"]:
        for role in ROLES:
            t = texts.get((row["row_id"], role))
            if t is None or text_sha(t) != row[role]["text_sha256"]:
                bad.append(f"{row['row_id']}/{role}")
    return bad


def table_data_for_row(entry: dict, texts: Dict[tuple, str], pins: Pins, claim: Claim, row_id: str, *, title_text: str) -> Dict[str, Any]:
    """The product input for ONE target cell (the count of `row_id`)."""
    rows_view = [[texts[(r["row_id"], "label")], texts[(r["row_id"], "pool")], texts[(r["row_id"], "count")]] for r in entry["rows"]]
    target = next(r for r in entry["rows"] if r["row_id"] == row_id)
    title_years = sorted(T._years(title_text))
    td: Dict[str, Any] = {
        "headers": list(HEADERS),
        "rows": rows_view,
        "context_text": f"{title_text} {claim.extra_context}".strip(),
        "target_key": entry["fact_key"],
        "raw_cell_value": texts[(row_id, "count")],
        "row_label": texts[(row_id, "label")],
        "column": HEADERS[2],
        "page": entry["page"],
        "expected_page": pins.page,
        "table_title": title_text,
        # the product compares two strings: the pinned side is the claimed title when its SHA is the pinned one, else a marker that can equal nothing
        "expected_table_title": title_text if text_sha(title_text) == pins.title_sha256 else "<<title does not hash to the pinned title_sha256>>",
        "structured_pool": texts[(row_id, "pool")],
        "source_pool": claim.source_pool_text.get(row_id, texts[(row_id, "pool")]),
        "scope_granularity": {
            "category": entry["values"].get("category"),
            "selection": entry["values"].get("selection"),
            "pool": texts[(row_id, "pool")],
            "admission_year": entry["values"].get("admission_year"),
            "unit": entry["values"].get("unit"),
            **claim.scope_extra,
        },
    }
    if len(title_years) == 1:  # a title without any year string is NOT refused by the product's row 5 (only check_entry's E-YEAR catches it)
        td["column_year"] = title_years[0]
        td["expected_year"] = entry["values"].get("admission_year")
    if claim.guide_page_claimed is not None and pins.guide_page is not None:
        # The product compares two bare page numbers: here the page the secondary span CLAIMS vs the page the profile PINS (the two sources are different documents).
        td["primary_page"] = claim.guide_page_claimed
        td["secondary_page"] = pins.guide_page
    if row_id in pins.bundle_sha256:
        td["expected_bundle_sha256"] = pins.bundle_sha256[row_id]
    del target
    return td


def evaluate_bundle(entry: dict, texts: Dict[tuple, str], pins: Pins, claim: Optional[Claim] = None, *, geometry: Optional[dict] = None, approved: frozenset = frozenset()) -> Dict[str, Any]:
    """Run the layers in order.  Returns {adapter, geometry, rows:{row_id: RefusalResult}, decision}."""
    claim = claim or Claim()
    out: Dict[str, Any] = {"adapter": [], "geometry": [], "rows": {}}
    bad = verify_texts(entry, texts)
    if bad:
        out["adapter"].append(("ADAPTER_TEXT_HASH_MISMATCH", bad))
        out["decision"] = "REFUSE"
        return out
    pinned_bad = [f"{k[0]}/{k[1]}" for k, v in pins.cell_sha256.items() if text_sha(texts[k]) != v]
    if pinned_bad:
        out["adapter"].append(("ADAPTER_PINNED_CELL_MISMATCH", pinned_bad))
        out["decision"] = "REFUSE"
        return out
    title_text = entry["year_anchor"]["text"]
    if geometry is not None:
        out["geometry"] = T.check_entry(entry, approved_fact_keys=approved, **geometry)
    for r in entry["rows"]:
        out["rows"][r["row_id"]] = qs.evaluate_table_cell_format(table_data_for_row(entry, texts, pins, claim, r["row_id"], title_text=title_text))
    errors = [f for f in out["geometry"] if f["level"] == "error"]
    refused = [k for k, v in out["rows"].items() if v.decision != "ACCEPT"]
    out["decision"] = "ACCEPT" if not errors and not refused else "REFUSE"
    return out


def candidate_payload(entry: dict, texts: Dict[tuple, str], row_id: str, accepted: "qs.RefusalResult") -> Dict[str, str]:
    """The (extracted_key, extracted_value) a quarantine row stores for one accepted cell.  Candidate only; texts are NOT stored, only hashes and positions."""
    row = next(r for r in entry["rows"] if r["row_id"] == row_id)
    value = {
        "bundle_sha256": accepted.quarantine_payload["bundle_sha256"],
        "value": row["value"],
        "unit": entry["values"]["unit"],
        "page": entry["page"],
        "source_sha256": entry["source_sha256"],
        "profile_sha256": entry["profile_sha256"],
        "extractor_id": entry["extractor_id"],
        "row_id": row_id,
        "cells": {role: {"rect": row[role]["rect"], "text_sha256": row[role]["text_sha256"]} for role in ROLES},
    }
    return {"extracted_key": entry["fact_key"], "extracted_value": json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}
