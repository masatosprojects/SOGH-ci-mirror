"""Identity of a FACT, independent of the evidence id it happens to carry (Issue #55, gap G-05).

An evidence id in the delivered pipeline is `EV-<profile code>-<ordinal>-<source sha6>` (extract.py): it depends on the profile's code
string and on the order the facts were extracted in. Re-running an extraction with another profile code gives the SAME fact a NEW id.
This module compares facts by what they say and where they come from:

    fingerprint = (case, source sha256, fact_key, normalised value, locator)      locator = the normalised (page, quote) pairs of its proofs

Classification of two or more ids that share (case, source, fact_key):
  duplicate            same value AND same locator            -> one fact under two ids: alias them
  same_value_moved     same value, DIFFERENT locator          -> the same fact whose proof position was corrected: alias, keep the better position
  independent          different value AND different locator  -> two real facts of one key in one source: both must be storable
  conflict             different value, SAME locator          -> two statements about the same place: a real inconsistency
Nothing here renames or deletes an id: it only reports, and proposes an alias table (an id is never overwritten).
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import unicodedata
from typing import Any

KINDS = ("duplicate", "same_value_moved", "independent", "conflict")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def locator(record: dict[str, Any]) -> tuple[tuple[Any, str], ...]:
    """Where in the source the fact is said: the sorted, de-duplicated (page, normalised quote) pairs of its proofs."""
    pairs = {(p.get("page"), _squash(p["quote"])) for p in record.get("proofs") or [] if isinstance(p, dict) and p.get("quote")}
    return tuple(sorted(pairs, key=lambda t: (str(t[0]), t[1])))


def locator_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(locator(record)).encode()).hexdigest()[:16]


def source_of(record: dict[str, Any]) -> Any:
    return record.get("source_sha256") or record.get("source_pdf_sha256")


def group_key(record: dict[str, Any], case_id: str) -> tuple[str, Any, str]:
    return (case_id, source_of(record), record.get("fact_key") or record.get("key") or "")


def classify(a: dict[str, Any], b: dict[str, Any]) -> str:
    same_value = _canon(a.get("value")) == _canon(b.get("value"))
    same_locator = locator(a) == locator(b)
    if same_value and same_locator:
        return "duplicate"
    if same_value:
        return "same_value_moved"
    return "conflict" if same_locator else "independent"


def find_groups(evidence: dict[str, dict[str, Any]], case_of) -> list[dict[str, Any]]:
    """Every (case, source, fact_key) that holds more than one evidence id (revisions, which carry a logical_id, are a different thing and are left out)."""
    groups: dict[tuple, list[str]] = collections.defaultdict(list)
    for eid, rec in evidence.items():
        if rec.get("logical_id"):
            continue
        groups[group_key(rec, case_of(rec))].append(eid)
    out = []
    for key, ids in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(ids) < 2:
            continue
        pair_kinds = {classify(evidence[i], evidence[j]) for n, i in enumerate(ids) for j in ids[n + 1:]}
        out.append({"case": key[0], "source": key[1], "fact_key": key[2], "ids": sorted(ids), "kinds": sorted(pair_kinds)})
    return out


def propose_aliases(groups: list[dict[str, Any]], prefer: list[str] | None = None) -> dict[str, str]:
    """alias id -> canonical id, only for groups whose members are all duplicates / moved proofs. `prefer`: ids to keep (e.g. the ones the native
    database and its articles already use); otherwise the lexicographically first. Independent facts and conflicts get NO alias."""
    aliases: dict[str, str] = {}
    for g in groups:
        if set(g["kinds"]) - {"duplicate", "same_value_moved"}:
            continue
        keep = next((i for p in (prefer or []) for i in g["ids"] if i == p), g["ids"][0])
        aliases.update({i: keep for i in g["ids"] if i != keep})
    return aliases
