"""SELF_TEST (Claude) for migration 0011-g05-alias-provenance and src/db_contract/alias_provenance.py (owner decision 2026-11-08: storage of the 01 alias's extractor provenance and of a source's medium, and the
four per-key rules of the approved registration). SYNTHETIC databases only; applied to no operational database. Not an acceptance of the 01 registration: that needs the real stored records and the PDF
(not opened by anyone yet) and the owner's acceptance. It supersedes the prototype test of PR #278 (the two tables are real now).

Proven: the frozen file is pinned and creates two EMPTY append-only tables; the 01 situation (an alias that differs from the approved head only in `pattern`, `quote_normalized`, `section`, `source_kind`) is registered
ONLY when each of the four keys is explained by evidence, atomically with its bundle; every other way is refused with nothing written; a position key can never be explained away."""
import copy
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.db_contract import additive_schema as ad
from src.db_contract import alias_provenance as prov
from src.db_contract import identity
from tests import db_support as dbs
from tests import test_additive_schema as T
from tests.test_g05_owner_review import add_revision, dump, fact_and_record, sha, world  # noqa: F401  (world is a fixture)

SQL = Path(ad.MIGRATION_DIR) / "0011_g05_alias_provenance.sql"
PIN = "1cf76e79974ac05855bb4f0491e24612f478b4320aa5c9a09f96d5327e630904"
ID = "0011-g05-alias-provenance"
QUOTE = "知識情報・図書館学類　 1６ 名"  # a quote with a full-width space and full-width digit: the contract's normalisation (whole-string NFKC, no spaces) is not a no-op
PATTERN = r"知識情報・図書館学類10040(?P<count>16)―小計"
PROFILE = "p" * 64


def head_proofs(**over):
    return [{"page": 6, "quote": QUOTE, "normalized_start": 10, "normalized_end": 20, "section": None, "source_kind": "pdf", **over}]


def alias_proofs(**over):
    return [{"page": 6, "quote": QUOTE, "normalized_start": 10, "normalized_end": 20, "pattern": PATTERN, "quote_normalized": identity._squash(QUOTE), **over}]


def bundle_for(record, **over):
    b = {"original_alias_record": record, "proof_order": [0], "profile_sha256": PROFILE, "extractor_version": "2026-11-01-v1.1", "normalizer_id": "nfkc-per-character",
         "section_constraint": {"used": False, "proven_by": PROFILE}}
    b.update(over)
    return b


@pytest.fixture
def scene(world):
    """The 01 situation: the head (EV-U-head) carries the corrected, pinned position; the legacy record differs from it only in extractor metadata. The medium of the source is recorded as pdf."""
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", head_proofs())
    legacy = copy.deepcopy(base)
    legacy["proofs"] = alias_proofs()
    legacy["evidence_id"] = "EV-LEGACY-01"  # the legacy delivery names itself
    source = T.facts(path)[0]["source_sha256"]
    with closing(dbs.app_connect(path)) as c:
        prov.record_source_representation(c, source, "pdf", {"received": "synthetic record", "validator": "v1"}, "claude")
        c.commit()
    return path, root, legacy, source


def reg(path, root, legacy, bundle="auto", by="claude", alias="EV-LEGACY-01"):
    with closing(dbs.app_connect(path)) as c:
        ad.register_alias(c, alias, root, "locator_corrected_copy", "synthetic 01", alias_record=legacy, pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head",
                          provenance_bundle=bundle_for(legacy) if bundle == "auto" else bundle, recorded_by=by)
        c.commit()


def tables(path):
    return dump(path)


# ------------------------------------------------------------------ the frozen file and the empty tables
def test_the_frozen_file_is_pinned_creates_two_empty_append_only_tables_and_is_in_the_chain(tmp_path):
    assert hashlib.sha256(SQL.read_bytes()).hexdigest() == PIN and b"\r" not in SQL.read_bytes()
    entry = next(m for m in ad.MIGRATIONS if m[0] == ID)
    assert entry[4] == SQL.read_bytes().decode("utf-8") and ad._seq(ID) == 11
    statements = [s for s, _ in ad.parse_frozen(entry[4])]
    assert sum(s.startswith("CREATE TABLE") for s in statements) == 2 and sum(s.startswith("CREATE TRIGGER") for s in statements) == 8
    assert not any(w in s.upper() for s in statements for w in ("INSERT INTO", " DROP ", "ALTER TABLE", "DELETE FROM"))
    path = T.build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    with closing(sqlite3.connect(path)) as c:
        assert [c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ad.ALIAS_PROVENANCE_TABLES] == [0, 0]
        assert ad.verify_history(c) == [] and ad.verify_schema_state(c) == [] and ad.verify_history_provenance(c) == []


@pytest.mark.parametrize("statement", ["CREATE TABLE alias_provenance_bundles(x)", "CREATE TABLE source_representations(x)",
                                       "CREATE TRIGGER trg_source_representations_no_update BEFORE UPDATE ON facts BEGIN SELECT 1; END"])
def test_an_existing_object_of_those_names_stops_the_migration_and_nothing_is_changed(tmp_path, statement):
    path = T.build(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS if ad._seq(m[0]) < 11))
    with closing(sqlite3.connect(path)) as c:
        c.execute(statement)
        c.commit()
    before = sha(path)
    try:
        r = ad.apply(path, confirm_disposable_copy=True)
        assert ID not in r["applied"]
    except ad.MigrationError:
        pass
    assert sha(path) == before


# ------------------------------------------------------------------ the 01 situation: registered only when every key is explained
def test_the_01_alias_is_registered_with_its_bundle_when_all_four_keys_are_explained(scene):
    path, root, legacy, _ = scene
    reg(path, root, legacy)
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("SELECT alias_id, pinned_evidence_id FROM evidence_aliases").fetchall() == [("EV-LEGACY-01", "EV-U-head")]
        assert prov.verify_alias_provenance(c, "EV-LEGACY-01") == []
        assert prov.stored_bundle(c, "EV-LEGACY-01")["original_alias_record"] == legacy
        r = ad.resolve(c, "EV-LEGACY-01")
        assert r["resolved_evidence_id"] == "EV-U-head" and r["cited_version_fixed"] is True


@pytest.mark.parametrize("what", ["no_bundle", "bundle_for_another_record", "no_section_proof", "section_proof_by_another_profile", "no_medium", "wrong_medium", "bad_quote_normalized",
                                  "unknown_key_only_in_alias", "missing_bundle_key", "no_recorded_by"])
def test_each_unexplained_difference_is_refused_and_nothing_at_all_is_written(scene, what):
    path, root, legacy, source = scene
    before = tables(path)
    bundle = bundle_for(legacy)
    by = "claude"
    if what == "no_bundle":
        bundle = None
    if what == "bundle_for_another_record":
        other = copy.deepcopy(legacy)
        other["proofs"][0]["pattern"] = "another(?P<count>1)"
        bundle = bundle_for(other)
    if what == "no_section_proof":
        bundle = bundle_for(legacy, section_constraint={"used": True, "proven_by": PROFILE})
    if what == "section_proof_by_another_profile":
        bundle = bundle_for(legacy, section_constraint={"used": False, "proven_by": "q" * 64})
    if what == "no_medium":
        with closing(dbs.app_connect(path)) as c:  # a database where nobody recorded the medium
            c.executescript("DROP TRIGGER trg_source_representations_no_delete; DELETE FROM source_representations;")
            c.commit()
        before = tables(path)
    if what == "wrong_medium":
        with closing(dbs.app_connect(path)) as c:
            prov.record_source_representation(c, source, "html", {"received": "a correction"}, "claude")  # the LATEST record says html, the head says pdf
            c.commit()
        before = tables(path)
    if what == "bad_quote_normalized":
        legacy["proofs"][0]["quote_normalized"] = "".join(ch for ch in QUOTE if not ch.isspace())  # per-character without NFKC: not the contract's value
        bundle = bundle_for(legacy)
    if what == "unknown_key_only_in_alias":
        legacy["proofs"][0]["extractor_confidence"] = 0.99
        bundle = bundle_for(legacy)
    if what == "missing_bundle_key":
        bundle = bundle_for(legacy)
        del bundle["profile_sha256"]
    if what == "no_recorded_by":
        by = ""
    with pytest.raises((ad.AliasError, ValueError)):
        reg(path, root, legacy, bundle=bundle, by=by)
    assert tables(path) == before  # the alias and its bundle are one unit: neither is kept


@pytest.mark.parametrize("change", [{"normalized_start": 11}, {"normalized_end": 21}, {"page": 7}, {"quote": QUOTE + "。"}])
def test_a_position_key_can_never_be_explained_away_even_with_a_perfect_bundle(scene, change):
    path, root, legacy, _ = scene
    legacy["proofs"][0].update(change)
    before = tables(path)
    with pytest.raises((ad.AliasError, ValueError)):
        reg(path, root, legacy)
    assert tables(path) == before


def test_a_non_null_section_must_be_equal_on_both_sides(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", head_proofs(section="第3節"))
    legacy = copy.deepcopy(base)
    legacy["proofs"] = alias_proofs()
    legacy["evidence_id"] = "EV-LEGACY-01"
    source = T.facts(path)[0]["source_sha256"]
    with closing(dbs.app_connect(path)) as c:
        prov.record_source_representation(c, source, "pdf", {"received": "synthetic"}, "claude")
        c.commit()
    with pytest.raises(ad.AliasError, match="section"):
        reg(path, root, legacy)
    legacy["proofs"][0]["section"] = "第3節"  # now equal on both sides: the key no longer differs
    reg(path, root, legacy)


def test_an_identical_position_needs_no_bundle_and_an_ordinary_registration_refuses_one(scene):
    path, root, legacy, _ = scene
    same = copy.deepcopy(legacy)
    same["proofs"] = head_proofs()
    reg(path, root, same, bundle=None)
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("SELECT count(*) FROM alias_provenance_bundles").fetchone()[0] == 0
        with pytest.raises(ad.AliasError, match="approved registration"):
            ad.register_alias(c, "EV-ORD", root, "legacy_compat_id", "ordinary", alias_record=copy.deepcopy(same), provenance_bundle=bundle_for(same), recorded_by="claude")


# ------------------------------------------------------------------ the medium of a source
def test_the_medium_is_unknown_until_recorded_versioned_and_never_pdf_equals_html(world):
    path, root = world
    source = T.facts(path)[0]["source_sha256"]
    with closing(dbs.app_connect(path)) as c:
        c.execute("PRAGMA foreign_keys=ON")
        assert prov.medium_of(c, source) == "unknown"
        assert prov.record_source_representation(c, source, "pdf", {"received": "x"}, "claude") == 1
        assert prov.medium_of(c, source) == "pdf"
        assert prov.record_source_representation(c, source, "html", {"received": "correction"}, "claude") == 2
        assert prov.medium_of(c, source) == "html" and c.execute("SELECT count(*) FROM source_representations").fetchone()[0] == 2
        for bad, basis in (("docx", {"a": 1}), ("pdf", {}), ("pdf", None)):
            with pytest.raises(ValueError):
                prov.record_source_representation(c, source, bad, basis, "claude")
        with pytest.raises(sqlite3.IntegrityError):
            prov.record_source_representation(c, "f" * 64, "pdf", {"a": 1}, "claude")  # not a stored source


# ------------------------------------------------------------------ both tables are append-only (real triggers of the real migration)
@pytest.mark.parametrize("recursive", [0, 1])
def test_bundles_and_representations_are_append_only(scene, recursive):
    path, root, legacy, source = scene
    reg(path, root, legacy)
    with closing(dbs.app_connect(path)) as c:
        c.execute(f"PRAGMA recursive_triggers={recursive}")
        for t, col in (("alias_provenance_bundles", "recorded_by"), ("source_representations", "recorded_by")):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                c.execute(f"UPDATE {t} SET {col}='x'")
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                c.execute(f"DELETE FROM {t}")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT OR REPLACE INTO alias_provenance_bundles VALUES ('EV-LEGACY-01', ?, '{}', 'attacker', 't')", ("a" * 64,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT OR REPLACE INTO source_representations VALUES (?, 1, 'html', '{}', 'attacker', 't')", (source,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO alias_provenance_bundles(rowid, alias_id, bundle_sha256, bundle_json, recorded_by, recorded_at) VALUES (-3, 'X', ?, '{}', 'a', 't')", ("a" * 64,))
        assert prov.verify_alias_provenance(c, "EV-LEGACY-01") == [] and prov.medium_of(c, source) == "pdf"


def test_a_bundle_whose_content_was_changed_is_detected_by_the_audit(scene):
    path, root, legacy, _ = scene
    reg(path, root, legacy)
    with closing(dbs.app_connect(path)) as c:
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='alias_provenance_bundles'").fetchall():
            c.execute(f"DROP TRIGGER {name}")  # a hostile file
        c.execute("UPDATE alias_provenance_bundles SET bundle_json = replace(bundle_json, 'nfkc-per-character', 'something-else')")
        c.commit()
        assert any("bundle_sha256 does not match" in p for p in prov.verify_alias_provenance(c, "EV-LEGACY-01"))
    assert dbs.audit(path)["invariants"]["DB-17"]["status"] == "fail"  # the dropped guards are seen by DB-17 as well


def test_db17_and_the_gate_see_the_new_migration(scene):
    path, root, legacy, _ = scene
    reg(path, root, legacy)
    assert dbs.audit(path)["invariants"]["DB-17"]["status"] == "pass"
    with closing(sqlite3.connect(path)) as c:
        assert ad.verify_history_for_acceptance(c, before=ad.history_witness(c), through=ad.MIGRATIONS[-1][0]) == []


def test_a_proof_that_only_one_side_has_is_refused_even_with_a_perfect_bundle(scene):
    path, root, legacy, _ = scene
    legacy["proofs"].append({"page": 7, "quote": "もう一つの引用", "pattern": PATTERN})
    before = tables(path)
    with pytest.raises((ad.AliasError, ValueError)):
        reg(path, root, legacy)
    assert tables(path) == before


def test_a_head_that_claims_the_medium_unknown_never_matches_an_unrecorded_source(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", head_proofs(source_kind="unknown"))
    legacy = copy.deepcopy(base)
    legacy["proofs"] = alias_proofs()
    legacy["evidence_id"] = "EV-LEGACY-01"
    before = tables(path)
    with pytest.raises(ad.AliasError, match="recorded medium"):
        reg(path, root, legacy)  # nobody recorded the medium: it is unknown, and unknown is not a match for anything, not even for the word `unknown`
    assert tables(path) == before


def test_the_decision_function_itself_refuses_an_unpaired_proof_and_differing_field_proofs(scene):
    """Defence in depth: register_alias's earlier identity check already stops these; the decision function must not rely on that."""
    path, root, legacy, source = scene
    with closing(dbs.app_connect(path)) as c:
        head = copy.deepcopy(legacy)
        head["proofs"] = head_proofs()
        for diff, expect in (({"page": 7, "unpaired": "alias"}, "exists only on the alias side"), ({"field_proofs": "differ"}, "field proofs differ")):
            reasons = prov.explain_position_differences(c, [diff], "EV-LEGACY-01", legacy, head, source)
            assert reasons and expect in reasons[0]
        assert prov.explain_position_differences(c, [], "EV-LEGACY-01", legacy, head, source) == []
