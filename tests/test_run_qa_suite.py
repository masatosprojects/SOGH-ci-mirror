import sqlite3
from pathlib import Path

from src import run_qa_suite


def test_run_with_no_sqlite_returns_empty_db_qa():
    report = run_qa_suite.run(None)
    assert report["db_qa"] is None


def test_run_with_clean_sqlite_has_no_issues(tmp_path: Path):
    db = tmp_path / "clean.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    conn.close()

    report = run_qa_suite.run(db)
    assert report["db_qa"]["issue_count"] == 0


def test_run_articles_reports_findings_for_bad_article():
    data = {
        "evidence": {
            "EV-1": {
                "university": "〇〇大学",
                "faculty": "理学部",
                "department": None,
                "admission_method": "総合型選抜",
                "fiscal_year": 2026,
                "quota": 30,
            }
        },
        "articles": [{"article_id": "a1", "text": "募集人数は30名です。", "claim": {"fiscal_year": 2026}}],
    }
    result = run_qa_suite.run_articles(data)
    assert len(result["per_article"]) == 1
    assert result["per_article"][0]["ok"] is False
    assert result["per_article"][0]["findings"]


def test_run_articles_clean_article_ok():
    data = {
        "evidence": {
            "EV-1": {
                "university": "〇〇大学",
                "faculty": "理学部",
                "department": None,
                "admission_method": "総合型選抜",
                "fiscal_year": 2026,
                "quota": 30,
            }
        },
        "articles": [
            {
                "article_id": "a1",
                "text": "〇〇大学理学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。",
                "claim": {"university": "〇〇大学", "faculty": "理学部", "admission_method": "総合型選抜", "fiscal_year": 2026},
            }
        ],
    }
    result = run_qa_suite.run_articles(data)
    assert result["per_article"][0]["ok"] is True
    assert result["batch_findings"] == []


def test_run_articles_batch_flags_near_duplicates():
    evidence = {
        "EV-1": {
            "university": "〇〇大学",
            "faculty": "理学部",
            "department": None,
            "admission_method": "総合型選抜",
            "fiscal_year": 2026,
            "quota": 30,
        }
    }
    claim = {"university": "〇〇大学", "faculty": "理学部", "admission_method": "総合型選抜", "fiscal_year": 2026}
    base_text = "〇〇大学理学部の総合型選抜の募集人数は30名[EV-1]です。詳細は大学公式サイトでご確認ください。"
    data = {
        "evidence": evidence,
        "articles": [
            {"article_id": "a1", "text": base_text, "claim": claim},
            {"article_id": "a2", "text": base_text, "claim": claim},
        ],
    }
    result = run_qa_suite.run_articles(data)
    categories = {f["category"] for f in result["batch_findings"]}
    assert "near_duplicate_article" in categories


def test_main_returns_nonzero_exit_on_integrity_error(tmp_path: Path, capsys):
    db = tmp_path / "broken.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER, FOREIGN KEY(parent_id) REFERENCES parent(id))")
    conn.execute("INSERT INTO child VALUES (1, 999)")
    conn.commit()
    conn.close()

    exit_code = run_qa_suite.main(["--sqlite", str(db)])
    assert exit_code == 1
