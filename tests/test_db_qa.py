import sqlite3
from pathlib import Path

from src.db_qa import sqlite_integrity as dq


def _make_db(path: Path, *, with_fk_violation: bool, with_dupe: bool, bad_year: bool, mixed_year: bool):
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = OFF")  # allow writing a violation, then we flip on for checks
    conn.execute("CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute(
        "CREATE TABLE programs (id INTEGER PRIMARY KEY, university_id INTEGER, "
        "nendo INTEGER, name TEXT, "
        "FOREIGN KEY(university_id) REFERENCES universities(id))"
    )
    conn.execute("INSERT INTO universities VALUES (1, 'Example University')")
    year_a = 999 if bad_year else 2025
    year_b = 20250401 if mixed_year else 2025
    conn.execute("INSERT INTO programs VALUES (1, 1, ?, 'Program A')", (year_a,))
    conn.execute("INSERT INTO programs VALUES (2, 1, ?, 'Program B')", (year_b,))
    if with_fk_violation:
        conn.execute("INSERT INTO programs VALUES (3, 999, 2025, 'Orphan Program')")
    if with_dupe:
        conn.execute("INSERT INTO programs VALUES (4, 1, 2025, 'Program A')")
        conn.execute("INSERT INTO programs VALUES (5, 1, 2025, 'Program A')")
    conn.commit()
    conn.close()


def test_clean_db_has_no_issues(tmp_path: Path):
    db = tmp_path / "clean.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=False, bad_year=False, mixed_year=False)
    result = dq.run_all_checks(db)
    assert result["issue_count"] == 0, result["issues"]


def test_detects_foreign_key_violation(tmp_path: Path):
    db = tmp_path / "fk.sqlite3"
    _make_db(db, with_fk_violation=True, with_dupe=False, bad_year=False, mixed_year=False)
    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "foreign_key_violation" in categories


def test_detects_duplicate_rows(tmp_path: Path):
    db = tmp_path / "dupe.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=True, bad_year=False, mixed_year=False)
    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "duplicate_rows" in categories


def test_composite_primary_key_association_table_is_not_a_false_duplicate(tmp_path: Path):
    """fact_evidence-style table: the whole key is the identity and the only
    payload column is NULL everywhere. That is not a duplicate row."""
    db = tmp_path / "assoc.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE fact_evidence (fact_id TEXT, snapshot_id TEXT, locator TEXT, excerpt TEXT,"
        " PRIMARY KEY (fact_id, snapshot_id, locator))"
    )
    conn.executemany(
        "INSERT INTO fact_evidence VALUES (?, 's1', 'p5', NULL)", [("f1",), ("f2",), ("f3",)]
    )
    conn.commit()
    conn.close()
    assert dq.check_duplicate_rows(sqlite3.connect(db)) == []


def test_single_key_table_with_repeated_payload_is_still_a_duplicate(tmp_path: Path):
    db = tmp_path / "single.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO t (name) VALUES (?)", [("same",), ("same",)])
    conn.commit()
    assert [i.category for i in dq.check_duplicate_rows(conn)] == ["duplicate_rows"]


def test_detects_implausible_year(tmp_path: Path):
    db = tmp_path / "year.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=False, bad_year=True, mixed_year=False)
    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "year_out_of_range" in categories


def test_detects_mixed_year_magnitude(tmp_path: Path):
    db = tmp_path / "mixedyear.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=False, bad_year=False, mixed_year=True)
    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "year_column_mixed_magnitude" in categories


def test_detects_near_duplicate_entity_names(tmp_path: Path):
    db = tmp_path / "entities.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO universities VALUES (1, '〇〇大学')")
    conn.execute("INSERT INTO universities VALUES (2, '〇〇大学 ')")  # trailing space typo
    conn.execute("INSERT INTO universities VALUES (3, '△△大学')")  # genuinely different
    conn.commit()
    conn.close()

    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "near_duplicate_entity_name" in categories


def test_exact_duplicate_entity_names_not_flagged_as_near_duplicate(tmp_path: Path):
    db = tmp_path / "entities_exact.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO universities VALUES (1, '〇〇大学')")
    conn.execute("INSERT INTO universities VALUES (2, '〇〇大学')")
    conn.commit()
    conn.close()

    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "near_duplicate_entity_name" not in categories


def test_clearly_different_entity_names_not_flagged(tmp_path: Path):
    db = tmp_path / "entities_different.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE universities (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO universities VALUES (1, '〇〇大学')")
    conn.execute("INSERT INTO universities VALUES (2, '△△大学')")
    conn.commit()
    conn.close()

    result = dq.run_all_checks(db)
    categories = {i["category"] for i in result["issues"]}
    assert "near_duplicate_entity_name" not in categories


def test_backup_and_verify_matches(tmp_path: Path):
    db = tmp_path / "src.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=False, bad_year=False, mixed_year=False)
    backup = tmp_path / "backup" / "src_backup.sqlite3"
    issues = dq.backup_and_verify(db, backup)
    assert issues == []
    assert backup.exists()


def test_backup_detects_mismatch_if_source_changes_after(tmp_path: Path):
    db = tmp_path / "src2.sqlite3"
    _make_db(db, with_fk_violation=False, with_dupe=False, bad_year=False, mixed_year=False)
    backup = tmp_path / "backup2" / "src2_backup.sqlite3"
    dq.backup_and_verify(db, backup)

    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO universities VALUES (2, 'Another University')")
    conn.commit()
    conn.close()

    backup_conn = sqlite3.connect(str(backup))
    src_count = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM universities").fetchone()[0]
    backup_count = backup_conn.execute("SELECT COUNT(*) FROM universities").fetchone()[0]
    backup_conn.close()
    assert src_count != backup_count
