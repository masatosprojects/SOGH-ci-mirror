"""SELF_TEST (Claude, author of the g6 contract) for scripts/g6_sim_e2e.py: "an old edition -> a SIMULATED new edition -> versioned source -> impacted articles only -> revision candidates".

Two targets, never confused:
  * a SYNTHETIC fixture database (built with tests/db_support.py helpers, invented university, temporary file): always runs;
  * a disposable COPY of the pinned real v06 file: is run by hand from tests/qa_g6_sim_e2e_real_clone.py (a test_*.py file must not skip; the real file is not in the repository). The pinned file itself is never opened for writing.
The new edition is SIMULATED and fictional. This is not an independent QA and not an acceptance of g6.
"""
import hashlib
import importlib.util
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S  # noqa: E402  (puts Work's pipeline on the path)
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import EvidenceStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "g6_sim_e2e.py"
spec = importlib.util.spec_from_file_location("g6_sim_e2e", SCRIPT)
e2e = importlib.util.module_from_spec(spec)
sys.modules["g6_sim_e2e"] = e2e
spec.loader.exec_module(e2e)

PINNED = Path(r"C:\Users\USER\OneDrive\ドキュメント\ChatGPT\SOGH\outputs\resume-m1\work-solo-light-20261106\pinned-v06-readonly.sqlite")
PINNED_SHA = "a8e48b5b16239368e9b5c05aad1dbeb692a657f28dab909bf3c99fff41539578"
SHA_A, SHA_B = "a" * 64, "b" * 64


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_fixture(tmp_path, migrate=True):
    """Two universities. Source A has a quota (page 1) and an exam date (page 2); three articles: A1 cites the quota, A2 cites only the date (same source), B cites source B."""
    path, _p = S.make_native(tmp_path, "fx.sqlite")  # case "case": source A, EV-case-1 (quota 16), article art-case
    S.ingest_cycle(EvidenceStore(path), "caseB", S.profile(university="別の試験大学", sha=SHA_B), tmp_path, count=20)
    quote = "第1次選考は11月20日に行います。"
    record = ('{"evidence_id":"EV-case-2","fact_key":"exam_date","key":"exam_date","source_sha256":"%s","source_url":"https://example.ac.jp/試験大学/2027.pdf",'
              '"proofs":[{"page":2,"quote":"%s"}],"university":"試験大学"}') % (SHA_A, quote)
    page1 = ("令和9年度 試験大学 試験学部 入学者選抜要項。出願資格は高等学校を卒業した者または卒業見込みの者です。提出書類は志願理由書と調査書です。"
             "募集人員は16名です。選考は書類審査と面接によって総合的に行います。入学検定料は各自の方法で納付してください。")
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE source_pages SET text=?, text_sha256=? WHERE source_sha256=? AND page=1", (page1, hashlib.sha256(page1.encode()).hexdigest(), SHA_A))
        db.execute("INSERT INTO source_pages(source_sha256,page,text,text_sha256) VALUES (?,?,?,?)", (SHA_A, 2, quote, hashlib.sha256(quote.encode()).hexdigest()))
        db.execute("INSERT INTO facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) VALUES "
                   "('EV-case-2','case',?,'exam_date','{\"month\":11,\"day\":20}',?,'source_checked_for_saved_version')", (SHA_A, record))
        db.execute("INSERT INTO article_versions(article_id,case_id,input_hash,series,title,body,artifact_path,publish_allowed) VALUES "
                   "('art-case-2','case',?,'schedule','日程記事','# 日程\\n\\n第1次選考は11月20日[EV-case-2]に行います。\\n',?,0)", ("c" * 64, str(tmp_path / "x.md")))
        db.execute("INSERT INTO article_evidence(article_id,evidence_id) VALUES ('art-case-2','EV-case-2')")
        db.commit()
    RevisionStore(path, tmp_path / "fx.backup")
    if migrate:
        r = ad.apply(path, confirm_disposable_copy=True)
        assert not r["rolled_back"] and r["applied"][-1] == "0014-g06-source-series"
    return path


@pytest.fixture
def fixture_run(tmp_path):
    path = build_fixture(tmp_path)
    before_hash = _sha(path)
    result = e2e.run(path)
    return path, result, before_hash


def test_synthetic_every_check_passes_and_the_numbers_are_exact(fixture_run):
    _path, r, _ = fixture_run
    assert r["all_checks_pass"], [k for k, v in r["checks"].items() if not v]
    assert r["simulated_change"] == {"evidence_id": "EV-case-1", "page": 1, "old_number": "16", "new_number": "17"}
    assert [e["rev"] for e in r["editions"]] == [1, 2] and r["new_edition"]["label"] == "SIMULATED"
    d = r["diff"]
    assert (d["pages_added"], d["pages_removed"], d["pages_changed"], d["changed_lines"], d["value_changes"]) == (1, 0, 1, 1, 1)  # the added page is the SIMULATED label page
    assert d["value_change_old"] == [["number:16", "persons:16"]] and d["value_change_new"] == [["number:17", "persons:17"]]


def test_synthetic_only_the_dependent_article_is_flagged_both_directions(fixture_run):
    _path, r, _ = fixture_run
    i = r["impact"]
    assert i["articles_total"] == 3 and i["class_counts"] == {"revision_candidate": 1, "review_same_page": 0, "not_flagged": 2}
    assert i["articles_flagged"] == ["art-case"] == i["oracle_articles"]  # flagged: the article that cites the changed quota
    assert i["evidence_flagged_republish"] == ["EV-case-1"] == i["oracle_evidence"]
    assert i["articles_not_flagged"] == ["art-case-2", "art-caseB"]  # NOT flagged: same source other page, and another university
    assert i["summary"]["evidence_value_change"] == 1 and i["summary"]["evidence_intact"] == 2 and i["summary"]["articles_republish_required"] == 1 and i["summary"]["articles_ok"] == 2
    assert i["recorded_impacts"] == [{"impact_id": "IMP-001", "article_id": "art-case", "evidence_id": "EV-case-1"}] and i["impact_table_rows"] == 1


def test_synthetic_the_0014_guards_refuse_every_attempt_and_leave_the_rows_alone(fixture_run):
    path, r, _ = fixture_run
    assert [g["case"] for g in r["guards"]] == ["skipped_revision_number", "wrong_hash", "insert_or_replace_old_edition", "update_old_edition_content",
                                                "update_old_edition_hash", "delete_old_edition", "delete_new_edition"]
    assert all(g["refused"] and g["message"].startswith("G-06 VIOLATION") for g in r["guards"])
    assert r["guard_row_count_before_after"][0] == r["guard_row_count_before_after"][1]
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM source_document_series_editions").fetchone()[0] == 2


def test_synthetic_the_old_rows_of_every_original_table_are_unchanged_and_only_the_series_tables_grew(tmp_path):
    path = build_fixture(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        before = e2e.table_digests(db, skip=e2e.SERIES_TABLES)
    r = e2e.run(path)
    with closing(sqlite3.connect(path)) as db:
        after = e2e.table_digests(db, skip=e2e.SERIES_TABLES)
        assert db.execute("SELECT count(*) FROM source_document_series_editions").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM series_revision_article_impacts").fetchone()[0] == 1
    assert before == after and r["old_tables"]["unchanged"] and r["old_tables"]["changed_tables"] == []
    assert r["series_tables_rows_after"] == {"source_document_series_editions": 2, "series_revision_article_impacts": 1}


def test_synthetic_the_new_edition_is_labelled_simulated_in_its_stored_text_and_series_title(fixture_run):
    path, _r, _ = fixture_run
    with closing(sqlite3.connect(path)) as db:
        title, new_text = db.execute("SELECT document_title, content_text FROM source_document_series_editions WHERE rev_number=2").fetchone()
    assert "SIMULATED" in title and "NOT AN OFFICIAL PUBLICATION" in title and "SIMULATED" in new_text and "公式発表ではありません" in new_text


def test_an_unmigrated_database_is_refused_before_anything_is_written(tmp_path):
    path = build_fixture(tmp_path, migrate=False)
    before = _sha(path)
    with pytest.raises(SystemExit):
        e2e.run(path)
    assert _sha(path) == before


def test_the_cli_prints_json_and_exits_zero(tmp_path):
    path = build_fixture(tmp_path)
    p = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    import json
    assert json.loads(p.stdout)["all_checks_pass"] is True
