"""SELF_TEST (Claude, contract owner) for the provenance and witness checks of the migration history (M1.g5).  Synthetic databases built by the runner itself on disposable copies; nothing here touches a
real database.  NOT an independent QA and not an acceptance of g5.

Why: an independent scan (qa/frozen-replace-scan, a2e1e79) showed that a plain connection can replace a row of ``schema_migrations`` with INSERT OR REPLACE and that ``verify_history`` /
``verify_schema_state`` do not see a changed ``from_version``, ``applied_at`` or ``description``.  The frozen SQL is not changed here; these are DETECTION functions that are NOT wired into
``apply()`` or the accepted audits (g4 / g8 depend on them; wiring them in is for the owner and Work to agree).
"""
import hashlib
import shutil
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad

CHAIN = [m[0] for m in ad.MIGRATIONS]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """A native database before any migration (built once, copied for every test)."""
    root = tmp_path_factory.mktemp("g5base")
    path, _p = S.make_native(root)
    RevisionStore(path, root / "backup.sqlite")
    return path


def fresh(base, tmp_path, name="work.sqlite"):
    target = tmp_path / name
    shutil.copy(base, target)
    return target


def migrated(base, tmp_path, only=None):
    path = fresh(base, tmp_path)
    report = ad.apply(path, confirm_disposable_copy=True, only=only)
    assert not report["rolled_back"], report
    return path


def raw(path):
    return sqlite3.connect(path)          # a plain connection: no capability, default PRAGMAs


def rows(path):
    with closing(raw(path)) as c:
        return c.execute("SELECT rowid, version, from_version, applied_at, description, seq FROM schema_migrations ORDER BY seq").fetchall()


def replace_row(path, seq, *, rowid=None, **changes):
    """INSERT OR REPLACE of the row with this sequence, changing some columns; with ``rowid`` given the replacement keeps that rowid (a careful tamperer)."""
    with closing(raw(path)) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(schema_migrations)")]
        old = dict(zip(cols, c.execute("SELECT * FROM schema_migrations WHERE seq=?", (seq,)).fetchone()))
        old_rowid = c.execute("SELECT rowid FROM schema_migrations WHERE seq=?", (seq,)).fetchone()[0]
        old.update(changes)
        if rowid is True:
            c.execute(f"INSERT OR REPLACE INTO schema_migrations(rowid,{','.join(cols)}) VALUES (?,{','.join('?' for _ in cols)})", (old_rowid, *old.values()))
        else:
            c.execute(f"INSERT OR REPLACE INTO schema_migrations({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", tuple(old.values()))
        c.commit()


# ------------------------------------------------------------------ a database built by the runner is consistent
def test_H1_a_database_built_by_the_runner_has_no_provenance_problem(base, tmp_path):
    path = migrated(base, tmp_path)
    with closing(raw(path)) as c:
        assert ad.verify_history(c) == [] and ad.verify_history_provenance(c) == []
        w = ad.history_witness(c)
    assert [r[0] for r in w] == CHAIN and [r[5] for r in w] == [int(v.split("-")[0]) for v in CHAIN]


def test_H2_the_chain_is_consistent_across_separate_runs_and_the_step_is_recognised_as_an_append(base, tmp_path):
    path = migrated(base, tmp_path, only=tuple(CHAIN[:2]))
    with closing(raw(path)) as c:
        assert ad.verify_history_provenance(c) == []
        before = ad.history_witness(c)
    assert len(before) == 2
    report = ad.apply(path, confirm_disposable_copy=True)
    assert not report["rolled_back"]
    with closing(raw(path)) as c:
        assert ad.verify_history_provenance(c) == []
        assert ad.verify_history_step(before, c, expected_new=tuple(CHAIN[2:])) == []
        assert ad.verify_history_step(before, c) == []


# ------------------------------------------------------------------ what a plain connection can do, and what is seen
@pytest.mark.parametrize("column,value,message", [
    ("from_version", "0000-forged", "says it follows '0000-forged'"),
    ("description", "FORGED description", "description that is not the one this code holds"),
    ("applied_at", "2999-01-01T00:00:00+00:00", "before the migration applied just before it"),     # the NEXT row now goes back in time
    ("applied_at", "yesterday", "not an ISO-8601 time"),
    ("applied_at", "2026-11-08T10:00:00", "without a time zone"),
])
def test_H3_each_provenance_column_is_checked_on_its_own(base, tmp_path, column, value, message):
    """The replacement keeps its rowid, so the physical-order check does not fire: each check has to find its own change."""
    path = migrated(base, tmp_path)
    replace_row(path, 3, rowid=True, **{column: value})
    with closing(raw(path)) as c:
        problems = ad.verify_history_provenance(c)
    assert any(message in x for x in problems), (column, value, problems)
    assert not any("written again" in x for x in problems)


def test_H3b_a_row_written_again_with_identical_content_is_seen_only_by_its_position(base, tmp_path):
    path = migrated(base, tmp_path)
    with closing(raw(path)) as c:
        before = ad.history_witness(c)
    replace_row(path, 3)                                                                 # the very same values, but the row now lies after the later ones
    with closing(raw(path)) as c:
        problems = ad.verify_history_provenance(c)
        step = ad.verify_history_step(before, c)
    assert any("written again" in x for x in problems) and len(problems) == 1
    assert step == []                                                                    # the witness compares columns, not the position: documented


def staged(base, tmp_path):
    """One migration per run, so that the recorded times are clearly apart."""
    path = fresh(base, tmp_path)
    for version in CHAIN:
        report = ad.apply(path, confirm_disposable_copy=True, only=(version,))
        assert not report["rolled_back"], report
    return path


def test_H4_a_careful_replacement_that_keeps_the_rowid_and_a_plausible_time_is_seen_only_with_a_witness(base, tmp_path):
    from datetime import datetime
    path = staged(base, tmp_path)
    with closing(raw(path)) as c:
        before = ad.history_witness(c)
        assert ad.verify_history_provenance(c) == []
    r = rows(path)
    previous, middle, following = (datetime.fromisoformat(r[i][3]) for i in (1, 2, 3))
    assert previous < following
    between = (previous + (following - previous) / 2).isoformat()                       # still ordered, still a valid time, but not what was recorded
    assert between != r[2][3]
    replace_row(path, r[2][5], rowid=True, applied_at=between)
    with closing(raw(path)) as c:
        provenance = ad.verify_history_provenance(c)
        step = ad.verify_history_step(before, c)
    assert provenance == []                                                             # the documented residual: nothing in the database itself shows it
    assert any("changed its applied_at" in x for x in step)                             # the witness kept outside does


def test_H5_null_version_and_non_positive_rowid_are_reported(base, tmp_path):
    path = migrated(base, tmp_path)
    with closing(raw(path)) as c:
        sha = "a" * 64
        c.execute("INSERT INTO schema_migrations(version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (NULL,NULL,'2999-01-01T00:00:00+00:00',?,?,98,?,'[]')", (sha, "x", sha))
        c.execute("INSERT INTO schema_migrations(rowid,version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (-3,'0099-x',NULL,'2999-01-02T00:00:00+00:00',?,?,99,?,'[]')", (sha, "x", sha))
        c.commit()
        problems = ad.verify_history_provenance(c)
    assert any("has no version" in x for x in problems) and any("rowids are positive" in x for x in problems)


# ------------------------------------------------------------------ the witness (evidence kept outside the database)
def drop_protection(path):
    with closing(raw(path)) as c:
        for name in ("trg_ao_schema_migrations_update", "trg_ao_schema_migrations_delete"):
            c.execute(f"DROP TRIGGER IF EXISTS {name}")
        c.commit()


@pytest.mark.parametrize("column", [c for c in ad.HISTORY_COLUMNS if c != "version"])
def test_H6_any_changed_column_of_an_old_row_is_named(base, tmp_path, column):
    path = migrated(base, tmp_path, only=tuple(CHAIN[:3]))
    with closing(raw(path)) as c:
        before = ad.history_witness(c)
    drop_protection(path)                                                              # an operator with DDL rights: the triggers do not stop everyone
    value = {"seq": 77, "checksum": "e" * 64, "statements_applied_sha256": "e" * 64}.get(column, "CHANGED")
    with closing(raw(path)) as c:
        c.execute(f"UPDATE schema_migrations SET {column}=? WHERE seq=3", (value,))
        c.commit()
        problems = ad.verify_history_step(before, c)
    assert any(f"changed its {column}" in x for x in problems)


def test_H7_a_missing_old_row_a_wrong_next_row_and_a_stale_user_version_are_reported(base, tmp_path):
    path = migrated(base, tmp_path, only=tuple(CHAIN[:2]))
    with closing(raw(path)) as c:
        before = ad.history_witness(c)
        assert ad.verify_history_step(before, c) == []                                 # nothing happened: fine
    # a row that is gone
    gone = fresh(base, tmp_path, "gone.sqlite")
    shutil.copy(path, gone)
    drop_protection(gone)
    with closing(raw(gone)) as c:
        c.execute("DELETE FROM schema_migrations WHERE seq=2")
        c.commit()
        assert any("is gone" in x for x in ad.verify_history_step(before, c))
    # the chain skipped one migration (the one after next is recorded right after the last)
    skip = fresh(base, tmp_path, "skip.sqlite")
    shutil.copy(path, skip)
    with closing(raw(skip)) as c:
        sha = "b" * 64
        c.execute("INSERT INTO schema_migrations(version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (?,?,?,?,?,?,?,'[]')",
                  (CHAIN[3], CHAIN[1], "2999-01-01T00:00:00+00:00", sha, "x", ad._seq(CHAIN[3]), sha))
        c.commit()
        assert any("is not the next one of the chain" in x for x in ad.verify_history_step(before, c))
    # the next row is right but names the wrong predecessor
    liar = fresh(base, tmp_path, "liar.sqlite")
    shutil.copy(path, liar)
    with closing(raw(liar)) as c:
        sha = "c" * 64
        c.execute("INSERT INTO schema_migrations(version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (?,?,?,?,?,?,?,'[]')",
                  (CHAIN[2], "0000-forged", "2999-01-01T00:00:00+00:00", sha, "x", ad._seq(CHAIN[2]), sha))
        c.commit()
        problems = ad.verify_history_step(before, c)
    assert any("says it follows '0000-forged'" in x for x in problems) and any("user_version" in x for x in problems)
    # the next row is right but carries a wrong sequence number
    wrong_seq = fresh(base, tmp_path, "wrongseq.sqlite")
    shutil.copy(path, wrong_seq)
    with closing(raw(wrong_seq)) as c:
        sha = "d" * 64
        c.execute("INSERT INTO schema_migrations(version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (?,?,?,?,?,?,?,'[]')",
                  (CHAIN[2], CHAIN[1], "2999-01-01T00:00:00+00:00", sha, "x", 77, sha))
        c.commit()
        assert any("has the sequence 77" in x for x in ad.verify_history_step(before, c))
    # a new row whose sequence puts it BEFORE the old ones
    early = fresh(base, tmp_path, "early.sqlite")
    shutil.copy(path, early)
    with closing(raw(early)) as c:
        sha = "e" * 64
        c.execute("INSERT INTO schema_migrations(version,from_version,applied_at,checksum,description,seq,statements_applied_sha256,applied_statement_ids) VALUES (?,?,?,?,?,?,?,'[]')",
                  (CHAIN[2], CHAIN[1], "2999-01-01T00:00:00+00:00", sha, "x", 1, sha))
        c.commit()
        assert any("no longer the first rows of the history" in x for x in ad.verify_history_step(before, c))


def test_H8_expected_new_is_checked_exactly(base, tmp_path):
    path = migrated(base, tmp_path, only=tuple(CHAIN[:2]))
    with closing(raw(path)) as c:
        before = ad.history_witness(c)
    ad.apply(path, confirm_disposable_copy=True, only=(CHAIN[2],))
    with closing(raw(path)) as c:
        assert ad.verify_history_step(before, c, expected_new=(CHAIN[2],)) == []
        assert any("was to add" in x for x in ad.verify_history_step(before, c, expected_new=(CHAIN[2], CHAIN[3])))
        assert any("was to add" in x for x in ad.verify_history_step(before, c, expected_new=()))


# ------------------------------------------------------------------ read only, and the edges
def test_H9_both_checks_work_on_a_read_only_connection_and_change_nothing(base, tmp_path):
    path = migrated(base, tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ro = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        w = ad.history_witness(ro)
        assert ad.verify_history_provenance(ro) == [] and ad.verify_history_step(w, ro) == []
    finally:
        ro.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_H10_a_database_without_a_history_is_never_answered_with_a_silent_pass(base, tmp_path):
    """Antigravity's independent QA of PR #268 (91abc70, e6f2367): with no schema_migrations these checks answered [] / () / [], so a gate written as 'no problems' would accept an unmigrated or wiped database."""
    path = fresh(base, tmp_path)
    with closing(raw(path)) as c:
        assert any("does not exist" in x for x in ad.verify_history_provenance(c))
        assert any("does not exist" in x for x in ad.verify_history_step((), c))
        assert ad.history_witness(c) == ()                                   # a value, not a verdict: it proves nothing about old rows (the gate refuses it)
        assert ad.verify_history(c) == []                                    # the EXISTING contract is unchanged: apply() relies on it to migrate a database that has no history


def test_H11_the_existing_checks_and_the_runner_are_unchanged_by_the_new_functions(base, tmp_path):
    path = migrated(base, tmp_path)
    replace_row(path, 3, description="FORGED description")
    with closing(raw(path)) as c:
        # verify_history still does not look at the description (documented); the new check does
        assert not any("description" in x for x in ad.verify_history(c))
        assert any("description" in x for x in ad.verify_history_provenance(c))


def test_H12_a_history_of_another_layout_is_never_called_consistent(base, tmp_path):
    """schema_migrations as the draft of PR #70 made it (another column set): verify_history raises, so these checks must not answer 'consistent' for a history they cannot read."""
    path = fresh(base, tmp_path)
    with closing(raw(path)) as c:
        c.execute("CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, description TEXT, statements_sha256 TEXT, applied_at TEXT)")
        c.execute("INSERT INTO schema_migrations VALUES ('0001-x','d',?, '2026-01-01T00:00:00+00:00')", ("a" * 64,))
        c.commit()
        with pytest.raises(ad.MigrationError):
            ad.verify_history(c)
        assert any("another layout" in x for x in ad.verify_history_provenance(c))
        with pytest.raises(ad.MigrationError, match="no witness can be taken"):
            ad.history_witness(c)
        assert any("another layout" in x for x in ad.verify_history_step((), c))


# ------------------------------------------------------------------ the acceptance gate: a missing, empty, wiped or partial history can never be accepted (Antigravity's False-Pass finding)
def gate(path, *, before, expected_new=None, through=None):
    with closing(raw(path)) as c:
        return ad.verify_history_for_acceptance(c, before=before, expected_new=expected_new, through=through)


def witness_of(path):
    with closing(raw(path)) as c:
        return ad.history_witness(c)


def test_H13_a_complete_history_with_its_witness_passes_the_gate_and_so_does_a_fresh_migration_with_expected_new(base, tmp_path):
    done = migrated(base, tmp_path)
    assert gate(done, before=witness_of(done)) == []                                              # nothing happened since the witness
    fresh_path = fresh(base, tmp_path, "fresh.sqlite")
    ad.apply(fresh_path, confirm_disposable_copy=True)
    assert gate(fresh_path, before=(), expected_new=tuple(CHAIN)) == []                           # the whole history was created in this step
    stepped = fresh(base, tmp_path, "stepped.sqlite")
    ad.apply(stepped, confirm_disposable_copy=True, only=tuple(CHAIN[:3]))
    before = witness_of(stepped)
    ad.apply(stepped, confirm_disposable_copy=True)
    assert gate(stepped, before=before, expected_new=tuple(CHAIN[3:])) == []


def test_H14_no_table_an_empty_table_and_a_foreign_database_are_refused_with_the_reason(base, tmp_path):
    none = fresh(base, tmp_path, "none.sqlite")
    assert any("does not exist" in x for x in gate(none, before=()))
    assert any("does not exist" in x for x in gate(none, before=(), expected_new=tuple(CHAIN)))      # even with the right expectation: nothing is recorded
    empty = fresh(base, tmp_path, "empty.sqlite")
    with closing(raw(empty)) as c:
        c.execute(ad.SCHEMA_MIGRATIONS)
        c.commit()
    problems = gate(empty, before=(), expected_new=tuple(CHAIN))
    assert any("holds no migration" in x for x in problems) and any("not the complete chain" in x for x in problems)
    foreign = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(foreign)) as c:
        c.execute("CREATE TABLE random_user_table (id INTEGER PRIMARY KEY)")
        c.commit()
    assert gate(foreign, before=()) != []


def test_H15_a_partial_history_is_refused_even_though_every_row_is_consistent(base, tmp_path):
    partial = migrated(base, tmp_path, only=tuple(CHAIN[:4]))
    with closing(raw(partial)) as c:
        assert ad.verify_history_provenance(c) == [] and ad.verify_history(c) == []                  # the rows that are there ARE consistent: this is exactly why they cannot be the gate
    problems = gate(partial, before=witness_of(partial))
    assert any("not the complete chain: 4 of" in x and "missing" in x for x in problems)
    assert gate(partial, before=witness_of(partial), through=CHAIN[3]) == []                         # but a gate that EXPECTS the history to stop there accepts it
    assert any("not the complete chain" in x for x in gate(partial, before=witness_of(partial), through=CHAIN[2]))     # one more than expected is refused too
    assert any("not a migration of this code" in x for x in gate(partial, before=witness_of(partial), through="0999-nothing"))


def test_H16_a_wiped_history_is_refused_whatever_the_witness_says(base, tmp_path):
    path = migrated(base, tmp_path)
    before = witness_of(path)
    drop_protection(path)
    with closing(raw(path)) as c:
        c.execute("DELETE FROM schema_migrations")
        c.commit()
    problems = gate(path, before=before)
    assert any("holds no migration" in x for x in problems) and any("is gone" in x for x in problems) and any("not the complete chain: 0 of" in x for x in problems)
    assert gate(path, before=(), expected_new=tuple(CHAIN)) != []                                  # an attacker who passes an empty witness gets nothing either


def test_H17_without_a_witness_or_with_an_empty_one_the_gate_does_not_pass(base, tmp_path):
    path = migrated(base, tmp_path)
    assert any("no witness was given" in x for x in gate(path, before=None))
    assert any("an empty witness proves nothing" in x for x in gate(path, before=()))
    assert any("was to add" in x for x in gate(path, before=(), expected_new=tuple(CHAIN[:2])))


def test_H18_a_tampered_row_a_replaced_row_and_a_changed_checksum_are_refused_by_the_gate(base, tmp_path):
    path = migrated(base, tmp_path)
    before = witness_of(path)
    r = rows(path)
    replace_row(path, r[2][5], rowid=True, description="FORGED description")
    assert any("description" in x for x in gate(path, before=before))
    second = tmp_path / "second"
    second.mkdir()
    path2 = migrated(base, second)
    before2 = witness_of(path2)
    drop_protection(path2)
    with closing(raw(path2)) as c:
        c.execute("UPDATE schema_migrations SET checksum=? WHERE seq=3", ("f" * 64,))
        c.commit()
    assert any("checksum mismatch" in x for x in gate(path2, before=before2))


def test_H19_another_layout_cannot_be_accepted_and_the_gate_reads_but_never_writes(base, tmp_path):
    path = fresh(base, tmp_path)
    with closing(raw(path)) as c:
        c.execute("CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, description TEXT, statements_sha256 TEXT, applied_at TEXT)")
        c.commit()
    assert any("another layout" in x for x in gate(path, before=()))
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    good = migrated(base, ro_dir)
    digest = hashlib.sha256(good.read_bytes()).hexdigest()
    before = witness_of(good)
    ro = sqlite3.connect(f"file:{good.as_posix()}?mode=ro", uri=True)
    try:
        assert ad.verify_history_for_acceptance(ro, before=before) == []
    finally:
        ro.close()
    assert hashlib.sha256(good.read_bytes()).hexdigest() == digest


def test_H20_the_existing_runner_and_verify_history_are_unchanged(base, tmp_path):
    path = fresh(base, tmp_path)
    with closing(raw(path)) as c:
        assert ad.verify_history(c) == []                       # apply() migrates a database that has no history: this answer stays
    report = ad.apply(path, confirm_disposable_copy=True)
    assert not report["rolled_back"] and report["applied"] == CHAIN
