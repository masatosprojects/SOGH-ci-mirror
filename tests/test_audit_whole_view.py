"""Issue #48: a handoff that delivers a manifest + a WHOLE VIEW (and no differential export) is audited, not skipped.

`skipped` is never turned into `passed`: what could not be run (original PDFs / HTML) stays `skipped` / `not_run`.
Synthetic deliveries (an invented 〇〇大学) in a temporary inbox; each negative case changes one thing.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.integration import audit_handoff as ah
from src.regression import fullview as fv
from tests.test_regression_harness import make_export

OLD = make_export("A")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def write_manifest(root: Path) -> None:
    files = [{"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
             for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    write_json(root / "manifest.json", {"files": files})


def view_of(*exports):
    view = {"evidence": {}, "articles": []}
    for e in exports:
        view["evidence"].update(copy.deepcopy(e["evidence"]))
        view["articles"] += copy.deepcopy(e["articles"])
    return view


def build(tmp_path: Path, view, *, old=True, manifest=True, name="samples/current/active-state.json") -> Path:
    inbox = tmp_path / "inbox"
    if old:
        write_json(inbox / "h-old" / "samples" / "claude-compatible-export.json", OLD)
    new = inbox / "h-new"
    write_json(new / name, view)
    (new / "README.md").write_text("handoff", encoding="utf-8")
    if manifest:
        write_manifest(new)
    return new


def audit(root: Path):
    return ah.audit(root)


def test_a_valid_whole_view_is_audited_and_what_could_not_run_stays_skipped(tmp_path):
    report = audit(build(tmp_path, view_of(OLD)))
    s = report["summary"]
    assert s["failed"] == [] and s["views_checked"] == ["samples/current/active-state.json"] and s["exports_checked"] == []
    assert report["export"]["status"] == "pass" and report["manifest"]["status"] == "pass"
    view = report["export"]["whole_views"]["samples/current/active-state.json"]
    assert view["evidence_reuse"]["reused"] == 2 and view["evidence_reuse"]["collisions"] == [] and view["article_history"]["same_text"] == 1
    assert view["original_source_comparison"] == "not_run"
    assert report["source_pdfs"]["status"] == "skipped"  # no --pdf-dir: the originals were NOT checked, and it says so
    assert "database" in s["skipped"] and "source_pdfs" in s["skipped"]


def test_no_export_and_no_view_is_still_skipped_not_passed(tmp_path):
    root = tmp_path / "inbox" / "h"
    write_json(root / "notes.json", {"hello": 1})
    write_manifest(root)
    report = audit(root)
    assert report["export"]["status"] == "skipped" and "whole view" in report["export"]["reason"]
    assert report["summary"]["views_checked"] == []


def test_a_work_report_with_a_view_like_name_is_not_mistaken_for_a_view(tmp_path):
    new = build(tmp_path, view_of(OLD))
    write_json(new / "qa" / "full-view-final.json", {"passed": 5, "failed": 0})
    write_manifest(new)
    s = audit(new)["summary"]
    assert s["views_checked"] == ["samples/current/active-state.json"] and s["failed"] == []


@pytest.mark.parametrize("broken", [
    {"evidence": [], "articles": []},
    {"evidence": {"EV-A-Q": {"evidence_id": "EV-A-Q"}}, "articles": "nope"},
    {"evidence": {"EV-X": {"evidence_id": "EV-OTHER"}}, "articles": [{"article_id": "a", "text": "t", "claim": {}}]},
    {"evidence": {"EV-A-Q": OLD["evidence"]["EV-A-Q"]}, "articles": [{"article_id": "a", "text": "t"}]},
    ["not", "an", "object"],
])
def test_a_malformed_whole_view_fails(tmp_path, broken):
    report = audit(build(tmp_path, broken))
    assert "export" in report["summary"]["failed"]


def test_a_canonical_view_that_is_not_json_fails_instead_of_vanishing(tmp_path):
    new = build(tmp_path, view_of(OLD))
    (new / "samples" / "current" / "active-state.json").write_text("{ not json", encoding="utf-8")
    write_manifest(new)
    assert "export" in audit(new)["summary"]["failed"]


def test_a_tampered_file_fails_the_manifest(tmp_path):
    new = build(tmp_path, view_of(OLD))
    path = new / "samples" / "current" / "active-state.json"
    changed = view_of(OLD)
    changed["articles"][0]["text"] += "\n改ざん"
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    report = audit(new)
    assert report["manifest"]["status"] == "fail" and "manifest" in report["summary"]["failed"]


def test_a_file_missing_from_the_manifest_fails(tmp_path):
    new = build(tmp_path, view_of(OLD))
    (new / "extra.json").write_text("{}", encoding="utf-8")
    assert "manifest" in audit(new)["summary"]["failed"]


def test_a_citation_that_exists_nowhere_fails(tmp_path):
    view = view_of(OLD)
    view["articles"][0]["text"] = view["articles"][0]["text"].replace("[EV-A-I]", "[EV-NOWHERE]")
    report = audit(build(tmp_path, view))
    assert report["export"]["status"] == "fail"
    assert any("does not contain" in f for f in report["export"]["whole_views"]["samples/current/active-state.json"]["failures"])


@pytest.mark.parametrize("field,value", [("fiscal_year", 2026), ("admission_method", "一般選抜"), ("value", {"count": 151, "unit": "名"}),
                                         ("source_pdf_sha256", "b" * 64)])
def test_an_evidence_id_reused_for_something_else_is_a_collision(tmp_path, field, value):
    view = view_of(OLD)
    view["evidence"]["EV-A-Q"][field] = value
    report = audit(build(tmp_path, view))
    v = report["export"]["whole_views"]["samples/current/active-state.json"]
    assert report["export"]["status"] == "fail" and v["evidence_reuse"]["collisions"], field


def test_a_different_year_or_method_mixed_into_an_article_fails_the_article_qa(tmp_path):
    view = view_of(OLD)
    view["articles"][0]["claim"] = dict(view["articles"][0]["claim"], fiscal_year=2026)
    assert audit(build(tmp_path, view))["export"]["status"] == "fail"
    view = view_of(OLD)
    view["evidence"]["EV-A-Q"]["admission_method"] = "別方式"
    assert audit(build(tmp_path / "second", view, old=False))["export"]["status"] == "fail"


def test_a_wrong_number_in_an_article_fails(tmp_path):
    view = view_of(OLD)
    view["articles"][0]["text"] = view["articles"][0]["text"].replace("150名", "999名")
    assert audit(build(tmp_path, view))["export"]["status"] == "fail"


def revision(base, **over):
    h = "0123456789abcdef"
    rev = {"article_id": f"{base['article_id']}:revision:{h}", "base_article_id": base["article_id"], "revision_hash": h + "f" * 48,
           "as_of": "2026-11-01", "claim": base["claim"], "publish_allowed": False,
           "text": base["text"].replace("\n\n最新情報", " なお、詳しい日程は公式サイトをご覧ください。\n\n最新情報"),
           "evidence_ids": sorted({"EV-A-Q", "EV-A-I"})}
    rev.update(over)
    return rev


def test_a_proper_revision_passes_and_a_contradictory_history_fails(tmp_path):
    base = OLD["articles"][0]
    good = view_of(OLD)
    good["articles"].append(revision(base))
    assert audit(build(tmp_path / "ok", good))["export"]["status"] == "pass"
    for name, bad in {"hash": revision(base, revision_hash="9" * 64), "identical": revision(base, text=base["text"]),
                      "no_as_of": revision(base, as_of=None), "wrong_base": revision(base, base_article_id="x"),
                      "unlisted_citation": revision(base, evidence_ids=["EV-A-Q"])}.items():
        view = view_of(OLD)
        view["articles"].append(bad)
        report = audit(build(tmp_path / name, view))
        assert report["export"]["status"] == "fail", name


def test_an_old_differential_export_handoff_is_judged_exactly_as_before(tmp_path):
    inbox = tmp_path / "inbox"
    root = inbox / "h-old"
    write_json(root / "samples" / "claude-compatible-export.json", OLD)
    write_manifest(root)
    s = audit(root)["summary"]
    assert s["views_checked"] == [] and s["exports_checked"] == ["samples/claude-compatible-export.json"] and s["failed"] == []
    broken = copy.deepcopy(OLD)
    broken["evidence"]["EV-A-Q"]["value"]["count"] = 151
    write_json(root / "samples" / "claude-compatible-export.json", broken)
    write_manifest(root)
    assert "export" in audit(root)["summary"]["failed"]  # quote 150 vs value 151 is still caught


def test_the_ci_view_check_fails_on_a_malformed_canonical_view_too(tmp_path):
    inbox = tmp_path / "inbox"
    write_json(inbox / "h-old" / "claude-compatible-export.json", OLD)
    write_json(inbox / "h-new" / "active-state.json", {"evidence": [], "articles": []})
    report = fv.build_report(inbox)
    assert not report["verdict"]["ok"] and any("malformed view" in r for r in report["verdict"]["reasons"])
    assert "malformed view" in fv.render_markdown(report)
    (inbox / "h-new" / "active-state.json").write_text("not json", encoding="utf-8")
    assert any("unreadable view" in r for r in fv.build_report(inbox)["verdict"]["reasons"])


def test_view_shape_problems_are_specific():
    assert fv.view_shape_problems(view_of(OLD)) == []
    assert fv.view_shape_problems([]) == ["the view is not an object"]
    dup = view_of(OLD)
    dup["articles"].append(copy.deepcopy(dup["articles"][0]))
    assert any("duplicate article_id" in p for p in fv.view_shape_problems(dup))
