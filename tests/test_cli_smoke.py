"""End-to-end smoke tests that actually invoke the CLIs as subprocesses
(not just calling their Python functions directly), so "this command
works" claims in docs/README are backed by something that runs the real
entry point the way a human would type it.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# The CLIs print JSON with ensure_ascii=False, so pin the child's stdout to
# UTF-8; otherwise the result depends on the host locale (cp932 on Japanese
# Windows) and decoding the output fails.
_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_ENV,
        timeout=30,
    )


def test_run_qa_suite_cli_on_sample_fixture():
    result = _run(["-m", "src.run_qa_suite", "--articles-json", "tests/fixtures/sample_articles.json"])
    assert result.returncode == 1  # fixture intentionally includes bad articles
    report = json.loads(result.stdout)
    assert report["article_qa"]["per_article"][0]["article_id"] == "sample-clean"
    assert report["article_qa"]["per_article"][0]["ok"] is True


def test_sqlite_integrity_cli_on_clean_db(tmp_path: Path):
    db = tmp_path / "clean.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    conn.close()

    result = _run(["-m", "src.db_qa.sqlite_integrity", str(db)])
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["issue_count"] == 0


def test_validate_export_cli_on_invalid_record(tmp_path: Path):
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"EV-1": {"university": "〇〇大学"}}, ensure_ascii=False), encoding="utf-8")

    result = _run(["-m", "src.integration.validate_export", str(export)])
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["invalid_count"] == 1
