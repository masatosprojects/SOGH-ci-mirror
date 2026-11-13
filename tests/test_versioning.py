"""Versioning: snapshots, diffs, and the facts/articles a new edition affects.
All data is synthetic (〇〇大学)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.versioning import impact
from src.versioning.diff import diff_snapshots
from src.versioning.snapshot import (
    SnapshotError,
    SourceSnapshot,
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
    snapshot_from_evidence,
)

REPO_ROOT = Path(__file__).parent.parent
OLD_SHA, NEW_SHA = "a" * 64, "b" * 64
URL = "https://example.ac.jp/youkou.pdf"

PAGES = [
    "表紙 〇〇大学 2027年度入学 募集要項。",
    "募集人員は5名です。ただし、募集人員どおりに合格者を決定しない場合があります。",
    "出願期間は令和8年8月6日9:00から9月2日9:00までです。郵送は9月1日から9月3日必着です。",
    "面接・口述試験は個別に30分程度行います。必要に応じ試験時間を延長する場合があります。",
]


def snap(pages, sha=NEW_SHA, url=URL, **kw):
    return SourceSnapshot("univ-2027", url, sha, "2026-11-01", pages, **kw)


def ev(eid, quote, page, key="quota", sha=OLD_SHA, url=URL):
    return {"evidence_id": eid, "fact_key": key, "source_pdf_sha256": sha, "source_url": url,
            "proofs": [{"page": page, "quote": quote}]}


EXPORT = {
    "evidence": {
        "EV-1": ev("EV-1", "募集人員は5名です。", 2),
        "EV-2": ev("EV-2", "出願期間は令和8年8月6日9:00から9月2日9:00までです。", 3, "online_period"),
        "EV-3": ev("EV-3", "個別に30分程度行います。", 4, "interview"),
    },
    "articles": [
        {"article_id": "A1", "text": "募集人員は5名[EV-1]です。出願期間は8月6日から[EV-2]。"},
        {"article_id": "A2", "text": "面接は30分程度[EV-3]です。"},
    ],
}


def run(new_pages, **kw):
    return impact.assess_export(EXPORT, [snap(new_pages, **kw)])


def with_page(i, text):
    pages = list(PAGES)
    pages[i] = text
    return pages


# ---------------------------------------------------------------- snapshot

def test_snapshot_roundtrip_and_validation(tmp_path: Path):
    s = snap(PAGES, supersedes=[OLD_SHA], edition_note="訂正版")
    save_snapshot(s, tmp_path / "s.json")
    assert load_snapshot(tmp_path / "s.json") == s
    for bad, expect in [
        ({"url": "u"}, "missing"),
        ({**s.to_dict(), "sha256": "short"}, "sha256"),
        ({**s.to_dict(), "retrieved_at": "yesterday"}, "ISO date"),
        ({**s.to_dict(), "pages": "text"}, "pages"),
        ({**s.to_dict(), "schema_version": 99}, "schema_version"),
    ]:
        with pytest.raises(SnapshotError, match=expect):
            snapshot_from_dict(bad)


def test_snapshot_from_evidence_puts_quotes_on_their_pages():
    s = snapshot_from_evidence(EXPORT["evidence"], OLD_SHA, "univ-2027", "2026-11-01")
    assert len(s.pages) == 4 and "募集人員は5名です。" in s.pages[1] and s.pages[0] == ""
    with pytest.raises(SnapshotError):
        snapshot_from_evidence(EXPORT["evidence"], "c" * 64, "x", "2026-11-01")


# -------------------------------------------------------------------- diff

def test_identical_editions_have_no_changes():
    d = diff_snapshots(snap(PAGES, OLD_SHA), snap(PAGES, OLD_SHA))
    assert d.same_edition and d.identical_text and not d.changes


def test_inserted_page_is_a_move_not_a_change_of_every_later_page():
    d = diff_snapshots(snap(PAGES, OLD_SHA), snap(["目次"] + PAGES))
    assert d.pages_added == [1] and not d.pages_removed and not d.changes
    assert [(m.old_page, m.new_page) for m in d.page_map if m.moved] == [(1, 2), (2, 3), (3, 4), (4, 5)]
    assert not d.identical_text


def test_changed_number_is_flagged_as_a_value_change():
    d = diff_snapshots(snap(PAGES, OLD_SHA), snap(with_page(1, PAGES[1].replace("5名", "6名"))))
    assert len(d.changes) == 1 and d.changes[0].value_change
    assert d.changes[0].old_values == ["number:5", "persons:5"] and d.changes[0].new_values == ["number:6", "persons:6"]
    assert (d.changes[0].old_page, d.changes[0].new_page) == (2, 2)


def test_a_bare_number_in_a_table_cell_with_no_unit_is_still_a_value_change():
    old = snap(["募集人員 知識情報・図書館学類 5 体育専門学群 8"], OLD_SHA)
    new = snap(["募集人員 知識情報・図書館学類 6 体育専門学群 8"])
    d = diff_snapshots(old, new)
    assert d.value_changes and d.value_changes[0].old_values == ["number:5"] and d.value_changes[0].new_values == ["number:6"]


def test_reworded_text_is_not_a_value_change():
    d = diff_snapshots(snap(PAGES, OLD_SHA), snap(with_page(3, PAGES[3].replace("行います", "実施します"))))
    assert d.changes and not d.value_changes


def test_removed_and_added_pages():
    d = diff_snapshots(snap(PAGES, OLD_SHA), snap(PAGES[:3] + ["全く別の内容の新しいページです。申込書の様式は別添のとおりです。"]))
    assert d.pages_added == [4] and d.pages_removed == [4]


# ------------------------------------------------------------------ impact

def test_unchanged_edition_affects_nothing():
    report = run(PAGES)
    assert {v["status"] for v in report["evidence"].values()} == {"intact"}
    assert report["republish_required"] == [] and impact.exit_code(report) == 0


def test_changed_number_affects_that_fact_and_only_the_articles_citing_it():
    report = run(with_page(1, PAGES[1].replace("5名", "6名")))
    ev1 = report["evidence"]["EV-1"]
    assert ev1["status"] == "value_change"
    assert ev1["proofs"][0]["changes"] == [{"from": "5", "to": "6"}]
    assert report["republish_required"] == ["A1"]
    assert report["articles"]["A2"]["status"] == "ok"
    assert impact.exit_code(report) == 1


def test_changed_date_is_a_value_change():
    report = run(with_page(2, PAGES[2].replace("9月2日9:00", "9月5日9:00")))
    assert report["evidence"]["EV-2"]["status"] == "value_change"
    assert report["evidence"]["EV-2"]["proofs"][0]["changes"] == [{"from": "2", "to": "5"}]


def test_reworded_quote_is_reported_as_reworded():
    report = run(with_page(1, PAGES[1].replace("です。ただし", "となります。ただし")))
    assert report["evidence"]["EV-1"]["status"] == "reworded"
    assert report["articles"]["A1"]["status"] == "republish_required"


def test_removed_clause_is_missing():
    report = run(with_page(1, "試験日程は別表のとおりです。"))
    assert report["evidence"]["EV-1"]["status"] == "missing"
    assert report["republish_required"] == ["A1"]


def test_moved_quote_needs_review_because_articles_print_page_numbers():
    report = run(["目次"] + PAGES)
    assert {v["status"] for v in report["evidence"].values()} == {"moved"}
    assert report["evidence"]["EV-1"]["proofs"][0]["new_pages"] == [3]
    assert report["articles_to_review"] == ["A1", "A2"] and report["republish_required"] == []
    assert impact.exit_code(report) == 1


def test_change_elsewhere_on_the_cited_page_needs_the_old_edition_to_be_seen():
    new_pages = with_page(2, PAGES[2].replace("9月3日必着", "9月4日必着"))
    without_old = impact.assess_export(EXPORT, [snap(new_pages)])
    assert without_old["evidence"]["EV-2"]["status"] == "intact"  # the quote itself did not change
    with_old = impact.assess_export(EXPORT, [snap(new_pages)], [snap(PAGES, OLD_SHA)])
    assert with_old["evidence"]["EV-2"]["status"] == "page_changed"
    assert with_old["articles"]["A1"]["status"] == "review"
    assert with_old["evidence"]["EV-2"]["proofs"][0]["values_changed_on_page"] == [
        "date_noyear:(9, 3)", "date_noyear:(9, 4)", "number:3", "number:4"]  # the postal deadline moved 9/3 -> 9/4


def test_evidence_without_a_current_edition_is_unassessed_not_assumed_fine():
    other = snap(PAGES, url="https://example.ac.jp/other.pdf")
    report = impact.assess_export(EXPORT, [other])
    assert set(report["unassessed_evidence"]) == {"EV-1", "EV-2", "EV-3"}
    assert report["articles_unassessed"] == ["A1", "A2"]
    assert impact.exit_code(report) == 0 and impact.exit_code(report, require_all_assessed=True) == 2


def test_new_edition_under_a_new_url_is_matched_through_supersedes():
    moved_url = snap(with_page(1, PAGES[1].replace("5名", "7名")), url="https://example.ac.jp/v2.pdf", supersedes=[OLD_SHA])
    report = impact.assess_export(EXPORT, [moved_url])
    assert report["evidence"]["EV-1"]["status"] == "value_change"
    assert report["evidence"]["EV-1"]["source_url_changed"]["to"] == "https://example.ac.jp/v2.pdf"


def test_same_sha_but_quote_absent_is_an_inconsistency_not_a_pass():
    report = impact.assess_export(EXPORT, [snap(with_page(1, "別の本文です。"), sha=OLD_SHA)])
    assert report["evidence"]["EV-1"]["status"] == "missing"
    assert "evidence and source disagree" in report["evidence"]["EV-1"]["proofs"][0]["note"]


def test_evidence_with_no_quote_cannot_be_assessed():
    export = {"evidence": {"EV-9": {"evidence_id": "EV-9", "source_pdf_sha256": OLD_SHA, "source_url": URL}}, "articles": []}
    report = impact.assess_export(export, [snap(PAGES)])
    assert report["evidence"]["EV-9"]["status"] == "unassessed"


def test_unknown_citation_in_an_article_is_unassessed():
    export = {**EXPORT, "articles": [{"article_id": "A9", "text": "定員5名[EV-404]です。"}]}
    assert impact.assess_export(export, [snap(PAGES)])["articles"]["A9"]["status"] == "unassessed"


def test_a_digit_free_quote_that_vanishes_is_missing_or_reworded_never_intact():
    export = {"evidence": {"EV-7": ev("EV-7", "共通テストの受験は必要としません。", 1, "common_test")}, "articles": []}
    assert impact.assess_export(export, [snap(["表紙です。"])])["evidence"]["EV-7"]["status"] == "missing"


# --------------------------------------------------------------------- CLI

def _cli(*args):
    return subprocess.run([sys.executable, "-X", "utf8", "-m", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


def test_cli_diff_and_impact_exit_codes(tmp_path: Path):
    old, same, changed = tmp_path / "old.json", tmp_path / "same.json", tmp_path / "new.json"
    save_snapshot(snap(PAGES, OLD_SHA), old)
    save_snapshot(snap(PAGES, OLD_SHA), same)
    save_snapshot(snap(with_page(1, PAGES[1].replace("5名", "6名"))), changed)
    export = tmp_path / "export.json"
    export.write_text(json.dumps(EXPORT, ensure_ascii=False), encoding="utf-8")

    assert _cli("src.versioning.diff", "--old", str(old), "--new", str(same)).returncode == 0
    r = _cli("src.versioning.diff", "--old", str(old), "--new", str(changed))
    assert r.returncode == 1 and json.loads(r.stdout)["summary"]["value_changes"] == 1

    assert _cli("src.versioning.impact", "--export", str(export), "--new", str(same)).returncode == 0
    out = tmp_path / "report.json"
    r = _cli("src.versioning.impact", "--export", str(export), "--new", str(changed), "--json-out", str(out))
    assert r.returncode == 1
    assert json.loads(out.read_text(encoding="utf-8"))["republish_required"] == ["A1"]
