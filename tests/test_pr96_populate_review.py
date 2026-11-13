"""Independent, DIRECT tests of Work's `populate()` (PR #96: `research/inbox/work-f2-recovery-candidate/sql_candidate.py`) at its `mode=rw` URI form.

Claude-owned QA. DEFINED ONLY when Work's file exists (SOGH_WORK_F2_DIR may point at the directory). SYNTHETIC_ONLY: disposable synthetic databases in a temporary directory, no real rows, no real database.
Independence: the candidate database is built with CLAUDE'S OWN registration of Work's SQL text (the monkeypatched registry also used by tests/test_pr96_sql_candidate_review.py), not with Work's `experimental_registry`; Work's `populate` is then CALLED directly.
Shared helper, stated: the row payload text uses Work's `recover_history.canonical/typed/sha`, because the guard compares that exact text.
What passing means: `populate` behaves as described on these inputs. It is NOT the F-2 acceptance: the 36-row archive, the 30-row restoration candidate, the facts and offering conflicts, the formal 0010 registration, the DB-17/19 ownership and the F-2 signature are separate acceptance items for the user.
A new empty database appearing anywhere is a FAIL (see `test_populate_never_creates_a_database`). `known_issue` tests pin a current behaviour that is a weakness or undecided; flip them when Work changes it."""
import hashlib
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_F2_DIR") or REPO / "research" / "inbox" / "work-f2-recovery-candidate")
SQLFILE = WORK / "0010-work-f2-archive-candidate.sql"

if SQLFILE.exists() and (WORK / "sql_candidate.py").exists():
    sys.path.insert(0, str(WORK))
    sys.dont_write_bytecode = True
    from tests import db_support as S
    from admissions_pipeline.revisions import RevisionStore  # noqa: E402
    from src.db_contract import additive_schema as ad
    import recover_history as r  # noqa: E402  (Work's helper: the canonical payload text)
    import sql_candidate as c  # noqa: E402  (the function under test)
    from unittest.mock import patch

    TEXT = SQLFILE.read_text(encoding="utf-8")
    STATEMENTS = tuple(s.strip().rstrip(";").strip() for s in re.split(r"^-- @@\s*$", TEXT, flags=re.M)[1:])
    SRC = "a" * 64

    def _preflight(db):
        return [f"preexisting archive object {n!r}" for (n,) in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'work!_f2!_%' ESCAPE '!'")]

    ENTRY = ("0015-work-f2-archive-candidate", "F-2 archive candidate (Work)", lambda db: STATEMENTS, _preflight, TEXT)

    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def build(tmp, name="candidate.sqlite", migrate=True):
        path, _ = S.make_native(tmp, name)
        RevisionStore(path, tmp / (name + ".backup"))
        if migrate:
            with patch.object(ad, "MIGRATIONS", ad.MIGRATIONS + (ENTRY,)), patch.object(ad, "_OWNED_PREFIXES", ad._OWNED_PREFIXES + ("work_f2_",)):
                ad.apply(path, confirm_disposable_copy=True)
        return path

    def rows(n=2, **over):
        out = []
        for i in range(n):
            text = r.canonical(r.typed(("old", i + 7, None)))
            d = {"table": "old_table", "columns": ["id", "number", "unknown"], "row": text, "row_sha256": r.sha(text.encode()), "occurrence": 1 + i,
                 "schema": "CREATE TABLE old_table(id,number,unknown)", "kind": "table_absent"}
            d.update(over)
            out.append(d)
        return out

    def listing(directory):
        return sorted(p.name for p in Path(directory).iterdir())

    def canonical_state(path):
        """Everything except the archive table: every other table row by row, plus user_version. A row-level difference, not only a hash."""
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            state = {"user_version": db.execute("PRAGMA user_version").fetchone()[0]}
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite!_%' ESCAPE '!' AND name NOT LIKE 'work!_f2!_%' ESCAPE '!' ORDER BY name").fetchall():
                state[name] = db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            return state

    def archive_rows(path):
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT count(*) FROM work_f2_recovered_rows").fetchone()[0]

    # ------------------------------------------------------------------ the normal path
    def test_populate_inserts_the_rows_into_an_existing_candidate_and_changes_nothing_else(tmp_path):
        path = build(tmp_path)
        before, files = canonical_state(path), listing(tmp_path)
        assert c.populate(path, SRC, rows(2)) == 2
        assert archive_rows(path) == 2 and canonical_state(path) == before  # every other table, row by row, and user_version unchanged
        assert listing(tmp_path) == files  # no new file, no -journal / -wal left behind
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not db.execute("PRAGMA foreign_key_check").fetchall()

    def test_populate_is_idempotent_and_refuses_changed_fewer_or_foreign_input_without_a_byte_changing(tmp_path):
        path = build(tmp_path)
        assert c.populate(path, SRC, rows(2)) == 2
        done = sha(path)
        assert c.populate(path, SRC, rows(2)) == 0 and sha(path) == done  # the same input again: nothing happens
        altered = rows(2)
        altered[0]["row"] = altered[0]["row"].replace("7", "8")
        for label, args in (("a changed row", (SRC, altered)), ("fewer rows", (SRC, rows(1))), ("another source sha", ("b" * 64, rows(2)))):
            with pytest.raises(ValueError):
                c.populate(path, *args)
            assert sha(path) == done, label

    def test_populate_rolls_back_a_failure_part_way_without_leftovers_and_a_later_run_succeeds(tmp_path):
        path = build(tmp_path)
        before, files = sha(path), listing(tmp_path)
        with pytest.raises(RuntimeError):
            c.populate(path, SRC, rows(3), fail_after=1)
        assert sha(path) == before and listing(tmp_path) == files and archive_rows(path) == 0
        assert c.populate(path, SRC, rows(3)) == 3 and archive_rows(path) == 3

    # ------------------------------------------------------------------ a missing path must never become a new database
    @pytest.mark.parametrize("name", ["missing.sqlite", "missing candidate.sqlite", "missing#x.sqlite", "missing%41.sqlite", "日本語 無い.sqlite", "sub dir/missing.sqlite"])
    def test_populate_never_creates_a_database(tmp_path, name):
        existing = build(tmp_path)
        files = listing(tmp_path)
        target = tmp_path / name
        if "/" in name:
            (tmp_path / "sub dir").mkdir()
            files = listing(tmp_path)
        before_sub = listing(target.parent)
        with pytest.raises(sqlite3.OperationalError):
            c.populate(target, SRC, rows(1))
        assert not target.exists() and listing(target.parent) == before_sub and listing(tmp_path) == files  # a new (even empty) database is a FAIL
        assert sha(existing) == sha(existing)

    # ------------------------------------------------------------------ reserved characters in the path
    NAMES = ["sp ace.sqlite", "hash#tag.sqlite", "pct%41.sqlite", "per%25cent.sqlite", "日本語 練習.sqlite", "amp&eq=1.sqlite", "plus+sign.sqlite",
             "br[ack]et.sqlite", "q'uote.sqlite", "semi;colon.sqlite", "at@sign.sqlite", "tilde~comma,.sqlite", "bang!.sqlite", "dollar$.sqlite"]

    @pytest.mark.parametrize("name", NAMES)
    def test_populate_accepts_an_existing_candidate_whose_name_has_reserved_uri_characters(tmp_path, name):
        path = build(tmp_path, name)
        before = canonical_state(path)
        assert c.populate(path, SRC, rows(1)) == 1 and archive_rows(path) == 1 and canonical_state(path) == before

    def test_populate_does_not_decode_a_percent_sequence_into_a_different_file(tmp_path):
        """`decoy%41.sqlite` must not be read as `decoyA.sqlite`: the URI form must quote the percent sign."""
        percent, plain = build(tmp_path, "decoy%41.sqlite"), build(tmp_path, "decoyA.sqlite")
        plain_before = sha(plain)
        assert c.populate(percent, SRC, rows(1)) == 1
        assert sha(plain) == plain_before and archive_rows(plain) == 0 and archive_rows(percent) == 1

    def test_populate_works_with_a_relative_path_and_the_same_file_by_another_spelling(tmp_path, monkeypatch):
        path = build(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert c.populate(Path(path.name), SRC, rows(1)) == 1
        assert c.populate(tmp_path / "." / path.name, SRC, rows(1)) == 0  # the same database by a different spelling: it is recognised, not duplicated
        assert archive_rows(path) == 1

    # ------------------------------------------------------------------ the wrong target
    def test_populate_refuses_a_file_that_is_not_a_database_a_directory_and_an_empty_file_without_changing_them(tmp_path):
        text = tmp_path / "notadb.sqlite"
        text.write_text("hello" * 1000, encoding="utf-8")
        empty = tmp_path / "empty.sqlite"
        empty.write_bytes(b"")
        before = (sha(text), sha(empty), listing(tmp_path))
        with pytest.raises(sqlite3.DatabaseError):
            c.populate(text, SRC, rows(1))
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            c.populate(empty, SRC, rows(1))
        with pytest.raises(sqlite3.OperationalError):
            c.populate(tmp_path, SRC, rows(1))
        assert (sha(text), sha(empty), listing(tmp_path)) == before and empty.stat().st_size == 0

    def test_populate_refuses_a_database_without_the_archive_and_a_tampered_archive_without_changing_a_byte(tmp_path):
        bare = build(tmp_path, "bare.sqlite", migrate=False)
        before_bare = sha(bare)
        with pytest.raises(ValueError, match="archive_schema_drift"):
            c.populate(bare, SRC, rows(1))
        assert sha(bare) == before_bare
        for i, sql in enumerate(["DROP TRIGGER work_f2_no_update", "DROP TRIGGER work_f2_no_delete", "DROP TRIGGER work_f2_insert_guard", "CREATE INDEX work_f2_extra ON work_f2_recovered_rows(row_sha256)"]):
            tampered = build(tmp_path, f"tampered{i}.sqlite")
            with closing(sqlite3.connect(tampered)) as db:
                db.execute(sql)
                db.commit()
            before = sha(tampered)
            with pytest.raises(ValueError, match="archive_schema_drift"):
                c.populate(tampered, SRC, rows(1))
            assert sha(tampered) == before, sql

    # ------------------------------------------------------------------ malformed input
    MALFORMED = {
        "occurrence is a string": {"occurrence": "1"},
        "occurrence is a float": {"occurrence": 1.0},
        "occurrence is a bool": {"occurrence": True},
        "row hash is wrong": {"row_sha256": "0" * 64},
        "table is None": {"table": None},
        "columns is a string": {"columns": "id,number"},
        "row is not a string": {"row": 5},
    }

    @pytest.mark.parametrize("label", sorted(MALFORMED))
    def test_populate_refuses_malformed_rows_without_changing_the_database(tmp_path, label):
        path = build(tmp_path)
        before, files = sha(path), listing(tmp_path)
        with pytest.raises(Exception):  # which exception is pinned separately; what must hold: refused, nothing changed, no new file
            c.populate(path, SRC, rows(1, **self_over(label)))
        assert sha(path) == before and listing(tmp_path) == files and archive_rows(path) == 0

    def self_over(label):
        return MALFORMED[label]

    @pytest.mark.parametrize("bad", ["abc", None, 5, "A" * 64, "g" * 64, " " + "a" * 63])
    def test_populate_refuses_a_malformed_source_sha(tmp_path, bad):
        path = build(tmp_path)
        before = sha(path)
        with pytest.raises(ValueError, match="invalid_source_sha256"):
            c.populate(path, bad, rows(1))
        assert sha(path) == before

    def test_populate_refuses_duplicate_rows_inside_one_input(tmp_path):
        path = build(tmp_path)
        before = sha(path)
        with pytest.raises(ValueError, match="duplicate_recovery_input"):
            c.populate(path, SRC, rows(1) + rows(1))
        assert sha(path) == before

    # ------------------------------------------------------------------ pinned weaknesses (not judged; flip when Work changes them)
    def test_known_issue_pr96_an_arbitrary_loss_kind_is_accepted_and_stored(tmp_path):
        """F-M1-G3-01 (minor). The loss kind is a free string: `kind="weird"` is inserted. In the fixed pipeline the rows come from `recover_history.missing` and the manifest is compared, so this is not reachable through `main()`;
        as a library call `populate` does not validate the vocabulary. Work to say whether the vocabulary is closed (then validate) or open."""
        path = build(tmp_path)
        assert c.populate(path, SRC, rows(1, kind="weird")) == 1 and archive_rows(path) == 1

    def test_known_issue_pr96_a_row_that_is_not_a_string_raises_a_bare_attribute_error(tmp_path):
        """F-M1-G3-02 (informational). The refusal is correct (nothing changes) but the exception is a raw AttributeError (`int` has no `encode`), not a controlled ValueError like the other refusals."""
        path = build(tmp_path)
        with pytest.raises(AttributeError):
            c.populate(path, SRC, rows(1, row=5))

    def test_known_issue_pr96_an_empty_row_list_succeeds_as_a_no_op(tmp_path):
        """F-M1-G3-03 (informational). `populate(path, sha, [])` returns 0 and changes nothing: a silent success for an empty archive. The fixed pipeline never passes an empty list; a caller that did would not be told."""
        path = build(tmp_path)
        before = sha(path)
        assert c.populate(path, SRC, []) == 0 and sha(path) == before
