"""G-05 / M1.g1: the provenance of an alias that the position comparison of an APPROVED registration may rely on (owner decisions of 2026-11-08, migration 0011).

Status: SELF_TEST (Claude). Applied to no operational database. It writes only through ``record_*`` (called by ``register_alias`` inside its own savepoint, or by a sanctioned writer) and never repairs anything.

The 01 (募集人員) alias differs from the head's version only in extractor METADATA, never in a position key. ``position_differences`` names the differing keys; this module decides, per key and with evidence,
whether a difference may stop counting (the allow-list is these four keys and nothing else, and each has its own condition):

* ``pattern`` (only the alias has it): the stored provenance BUNDLE of that alias keeps exactly the alias record that is being registered, and the bundle verifies (SHA-256, required keys, same alias);
* ``quote_normalized`` (only the alias has it): its value equals the contract's normalisation (``identity._squash``, NFKC of the WHOLE string, whitespace removed) of the proof's ``quote`` - recomputed, never trusted;
  the extractor's per-character normalisation is a different function, so a value that differs is REFUSED, not held;
* ``section`` (only the head has it, as an explicit null): the bundle PROVES that the generating profile used no section constraint (``section_constraint == {"used": false, "proven_by": <the bundle's profile_sha256>}``);
  a missing value is not a null without that proof, and a non-null section must be equal on both sides;
* ``source_kind`` (only the head has it): equals the MEDIUM recorded for the source in ``source_representations`` (pdf / html). A source with no record is ``unknown`` and never matches; PDF and HTML are never the same.

Every other difference - a position key, an unpaired proof, a differing field proof, any other key - is refused, as before.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import identity

BUNDLE_KEYS = ("original_alias_record", "proof_order", "profile_sha256", "extractor_version", "normalizer_id")
ALIAS_ONLY_ALLOWED = frozenset({"pattern", "quote_normalized"})
HEAD_ONLY_ALLOWED = frozenset({"section", "source_kind"})
MEDIA = ("pdf", "html", "unknown")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def bundle_digest(bundle: Any) -> str:
    return hashlib.sha256(_canon(bundle).encode("utf-8")).hexdigest()


# ---- bundles ---------------------------------------------------------------------------------------------------------------------------------
def record_alias_provenance(db: sqlite3.Connection, alias_id: str, bundle: dict[str, Any], recorded_by: str) -> str:
    """Store the bundle of an EXISTING alias (append-only; a second bundle for the same alias is refused by the database). Returns its SHA-256."""
    problems = _bundle_shape(bundle, alias_id)
    if problems:
        raise ValueError("the provenance bundle is not storable: " + "; ".join(problems))
    digest = bundle_digest(bundle)
    db.create_function("sogh_write_ok", 0, lambda: 1)
    db.execute("INSERT INTO alias_provenance_bundles(alias_id, bundle_sha256, bundle_json, recorded_by, recorded_at) VALUES (?,?,?,?,?)",
               (alias_id, digest, _canon(bundle), recorded_by, datetime.now(timezone.utc).isoformat()))
    return digest


def _bundle_shape(bundle: Any, alias_id: str) -> list[str]:
    if not isinstance(bundle, dict):
        return ["the bundle is not an object"]
    problems = [f"missing key {k}" for k in BUNDLE_KEYS if k not in bundle]
    rec = bundle.get("original_alias_record")
    if not isinstance(rec, dict):
        problems.append("original_alias_record is not an object")
    else:
        if any(rec.get(k) not in (None, alias_id) for k in ("alias_id", "evidence_id")):
            problems.append("the bundle names another alias")
        if not isinstance(rec.get("proofs"), list) or not rec["proofs"]:
            problems.append("the original alias record keeps no proofs (the pattern lives there)")
    for k in ("profile_sha256", "extractor_version", "normalizer_id"):
        if k in bundle and (not isinstance(bundle[k], str) or not bundle[k].strip()):
            problems.append(f"{k} is empty")
    return problems


def verify_alias_provenance(db: sqlite3.Connection, alias_id: str) -> list[str]:
    """READ ONLY: what an audit says about the stored bundle of one alias; empty = consistent."""
    row = db.execute("SELECT bundle_sha256, bundle_json FROM alias_provenance_bundles WHERE alias_id=?", (alias_id,)).fetchone()
    if row is None:
        return ["no provenance bundle is stored for this alias"]
    try:
        data = json.loads(row[1])
    except ValueError:
        return ["the stored bundle is not JSON"]
    problems = _bundle_shape(data, alias_id)
    if bundle_digest(data) != row[0]:
        problems.append("bundle_sha256 does not match the stored bundle")
    return problems


def stored_bundle(db: sqlite3.Connection, alias_id: str) -> dict[str, Any] | None:
    row = db.execute("SELECT bundle_json FROM alias_provenance_bundles WHERE alias_id=?", (alias_id,)).fetchone()
    return None if row is None else json.loads(row[0])


# ---- the medium of a source --------------------------------------------------------------------------------------------------------------------
def record_source_representation(db: sqlite3.Connection, source_sha256: str, medium: str, basis: dict[str, Any], recorded_by: str) -> int:
    """A new version of the recorded medium (versions start at 1; a correction is a new version, the old one stays). ``basis`` must say where the medium comes from."""
    if medium not in MEDIA:
        raise ValueError(f"unknown medium {medium!r}")
    if not isinstance(basis, dict) or not basis:
        raise ValueError("the basis of a medium is required (a received record, a parsed check ...), never a hash or an extension alone")
    db.create_function("sogh_write_ok", 0, lambda: 1)
    version = (db.execute("SELECT max(rep_version) FROM source_representations WHERE source_sha256=?", (source_sha256,)).fetchone()[0] or 0) + 1
    db.execute("INSERT INTO source_representations(source_sha256, rep_version, medium, basis_json, recorded_by, recorded_at) VALUES (?,?,?,?,?,?)",
               (source_sha256, version, medium, _canon(basis), recorded_by, datetime.now(timezone.utc).isoformat()))
    return version


def medium_of(db: sqlite3.Connection, source_sha256: str) -> str:
    """The latest recorded medium; a source with no record is UNKNOWN (never guessed from an extension, a hash or a payload's own claim)."""
    row = db.execute("SELECT medium FROM source_representations WHERE source_sha256=? ORDER BY rep_version DESC LIMIT 1", (source_sha256,)).fetchone()
    return row[0] if row else "unknown"


# ---- the decision of the position comparison -------------------------------------------------------------------------------------------------
def explain_position_differences(db: sqlite3.Connection, diffs: list[dict[str, Any]], alias_id: str, alias_record: dict[str, Any], head_record: dict[str, Any],
                                 source_sha256: str) -> list[str]:
    """The reasons why the differences listed by ``position_differences`` may NOT stop counting; an empty list = every one is explained by the rules in the module docstring."""
    reasons: list[str] = []
    if not diffs:
        return reasons
    bundle_problems = verify_alias_provenance(db, alias_id)
    bundle = stored_bundle(db, alias_id) if not bundle_problems else None

    def proof(record, page, quote):
        for p in record.get("proofs") or []:
            if isinstance(p, dict) and p.get("page") == page and p.get("quote") == quote:
                return p
        return {}

    # the pairing key of position_differences is (page, quote); recover the quotes from the records
    keyed = {}
    for p in alias_record.get("proofs") or []:
        if isinstance(p, dict):
            keyed.setdefault(p.get("page"), []).append(p)
    for d in diffs:
        if "field_proofs" in d:
            reasons.append("the field proofs differ")
            continue
        if "unpaired" in d:
            reasons.append(f"a proof on page {d.get('page')} exists only on the {d['unpaired']} side")
            continue
        if d.get("value_differs"):
            reasons.append(f"page {d.get('page')}: the value of {', '.join(d['value_differs'])} differs (a position key or another value)")
            continue
        only_a, only_h = set(d.get("only_in_alias") or ()), set(d.get("only_in_head") or ())
        if only_a - ALIAS_ONLY_ALLOWED or only_h - HEAD_ONLY_ALLOWED:
            reasons.append(f"page {d.get('page')}: a key outside the allow-list differs: {sorted((only_a - ALIAS_ONLY_ALLOWED) | (only_h - HEAD_ONLY_ALLOWED))}")
            continue
        # which proofs of this page carry the differing keys
        for ap in keyed.get(d.get("page"), []):
            hp = proof(head_record, ap.get("page"), ap.get("quote"))
            if not hp or (set(ap) - set(hp)) != only_a or (set(hp) - set(ap)) != only_h:
                continue
            if "pattern" in only_a:
                if bundle is None:
                    reasons.append(f"page {d.get('page')}: `pattern` only the alias has, and its provenance bundle is {'; '.join(bundle_problems)}")
                elif _canon(bundle["original_alias_record"]) != _canon(alias_record):
                    reasons.append(f"page {d.get('page')}: `pattern`: the stored bundle does not keep exactly the alias record that is being registered")
            if "quote_normalized" in only_a and ap.get("quote_normalized") != identity._squash(str(ap.get("quote"))):
                reasons.append(f"page {d.get('page')}: `quote_normalized` is not the contract's normalisation of the quote (it is recomputed, not trusted)")
            if "section" in only_h:
                proven = bundle is not None and bundle.get("section_constraint") == {"used": False, "proven_by": bundle.get("profile_sha256")}
                if hp.get("section") is not None:
                    reasons.append(f"page {d.get('page')}: the head states a section; a non-null section must be equal on both sides")
                elif not proven:
                    reasons.append(f"page {d.get('page')}: a missing `section` is a null only if the bundle proves that no section constraint was used")
            if "source_kind" in only_h:
                medium = medium_of(db, source_sha256)
                if medium == "unknown" or hp.get("source_kind") != medium:
                    reasons.append(f"page {d.get('page')}: `source_kind` {hp.get('source_kind')!r} is not the recorded medium of the source ({medium})")
    return reasons
