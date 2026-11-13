"""The audit tool must catch the problems it claims to catch. Synthetic data only."""
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from src.integration import audit_handoff as ah


def _write_handoff(root: Path, files: dict[str, bytes]) -> None:
    entries = []
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        entries.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (root / "manifest.json").write_text(json.dumps({"files": entries}), encoding="utf-8")


def test_manifest_passes_then_detects_tampering_and_unlisted_files(tmp_path: Path):
    _write_handoff(tmp_path, {"a.txt": b"hello", "sub/b.json": b"{}"})
    assert ah.check_manifest(tmp_path)["status"] == "pass"
    (tmp_path / "a.txt").write_bytes(b"hellO")
    (tmp_path / "extra.txt").write_bytes(b"x")
    result = ah.check_manifest(tmp_path)
    assert result["status"] == "fail"
    assert any("sha256 differs: a.txt" in p for p in result["problems"])
    assert any("not in manifest" in p for p in result["problems"])


def _db(path: Path, rows: list[tuple]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    con.commit()
    con.close()
    return path


def test_database_equal_to_original_passes_and_row_change_fails(tmp_path: Path):
    original = _db(tmp_path / "o.sqlite", [(1, "a"), (2, "b")])
    same = _db(tmp_path / "s.sqlite", [(1, "a"), (2, "b")])
    assert ah.check_database(same, original)["status"] == "pass"
    changed = _db(tmp_path / "c.sqlite", [(1, "a"), (2, "B")])
    result = ah.check_database(changed, original)
    assert result["status"] == "fail" and result["tables_with_different_rows"] == ["t"]


def test_reconciliation_flags_a_changed_number_but_only_reviews_a_vanished_flag(tmp_path: Path):
    con = sqlite3.connect(tmp_path / "l.sqlite")
    con.execute("CREATE TABLE fact_claims (id TEXT, value_json TEXT)")
    con.execute("INSERT INTO fact_claims VALUES ('f1', ?)", (json.dumps({"value": 150}),))
    con.execute("INSERT INTO fact_claims VALUES ('f2', ?)", (json.dumps({"extension_possible": True, "minutes": 30}),))
    con.commit()
    con.close()
    recon = {
        "fact_links": [
            {"legacy_fact_id": "f1", "evidence_id": "E1", "pages": [5]},
            {"legacy_fact_id": "f2", "evidence_id": "E2", "pages": [5]},
        ],
        "reconciliation_counts": {"matched_saved_original": 2},
    }
    evidence = {
        "E1": {"value": {"count": 150}, "proofs": [{"page": 5}]},
        "E2": {"value": {"minutes": 30, "qualifier": "延長する場合がある"}, "proofs": [{"page": 5}]},
    }
    result = ah.check_reconciliation(tmp_path / "l.sqlite", recon, evidence)
    assert result["status"] == "review"
    assert [m["legacy_fact_id"] for m in result["needs_manual_review"]] == ["f2"]
    assert not result["independent_conflicts"]

    evidence["E1"]["value"] = {"count": 999}
    result = ah.check_reconciliation(tmp_path / "l.sqlite", recon, evidence)
    assert result["status"] == "fail"
    assert result["independent_conflicts"][0]["legacy_fact_id"] == "f1"


def test_reconciliation_flags_link_to_a_page_the_evidence_does_not_cite(tmp_path: Path):
    con = sqlite3.connect(tmp_path / "l.sqlite")
    con.execute("CREATE TABLE fact_claims (id TEXT, value_json TEXT)")
    con.execute("INSERT INTO fact_claims VALUES ('f1', ?)", (json.dumps({"value": 5}),))
    con.commit()
    con.close()
    recon = {"fact_links": [{"legacy_fact_id": "f1", "evidence_id": "E1", "pages": [9]}], "reconciliation_counts": {}}
    result = ah.check_reconciliation(tmp_path / "l.sqlite", recon, {"E1": {"value": {"count": 5}, "proofs": [{"page": 5}]}})
    assert result["status"] == "fail" and result["link_page_not_in_evidence_proofs"] == ["f1"]


def test_privacy_scan_finds_secrets_emails_and_personal_paths_in_files_and_db(tmp_path: Path):
    (tmp_path / "clean.txt").write_text("募集人員は5名です。", encoding="utf-8")
    assert ah.check_privacy(tmp_path, None)["status"] == "pass"
    (tmp_path / "leak.txt").write_text(
        "contact taro@example.com\nC:\\Users\\taro\\secret.txt\napi_key = abcdef123456\n", encoding="utf-8")
    kinds = {f["kind"] for f in ah.check_privacy(tmp_path, None)["findings"]}
    assert {"email", "windows_user_path", "secret_assignment"} <= kinds

    db = _db(tmp_path / "d.sqlite", [(1, "tel 03-1234-5678")])
    (tmp_path / "empty").mkdir()
    kinds = {f["kind"] for f in ah.check_privacy(tmp_path / "empty", db)["findings"]}
    assert "phone_jp" in kinds


def test_privacy_scan_decompresses_gz_text_but_leaves_sqlite_to_the_cell_scan(tmp_path: Path):
    (tmp_path / "x.txt.gz").write_bytes(gzip.compress("mail me: a@b.co".encode()))
    assert any(f["kind"] == "email" for f in ah.check_privacy(tmp_path, None)["findings"])


def test_values_in_quotes_flags_a_number_with_no_source_line():
    ev = {"E1": {"value": {"count": 5, "details_page": 6, "period": "AC_2027"},
                 "proofs": [{"page": 5, "quote": "募集人員は 5 名です"}]}}
    assert ah.check_values_in_quotes({"evidence": ev})["status"] == "pass"  # page/period fields are not quoted facts
    ev["E1"]["value"]["count"] = 50  # 5 -> 50: "50" is not in the quote even though "5" is
    result = ah.check_values_in_quotes({"evidence": ev})
    assert result["status"] == "fail" and result["not_in_own_quotes"][0]["value"] == 50


def test_source_pdfs_are_skipped_not_passed_without_a_pdf_dir():
    result = ah.check_source_pdfs({"evidence": {}, "articles": []}, None)
    assert result["status"] == "skipped"
