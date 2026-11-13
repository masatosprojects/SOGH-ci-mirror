"""SELF_TEST (Claude, contract owner) for the frozen migrations 0013-g07-quarantine-staging and 0014-g06-source-series: the tables of the product candidates of PR #306 (Antigravity; independent QA by Claude on head
59028ebc) now belong to the migration chain, so that DB-17 (including the table allow-list, PR #341) sees them and the modules no longer create anything on a migrated database.
SYNTHETIC databases only; applied to no operational database. Not an acceptance of g6 / g7.

What is proven: the two frozen files are byte-pinned and EQUAL (statement for statement, minus comments and IF NOT EXISTS) to the SCHEMA_SQL of the two modules, so they cannot drift; they create 3 + 2 EMPTY tables
and 10 + 7 guards and change no other row; the history, the schema state and DB-17 see them; on a migrated database the modules work with the tables of the migration (stage -> approve by a registered human who is not
the stager -> promote; a series is persisted, verified against its rows and linked to an impact); the guards fail closed on a connection that did not register the connection function; no REPLACE / DELETE; a pre-existing
table of these names stops the migration."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S  # noqa: E402  (puts Work's pipeline on the path)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402
from src.db_contract import quarantine_staging as qs  # noqa: E402
from src.versioning import series as sv  # noqa: E402

D = Path(ad.MIGRATION_DIR)
F13, F14 = D / "0013_g07_quarantine_staging.sql", D / "0014_g06_source_series.sql"
PIN13 = "97e6f9462952396b923ea88763cc8eb5fbfbe3a813948f41eaf8f2a1ffd2a78e"
PIN14 = "ca8b56d4c73b5e24c7f2f4eaf7dcac2cf6d39df01fedef03b5eac08b307c86d6"
ID13, ID14 = "0013-g07-quarantine-staging", "0014-g06-source-series"
T13, T14 = ad.QUARANTINE_TABLES, ad.SERIES_TABLES


def module_statements(sql):
    out, cur = [], ""
    for line in sql.splitlines(keepends=True):
        if not cur and (not line.strip() or line.lstrip().startswith("--")):
            continue
        cur += line
        if sqlite3.complete_statement(cur):
            st = "\n".join(l for l in cur.splitlines() if not l.lstrip().startswith("--")).strip().rstrip(";").strip()
            import re
            out.append(ad._norm(re.sub(r"\b(CREATE\s+(?:TABLE|TRIGGER|INDEX))\s+IF\s+NOT\s+EXISTS\s+", r"\1 ", st)))
            cur = ""
    return out


def native(tmp_path):
    path, _p = S.make_native(tmp_path, "n.sqlite")
    RevisionStore(path, tmp_path / "n.backup")
    return path


@pytest.fixture
def migrated(tmp_path):
    path = native(tmp_path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and ID13 in r["applied"] and ID14 in r["applied"]
    return path


def test_the_frozen_files_are_byte_pinned():
    assert hashlib.sha256(F13.read_bytes()).hexdigest() == PIN13 and hashlib.sha256(F14.read_bytes()).hexdigest() == PIN14


def test_the_files_equal_the_module_schema_statement_for_statement():
    for f, sql in ((F13, qs.SCHEMA_SQL), (F14, sv.SCHEMA_SQL)):
        parsed = [ad._norm(st) for st, _ in ad.parse_frozen(f.read_bytes().decode("utf-8"))]
        assert parsed == module_statements(sql), f.name


def test_the_chain_has_both_and_the_history_the_schema_state_and_the_table_allow_list_are_clean(migrated):
    ids = [m[0] for m in ad.MIGRATIONS]
    assert ids.index(ID13) < ids.index(ID14)
    with closing(sqlite3.connect(migrated)) as c:
        assert ad.verify_history(c) == [] and ad.verify_schema_state(c) == []


def test_they_create_five_empty_tables_and_seventeen_guards_and_change_no_other_row(tmp_path):
    path = native(tmp_path)
    before_ids = tuple(m[0] for m in ad.MIGRATIONS if int(m[0].split("-", 1)[0]) < 13)
    assert not ad.apply(path, confirm_disposable_copy=True, only=before_ids)["rolled_back"]

    def counts(p):
        with closing(sqlite3.connect(p)) as c:
            names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations' ORDER BY 1")]
            return {n: c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}

    before = counts(path)
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"] and r["applied"] == [ID13, ID14]
    after = counts(path)
    assert all(after.pop(t) == 0 for t in T13 + T14) and after == before
    with closing(sqlite3.connect(path)) as c:
        triggers = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
        assert len([t for t in triggers if t.startswith(ad.QUARANTINE_TRIGGER_PREFIXES)]) == 10 and len([t for t in triggers if t.startswith(ad.SERIES_TRIGGER_PREFIXES)]) == 7


def test_a_module_initialisation_on_a_migrated_database_creates_nothing(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        before = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        qs.init_quarantine_schema(c)
        sv.init_series_schema(c)
        assert {r[0] for r in c.execute("SELECT name FROM sqlite_master")} == before and ad.verify_schema_state(c) == []


def test_g7_the_flow_works_on_the_migrated_tables_and_needs_a_registered_human_who_is_not_the_stager(migrated, monkeypatch):
    monkeypatch.setenv("SOGH_AUTHORIZED_REVIEWERS", "yamada")
    with closing(sqlite3.connect(migrated)) as c:
        qs.init_quarantine_schema(c)
        qs.stage_candidate(c, "S1", "src", "table", "admission_quota", "16", staged_by="operator-9")
        with pytest.raises((PermissionError, ValueError, sqlite3.DatabaseError)):
            qs.review_candidate(c, "S1", "APPROVED", "mallory")  # not registered
        qs.stage_candidate(c, "S2", "src", "table", "admission_quota", "30", staged_by="yamada")
        with pytest.raises((PermissionError, ValueError, sqlite3.DatabaseError)):
            qs.review_candidate(c, "S2", "APPROVED", "yamada")  # the stager
        assert qs.review_candidate(c, "S1", "APPROVED", "yamada") is True
        assert qs.promote_candidate(c, "S1", "F1") is True
        assert c.execute("SELECT key, value FROM canonical_facts_staging_target").fetchall() == [("admission_quota", "16")]


def test_g7_a_connection_that_did_not_register_the_function_cannot_approve_or_promote_and_nothing_is_replaced(migrated, monkeypatch):
    monkeypatch.setenv("SOGH_AUTHORIZED_REVIEWERS", "yamada")
    with closing(sqlite3.connect(migrated)) as c:
        qs.init_quarantine_schema(c)
        qs.stage_candidate(c, "S1", "src", "table", "admission_quota", "16", staged_by="operator-9")
        qs.review_candidate(c, "S1", "APPROVED", "yamada")
        qs.promote_candidate(c, "S1", "F1")
        qs.stage_candidate(c, "S3", "src", "table", "admission_quota", "20", staged_by="operator-9")
        c.commit()
    with closing(sqlite3.connect(migrated)) as plain:  # no register_quarantine_connection_guards
        plain.execute("INSERT OR REPLACE INTO _quarantine_approval_seals(staging_id,reviewer,approval_token,payload_sha256) VALUES ('S3','bob','" + "B" * 32 + "','x')")
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("UPDATE quarantine_staging_candidates SET review_status='APPROVED',approved_by='bob',approval_token=? WHERE staging_id='S3'", ("B" * 32,))
        plain.rollback()
        for sql in ("DELETE FROM quarantine_staging_candidates", "UPDATE canonical_facts_staging_target SET value='x'", "DELETE FROM canonical_facts_staging_target"):
            with pytest.raises(sqlite3.DatabaseError):
                plain.execute(sql)
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("INSERT OR REPLACE INTO quarantine_staging_candidates(staging_id,source_id,format_type,extracted_key,extracted_value,quarantine_status,review_status,sha256_hash) VALUES ('S1','s','t','k','99','QUARANTINED','PENDING','h')")


def _three():
    s = sv.create_series("SER", "U", "T", "v1 text")
    sv.append_revision(s, "v2 text")
    sv.append_revision(s, "v3 text")
    return s


def test_g6_a_series_is_persisted_verified_against_its_rows_and_linked_to_an_impact(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        sv.init_series_schema(c)
        s = _three()
        assert sv.persist_series(c, s) == 3
        ok, errors = sv.verify_series_against_rows(c, s)
        assert ok, errors
        sv.record_revision_impact(c, "I1", "SER", "SER_rev1", "SER_rev2", "EV-1", "A1")
        with pytest.raises(sqlite3.DatabaseError):
            sv.record_revision_impact(c, "I2", "SER", "NOPE_rev1", "NOPE_rev2", "EV-1", "A1")  # editions that do not exist


def test_g6_the_guards_refuse_replace_delete_update_a_wrong_hash_and_a_skipped_revision(migrated):
    with closing(sqlite3.connect(migrated)) as c:
        sv.init_series_schema(c)
        sv.persist_series(c, _three())
        c.commit()
        sha = hashlib.sha256(b"x").hexdigest()
        for sql in ("DELETE FROM source_document_series_editions", "UPDATE source_document_series_editions SET university='OTHER'",
                    "INSERT OR REPLACE INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) VALUES ('SER_rev2','SER','U','T',2,'h','FORGED','SER_rev1',1)"):
            with pytest.raises(sqlite3.DatabaseError):
                c.execute(sql)
        with pytest.raises(sqlite3.DatabaseError):  # the hash does not match the content
            c.execute("INSERT INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) VALUES ('SER_rev4','SER','U','T',4,'deadbeef','x','SER_rev3',0)")
        with pytest.raises(sqlite3.DatabaseError):  # revision 9 skips 4..8
            c.execute("INSERT INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) VALUES ('SER_rev9','SER','U','T',9,?,'x','SER_rev3',0)", (sha,))


def test_g6_a_connection_that_did_not_register_the_function_cannot_insert_an_edition(migrated):
    with closing(sqlite3.connect(migrated)) as plain:
        with pytest.raises(sqlite3.DatabaseError):
            plain.execute("INSERT INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) VALUES ('A_rev1','A','U','T',1,'h','x',NULL,0)")


@pytest.mark.parametrize("tables, make, pre", [(T13, "CREATE TABLE quarantine_staging_candidates(x)", ad.preflight_g07_quarantine), (T14, "CREATE TABLE source_document_series_editions(x)", ad.preflight_g06_series)])
def test_a_table_of_those_names_that_exists_already_stops_the_migration(tmp_path, tables, make, pre):
    path = native(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(m[0] for m in ad.MIGRATIONS if int(m[0].split("-", 1)[0]) < 13))
    with closing(sqlite3.connect(path)) as c:
        c.execute(make)
        c.commit()
        assert any("already exist" in p for p in pre(c))  # the pre-flight alone refuses it ...
    before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    with pytest.raises(ad.MigrationError):  # ... and since D1 the stray table is DRIFT, so apply() stops before any migration
        ad.apply(path, confirm_disposable_copy=True)
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before
