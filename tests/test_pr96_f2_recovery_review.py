"""Independent tests of Work's F-2 recovery archive (PR #96; guarded head 2788e78: `research/inbox/work-f2-recovery-candidate/recover_history.py`).

Claude-owned QA. DEFINED ONLY when Work's directory exists, so absent (not skipped) until PR #96 is merged. SYNTHETIC_ONLY: invented tables in temporary databases; the real recomputation on the
read-only audit copies is recorded in docs/reviews/PR96_F2_RECOVERY_REVIEW_2026-11-02.md (it needs files that are not in the repository). Work's code is only imported and called, never edited.
`test_known_issue_*` pin real weaknesses of the current code (they assert the CURRENT behaviour; flip them when Work fixes it).
"""
import base64
import importlib.util
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_F2_DIR") or REPO / "research" / "inbox" / "work-f2-recovery-candidate")

if (WORK / "recover_history.py").exists():
    _spec = importlib.util.spec_from_file_location("pr96_recover", WORK / "recover_history.py")
    R = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(R)
    SRC_SHA = R.EXPECTED["v03"]

    def make_old(path):
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
CREATE TABLE facts(evidence_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, note);
CREATE TABLE article_versions(article_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE plain(a, b);
CREATE TABLE editions(case_id TEXT, profile_sha256 TEXT, observed_at TEXT);
CREATE TABLE same(x INTEGER PRIMARY KEY, y TEXT);
INSERT INTO facts VALUES('EV-1','{"v":1}',NULL),('EV-2','{"v":2}',1.5),('EV-3','{"v":3}',x'00ff10');
INSERT INTO article_versions VALUES('A-1','本文 1'),('A-2','本文 2');
INSERT INTO plain VALUES('r',1),('r',1),('r',1),('s',NULL);
INSERT INTO editions VALUES('c','sha','2026-11-01');
INSERT INTO same VALUES(1,'a');
""")
            db.commit()

    def make_new(path):
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
CREATE TABLE facts(evidence_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, note);
CREATE TABLE article_versions(article_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE plain(a, b);
CREATE TABLE editions(case_id TEXT, profile_sha256 TEXT, observed_at TEXT, profile_json TEXT);
CREATE TABLE same(x INTEGER PRIMARY KEY, y TEXT);
INSERT INTO facts VALUES('EV-1','{"v":1}',NULL),('EV-2','{"v":"changed"}',1.5),('EV-3','{"v":3}',x'00ff10'),('EV-4','{"v":4}',NULL);
INSERT INTO article_versions VALUES('A-9','別の本文');
INSERT INTO plain VALUES('r',1),('s',NULL);
INSERT INTO editions VALUES('c','sha','2026-11-01','{}');
INSERT INTO same VALUES(1,'a');
""")
            db.commit()

    @pytest.fixture
    def pair(tmp_path):
        old, new = tmp_path / "old.sqlite", tmp_path / "new.sqlite"
        make_old(old)
        make_new(new)
        return old, new, tmp_path

    def kinds(rows):
        return {(r["table"], r["kind"]) for r in rows}

    def test_the_difference_is_a_multiset_by_storage_class_and_classifies_each_loss(pair):
        old, new, _ = pair
        rows = R.missing(R.read(old), R.read(new))
        assert Counter(r["table"] for r in rows) == {"facts": 1, "article_versions": 2, "plain": 2, "editions": 1}
        assert kinds(rows) == {("facts", "changed_primary_key"), ("article_versions", "missing_primary_key"), ("plain", "missing_multiset_row"), ("editions", "column_layout_changed")}
        assert not [r for r in rows if r["table"] == "same"]  # identical tables lose nothing

    def test_three_identical_rows_without_a_primary_key_keep_each_missing_occurrence(pair):
        old, new, _ = pair
        plain = [r for r in R.missing(R.read(old), R.read(new)) if r["table"] == "plain"]
        assert sorted(r["occurrence"] for r in plain) == [1, 2]  # 3 old copies of ('r',1), 1 current: two are missing

    def test_every_storage_class_survives_the_round_trip_exactly(pair):
        old, _, tmp = pair
        archive_db = tmp / "arch.sqlite"
        with closing(sqlite3.connect(archive_db)) as d:
            d.execute("CREATE TABLE facts(evidence_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, note)")
        rows = R.missing(R.read(old), {})  # everything is missing from an empty snapshot
        assert R.archive(archive_db, SRC_SHA, [r for r in rows if r["table"] == "facts"]) == 3
        with closing(sqlite3.connect(archive_db)) as d:
            got = {json.loads(t)[0][1]: R.decode(t) for (t,) in d.execute("SELECT row_typed_json FROM work_f2_recovered_rows")}
        assert got["EV-1"] == ("EV-1", '{"v":1}', None) and got["EV-2"] == ("EV-2", '{"v":2}', 1.5) and got["EV-3"] == ("EV-3", '{"v":3}', b"\x00\xff\x10")
        assert type(got["EV-2"][2]) is float and type(got["EV-3"][2]) is bytes

    def test_a_second_archive_run_adds_nothing_and_changes_no_byte(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        rows = R.missing(R.read(old), R.read(new))
        assert R.archive(target, SRC_SHA, rows) == len(rows)
        first = target.read_bytes()
        assert R.archive(target, SRC_SHA, rows) == 0 and target.read_bytes() == first

    def test_the_canonical_tables_are_untouched_by_the_archive(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        before = R.read(target)
        R.archive(target, SRC_SHA, R.missing(R.read(old), R.read(new)))
        after = R.read(target)
        assert after == before  # the archive table itself is excluded from the snapshot by name

    def test_an_exception_in_the_middle_rolls_the_whole_archive_back_including_its_ddl(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        with pytest.raises(RuntimeError, match="injected_archive_failure"):
            R.archive(target, SRC_SHA, R.missing(R.read(old), R.read(new)), fail_after=2)
        with closing(sqlite3.connect(target)) as d:
            assert d.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'work_f2_%'").fetchone()[0] == 0

    def test_a_row_whose_hash_or_width_does_not_match_is_refused_and_nothing_is_written(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        rows = R.missing(R.read(old), R.read(new))
        for bad in (dict(rows[0], row_sha256="0" * 64), dict(rows[0], columns=rows[0]["columns"] + ["extra"])):
            with pytest.raises(ValueError, match="recovery_payload_mismatch"):
                R.archive(target, SRC_SHA, [bad])
        with closing(sqlite3.connect(target)) as d:
            assert d.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'work_f2_%'").fetchone()[0] == 0

    def test_the_same_archive_identity_with_a_different_origin_is_refused(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        rows = R.missing(R.read(old), R.read(new))
        R.archive(target, SRC_SHA, rows)
        with pytest.raises(ValueError, match="recovery_identity_conflict"):
            R.archive(target, SRC_SHA, [dict(rows[0], schema="CREATE TABLE tampered(x)")])

    def archived(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        rows = R.missing(R.read(old), R.read(new))
        R.archive(target, SRC_SHA, rows)
        return target, rows

    FAKE = (SRC_SHA, "facts", "f" * 64, 1, '["evidence_id"]', '[["str","EV-FABRICATED"]]', "CREATE TABLE facts(...)", "missing_primary_key", "archive_candidate_not_active")

    @pytest.mark.parametrize("recursive", ["OFF", "ON"])
    @pytest.mark.parametrize("statement", ["UPDATE work_f2_recovered_rows SET loss_kind='x'", "DELETE FROM work_f2_recovered_rows",
                                           "INSERT OR REPLACE INTO work_f2_recovered_rows SELECT * FROM work_f2_recovered_rows LIMIT 1"])
    def test_the_archive_refuses_update_delete_and_replace_whatever_the_recursive_triggers_setting(pair, recursive, statement):
        target, _ = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            d.execute(f"PRAGMA recursive_triggers={recursive}")
            with pytest.raises(sqlite3.Error):  # an IntegrityError from the append-only triggers, or 'no such function' from the insert guard (REPLACE inserts): both refuse
                d.execute(statement)

    def test_g1_regression_a_plain_connection_cannot_append_a_fabricated_recovered_row(pair):
        """Fixed in head 2788e78: the INSERT trigger calls a capability function that only the writer connection registers, so a bare connection fails closed."""
        target, rows = archived(pair)
        with closing(sqlite3.connect(target)) as d:  # no create_function, no pragma
            with pytest.raises(sqlite3.OperationalError, match="no such function"):
                d.execute("INSERT INTO work_f2_recovered_rows VALUES(?,?,?,?,?,?,?,?,?)", FAKE)
        assert R.verify_archive(target, SRC_SHA, rows)["row_count"] == len(rows)  # nothing was added

    def test_a_row_with_a_state_other_than_the_non_active_candidate_is_refused_even_with_the_capability(pair):
        target, _ = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            d.create_function(R.GUARD, 9, lambda *values: 1)  # a spoofed capability: the CHECK constraint still holds
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                d.execute("INSERT INTO work_f2_recovered_rows VALUES('x','facts','h',1,'[]','[]','','k','restored')")

    def test_a_row_not_in_the_pinned_manifest_is_refused_by_the_writer_even_if_it_is_well_formed(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        rows = R.missing(R.read(old), R.read(new))
        R.archive(target, SRC_SHA, rows)
        # the writer's allowlist is the exact pinned payloads: asking it to add a different payload fails (and an existing archive is verified, never extended)
        extra = rows + [dict(rows[0], occurrence=99)]
        with pytest.raises(ValueError, match="recovery_identity_conflict_or_manifest_mismatch"):
            R.archive(target, SRC_SHA, extra)

    # ---- the residual limit, tested as a limit: a same-account writer can spoof the capability, but the verification against the independently rebuilt manifest DETECTS it ----

    def test_a_spoofed_capability_can_insert_but_the_manifest_verification_detects_the_extra_row(pair):
        target, rows = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            d.create_function(R.GUARD, 9, lambda *values: 1)
            d.execute("INSERT INTO work_f2_recovered_rows VALUES(?,?,?,?,?,?,?,?,?)", FAKE)
            d.commit()
        with pytest.raises(ValueError, match="manifest_mismatch|conflict"):
            R.verify_archive(target, SRC_SHA, rows)

    @pytest.mark.parametrize("trigger", sorted(["work_f2_no_update", "work_f2_no_delete", "work_f2_no_replace", "work_f2_insert_guard"]))
    def test_dropping_any_guard_trigger_is_detected_as_schema_drift(pair, trigger):
        target, rows = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            d.execute(f"DROP TRIGGER {trigger}")
            d.commit()
        with pytest.raises(ValueError, match="archive_schema_drift"):
            R.verify_archive(target, SRC_SHA, rows)

    @pytest.mark.parametrize("what", ["row_deleted", "type_changed", "column_order_changed", "ddl_text_changed", "row_reordered_values", "extra_index"])
    def test_every_kind_of_tampering_after_the_guards_are_removed_is_detected_by_the_manifest(pair, what):
        target, rows = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            for name in ("work_f2_no_update", "work_f2_no_delete"):  # the attacker removes the append-only triggers first (same account) ...
                d.execute(f"DROP TRIGGER {name}")
            if what == "row_deleted":
                d.execute("DELETE FROM work_f2_recovered_rows WHERE rowid=(SELECT min(rowid) FROM work_f2_recovered_rows)")
            elif what == "type_changed":
                d.execute("UPDATE work_f2_recovered_rows SET row_sha256=CAST(row_sha256 AS BLOB) WHERE rowid=(SELECT min(rowid) FROM work_f2_recovered_rows)")  # same characters, stored as a BLOB (a column with TEXT affinity keeps it)
            elif what == "column_order_changed":
                d.execute("UPDATE work_f2_recovered_rows SET columns_json='[\"b\",\"a\"]' WHERE rowid=(SELECT min(rowid) FROM work_f2_recovered_rows)")
            elif what == "ddl_text_changed":
                d.execute("UPDATE work_f2_recovered_rows SET source_schema_sql=source_schema_sql||' ' WHERE rowid=(SELECT min(rowid) FROM work_f2_recovered_rows)")
            elif what == "row_reordered_values":
                d.execute("UPDATE work_f2_recovered_rows SET row_typed_json=replace(row_typed_json,'EV','XX') WHERE table_name='facts'")
            else:
                d.execute("CREATE INDEX work_f2_extra ON work_f2_recovered_rows(table_name)")
            if what != "extra_index":
                for name in ("work_f2_no_update", "work_f2_no_delete"):  # ... and puts the exact trigger text back, so the schema alone looks untouched: only the ROW check can notice
                    d.execute(R.TRIGGERS[name])
            d.commit()
        # G-5 (fixed in head 6f46a20): a column that mixes a BLOB and a TEXT used to make `verify_connection` stop with a TypeError while sorting; typed values are now compared as a multiset,
        # so the refusal is the NAMED manifest error like every other row-level tampering.
        with pytest.raises(ValueError, match="archive_schema_drift" if what == "extra_index" else "manifest_mismatch"):
            R.verify_archive(target, SRC_SHA, rows)

    def test_a_second_run_over_an_existing_archive_verifies_and_writes_nothing(pair):
        target, rows = archived(pair)
        before = target.read_bytes()
        assert R.archive(target, SRC_SHA, rows) == 0 and target.read_bytes() == before

    def test_an_archive_whose_guards_drifted_is_not_silently_repaired_by_a_rerun(pair):
        target, rows = archived(pair)
        with closing(sqlite3.connect(target)) as d:
            d.execute("DROP TRIGGER work_f2_insert_guard")
            d.commit()
        before = target.read_bytes()
        with pytest.raises(ValueError, match="archive_schema_drift"):
            R.archive(target, SRC_SHA, rows)
        assert target.read_bytes() == before  # rejected, not repaired

    def test_a_failure_in_the_middle_leaves_neither_the_table_nor_its_guards(pair):
        old, new, tmp = pair
        target = tmp / "clone.sqlite"
        target.write_bytes(new.read_bytes())
        with pytest.raises(RuntimeError, match="injected_archive_failure"):
            R.archive(target, SRC_SHA, R.missing(R.read(old), R.read(new)), fail_after=2)
        with closing(sqlite3.connect(target)) as d:
            assert d.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'work_f2_%'").fetchone()[0] == 0

    def test_the_manifest_depends_on_the_source_sha_the_rows_the_column_order_and_the_schema(pair):
        old, new, _ = pair
        rows = R.missing(R.read(old), R.read(new))
        base = R.manifest(SRC_SHA, rows)
        assert base["row_count"] == len(rows)
        assert R.manifest("0" * 64, rows)["payload_sha256"] != base["payload_sha256"]
        assert R.manifest(SRC_SHA, rows[:-1])["payload_sha256"] != base["payload_sha256"]
        assert R.manifest(SRC_SHA, list(reversed(rows)))["payload_sha256"] == base["payload_sha256"]  # the manifest is over a sorted payload: row order does not matter
        renamed = [dict(r, columns=list(reversed(r["columns"]))) for r in rows]
        assert R.manifest(SRC_SHA, renamed)["payload_sha256"] != base["payload_sha256"]
        with pytest.raises(ValueError, match="invalid_source_sha256"):
            R.manifest("not-a-sha", rows)

    def test_a_duplicated_recovery_input_is_refused(pair):
        old, new, _ = pair
        rows = R.missing(R.read(old), R.read(new))
        with pytest.raises(ValueError, match="duplicate_recovery_input"):
            R.payloads(SRC_SHA, rows + [rows[0]])

    def test_g2_limit_the_archive_objects_are_still_not_registry_owned_objects_of_the_frozen_schema(pair):
        """G-2 is mitigated by Work's own verifier (exact schema SHA over the table and the four triggers) but NOT by the formal schema-state check (DB-17): the objects are named `work_f2_*`, outside
        the owned prefixes, and adding them to the registry would make every other database 'drift'. Work correctly does not rename them to bypass the check. Formal integration needs a reviewed migration after 0009
        (docs/F2_RESTORATION_CONTRACT_PROPOSAL.md). Pinned as an open limit."""
        from src.db_contract import additive_schema as ad
        names = ["work_f2_no_update", "work_f2_no_delete", "work_f2_no_replace", "work_f2_insert_guard", "work_f2_recovered_rows"]
        assert set(names[:4]) == set(R.TRIGGERS) and not any(n.startswith(tuple(ad._OWNED_PREFIXES)) for n in names)