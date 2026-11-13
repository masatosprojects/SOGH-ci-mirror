"""SELF_TEST (Claude, author) for scripts/g6_real_pair_e2e.py: previous edition -> stored current edition -> versioned source -> impacted articles.

Runs only on a SYNTHETIC fixture (tests/db_support.py helpers, invented university, fictional PDF-free page texts): no PDF and no real database are needed and nothing is skipped.
The real pair (official PDF + pinned v06 copy) is run by hand from tests/qa_g6_real_pair_real_clone.py. The oracle is a plain string search; this is not an independent QA.
"""
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from tests.test_m1_g6_sim_e2e import SHA_A, build_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "g6_real_pair_e2e.py"
spec = importlib.util.spec_from_file_location("g6_real_pair_e2e", SCRIPT)
rp = importlib.util.module_from_spec(spec)
sys.modules["g6_real_pair_e2e"] = rp
spec.loader.exec_module(rp)

PREFIX = SHA_A[:8]
DATE = "第1次選考は11月20日に行います。"
# the stored (NEW) page 1 of the fixture holds "募集人員は16名です"; page 2 holds DATE.
OLD_PAGE1 = ("令和8年度 試験大学 試験学部 入学者選抜要項。出願資格は高等学校を卒業した者または卒業見込みの者です。提出書類は志願理由書と調査書です。"
             "募集人員は14名です。選考は書類審査と面接によって総合的に行います。入学検定料は各自の方法で納付してください。")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def fx(tmp_path):
    return build_fixture(tmp_path)


def test_a_changed_quota_flags_only_the_citing_article_both_directions(fx):
    r = rp.run(fx, [OLD_PAGE1, DATE], PREFIX)  # quota 14 -> 16; the date quote is unchanged on the same page
    assert r["all_checks_pass"], [k for k, v in r["checks"].items() if not v]
    o, i = r["oracle"], r["impact"]
    assert (o["new_edition_evidence"], o["proofs"], o["proofs_unchanged"], o["proofs_moved"], o["proofs_changed"]) == (2, 2, 1, 0, 1)
    assert o["evidence_changed"] == ["EV-case-1"] == i["evidence_flagged_republish"]
    assert i["articles_flagged"] == ["art-case"] == o["articles_by_text"] == o["articles_by_table"]
    assert i["class_counts"] == {"revision_candidate": 1, "review_same_page": 0, "not_flagged": 2}
    assert i["proof_mismatches"] == [] and i["articles_not_flagged"] == ["art-case-2", "art-caseB"]
    assert [c["evidence_id"] for c in r["real_changes"]] == ["EV-case-1"] and r["real_changes"][0]["product_status"] == "value_change"
    assert "14" in r["real_changes"][0]["old_excerpt"] and "16" in r["real_changes"][0]["new_excerpt"]


def test_a_quote_that_only_moved_page_is_not_a_change(fx):
    r = rp.run(fx, [OLD_PAGE1.replace("14名", "16名") + DATE, "別のページです。"], PREFIX)  # both quotes exist, the date one on page 1 instead of 2
    assert r["all_checks_pass"], [k for k, v in r["checks"].items() if not v]
    o = r["oracle"]
    assert (o["proofs_unchanged"], o["proofs_moved"], o["proofs_changed"]) == (1, 1, 0) and o["evidence_changed"] == [] and o["evidence_moved_only"] == ["EV-case-2"]
    assert r["impact"]["articles_flagged"] == [] and r["impact"]["evidence_flagged_republish"] == [] and r["real_changes"] == []
    assert r["impact"]["articles_review_same_page"] == ["art-case", "art-case-2"]  # reported separately, not revision candidates (the product marks the intact quote on a page whose numbers moved)


def test_a_sentence_missing_in_the_old_edition_flags_the_second_article_too(fx):
    r = rp.run(fx, [OLD_PAGE1, "この版には日程の記載がありません。"], PREFIX)
    assert r["all_checks_pass"], [k for k, v in r["checks"].items() if not v]
    assert r["oracle"]["evidence_changed"] == ["EV-case-1", "EV-case-2"] == r["impact"]["evidence_flagged_republish"]
    assert r["impact"]["articles_flagged"] == ["art-case", "art-case-2"] == r["oracle"]["articles_by_text"]
    assert r["impact"]["articles_not_flagged"] == ["art-caseB"] and len(r["impact"]["recorded_impacts"]) == 2


def test_identical_text_is_refused_as_not_a_pair(fx):
    with closing(sqlite3.connect(fx)) as db:
        pages = [t for (t,) in db.execute("SELECT text FROM source_pages WHERE source_sha256=? ORDER BY page", (SHA_A,))]
    before = _sha(fx)
    with pytest.raises(SystemExit):
        rp.run(fx, pages, PREFIX, old_sha="d" * 64)  # a re-issue with the same text: no new revision to register
    assert _sha(fx) == before


def test_the_series_is_two_real_editions_and_the_old_rows_do_not_change(tmp_path):
    path = build_fixture(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        before = rp.table_digests(db, skip=rp.SERIES_TABLES)
    r = rp.run(path, [OLD_PAGE1, DATE], PREFIX)
    with closing(sqlite3.connect(path)) as db:
        after = rp.table_digests(db, skip=rp.SERIES_TABLES)
        title, text2 = db.execute("SELECT document_title, content_text FROM source_document_series_editions WHERE rev_number=2").fetchone()
        assert db.execute("SELECT count(*) FROM source_document_series_editions").fetchone()[0] == 2
    assert before == after and r["old_tables"]["unchanged"] and "SIMULATED" not in title and "REAL EDITIONS" in title
    assert text2.split(rp.PAGE_SEP)[1] == DATE and [e["rev"] for e in r["editions"]] == [1, 2]
    assert len(r["guards"]) == 7 and all(g["refused"] and g["message"].startswith("G-06 VIOLATION") for g in r["guards"])


def test_excerpts_never_exceed_the_limit(fx):
    r = rp.run(fx, [OLD_PAGE1, DATE], PREFIX)
    pieces = [c[k] for c in r["real_changes"] for k in ("old_excerpt", "new_excerpt")] + [c[k] for c in r["diff_changes"] for k in ("old_excerpt", "new_excerpt")]
    assert pieces and all(len(x or "") <= rp.EXCERPT for x in pieces)


def test_unmigrated_database_wrong_prefix_and_same_hash_are_refused_without_a_write(tmp_path):
    path = build_fixture(tmp_path, migrate=False)
    before = _sha(path)
    with pytest.raises(SystemExit):
        rp.run(path, [OLD_PAGE1, DATE], PREFIX)
    assert _sha(path) == before
    (tmp_path / "m").mkdir()
    path2 = build_fixture(tmp_path / "m", migrate=True)
    b2 = _sha(path2)
    with pytest.raises(SystemExit):
        rp.run(path2, [OLD_PAGE1, DATE], "ffffffff")  # no such stored source
    with pytest.raises(SystemExit):
        rp.run(path2, [OLD_PAGE1, DATE], PREFIX, old_sha=SHA_A)  # same hash as the new edition: not a pair
    with pytest.raises(SystemExit):
        rp.run(path2, [], PREFIX)
    assert _sha(path2) == b2


def _cli(*args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, env=e)


def test_cli_prints_utf8_json_even_under_an_ascii_console_and_exits_zero(fx, tmp_path):
    pj = tmp_path / "old.json"
    pj.write_text(json.dumps([OLD_PAGE1, DATE], ensure_ascii=False), encoding="utf-8")
    p = _cli(fx, "--old-pages-json", pj, "--new-sha-prefix", PREFIX, env={"PYTHONIOENCODING": "ascii"})
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    out = json.loads(p.stdout.decode("utf-8"))
    assert out["all_checks_pass"] and "試験" in json.dumps(out["real_changes"], ensure_ascii=False) or out["real_changes"][0]["old_excerpt"]
    assert "募集人員" in p.stdout.decode("utf-8") or "名" in p.stdout.decode("utf-8")  # Japanese survives as UTF-8, not as \\u escapes
    assert out["old_edition"]["file_sha256"] and out["old_edition"]["pages"] == 2


def test_cli_argument_handling(fx, tmp_path):
    pj = tmp_path / "old.json"
    pj.write_text("[\"x\"]", encoding="utf-8")
    assert _cli(fx).returncode == 2  # neither a PDF nor --old-pages-json
    assert _cli(fx, tmp_path / "nope.pdf").returncode == 2  # PDF does not exist
    assert _cli(tmp_path / "nope.sqlite", "--old-pages-json", pj).returncode == 2  # database does not exist
    assert _cli(fx, tmp_path / "a.pdf", "--old-pages-json", pj).returncode == 2  # both given
    assert _cli().returncode == 2
