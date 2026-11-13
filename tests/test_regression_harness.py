"""The regression harness itself (src/regression), on synthetic deliveries.

A "delivery" here is a tiny export for an invented 〇〇大学. The point of these
tests is that the harness DETECTS the problems it exists to detect."""
import copy
import json
from pathlib import Path

import pytest

from src.integration import audit_handoff
from src.regression import report as rr
from src.regression.checks import Thresholds, compare_to_baseline, evaluate_export, evaluate_isolation, golden_view
from src.regression.handoffs import find_exports, find_handoffs

SHA = "a" * 64
URL = "https://example.ac.jp/youkou.pdf"
CAVEAT = "最新情報は大学公式サイトでご確認ください。"


def record(eid, key, value, quote, page=2, scope="target_admission_cycle", sha=SHA):
    return {"evidence_id": eid, "university": "〇〇大学", "faculty": "環境学部", "department": None,
            "admission_method": "夏秋AO入試", "fiscal_year": 2027, "source_url": URL, "source_pdf_sha256": sha,
            "retrieved_at": "2026-11-01", "fact_key": key, "value": value, "scope": scope,
            "proofs": [{"page": page, "quote": quote}]}


SHARED = ("出願の前に、募集要項の原文で出願資格・提出書類・日程を確認し、不明な点は入試担当窓口に問い合わせてください。"
          "提出書類は様式の指定に従い、記入漏れや添付漏れがないかを提出前にもう一度確かめましょう。")


def make_export(prefix="X", sha=SHA):
    quota, interview = f"EV-{prefix}-Q", f"EV-{prefix}-I"
    evidence = {
        quota: record(quota, "quota", {"count": 150, "unit": "名"}, "募集人員は150名です。", 2, sha=sha),
        interview: record(interview, "interview", {"minutes": 30, "type": "individual_interview_and_oral_exam"},
                          "面接は個別に30分程度行います。", 3, sha=sha),
    }
    text = (f"# 〇〇大学 環境学部 夏秋AO入試の概要\n\n作業基準日：2026-11-01。\n\n募集人員は150名[{quota}]です。\n\n"
            f"面接は個別に30分程度[{interview}]行います。\n\n{CAVEAT}\n")
    claim = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}
    return {"evidence": evidence, "articles": [{"article_id": f"{prefix}-art", "text": text, "claim": claim}]}


def write_inbox(tmp_path: Path, exports: dict[str, dict]) -> Path:
    inbox = tmp_path / "inbox"
    for rel, data in exports.items():
        path = inbox / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return inbox


LOOSE = Thresholds(body_detection_min=0.0, citation_id_detection_min=0.0)  # synthetic text is too small to measure rates on


# ------------------------------------------------------------- discovery

def test_new_university_is_found_by_file_name_alone(tmp_path: Path):
    inbox = write_inbox(tmp_path, {
        "work-db-v02/samples/claude-compatible-export.json": make_export("A"),
        "work-national-v2/samples/niigata/claude-compatible-export.json": make_export("B"),
        "work-national-v2/samples/osaka/claude-compatible-export.json": make_export("C"),
        "notes/readme.json": {"x": 1},
    })
    refs = find_exports(inbox)
    assert [r.key for r in refs] == ["work-db-v02/samples/claude-compatible-export.json",
                                     "work-national-v2/samples/niigata/claude-compatible-export.json",
                                     "work-national-v2/samples/osaka/claude-compatible-export.json"]
    assert [p.name for p in find_handoffs(inbox)] == ["work-db-v02", "work-national-v2"]
    assert refs[1].load()["articles"][0]["article_id"] == "B-art"


# ---------------------------------------------------------- one export

def test_a_good_export_passes_every_check():
    result = evaluate_export("x", make_export(), LOOSE)
    assert result["ok"], result["failures"]
    assert result["gate"] == {"ok": 2, "invalid": 0} and result["versioning"]["facts_checked"] == 2


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e["evidence"]["EV-X-Q"].pop("source_url"), "gate"),
    (lambda e: e["evidence"]["EV-X-Q"].update(fact_key="brand_new_key"), "unregistered"),
    (lambda e: e["evidence"]["EV-X-Q"]["value"].update(count="150"), "registry"),
    (lambda e: e["articles"][0].update(text=e["articles"][0]["text"].replace("150名", "999名")), "article"),
    (lambda e: e.update(articles=[]), "no evidence or no articles"),
])
def test_each_kind_of_problem_is_reported(mutate, needle):
    export = copy.deepcopy(make_export())
    mutate(export)
    result = evaluate_export("x", export, LOOSE)
    assert not result["ok"] and any(needle in f for f in result["failures"]), result["failures"]


def test_a_delivery_whose_drafts_have_no_as_of_date_fails_the_harness():
    export = make_export()
    export["articles"][0]["text"] = export["articles"][0]["text"].replace("作業基準日：2026-11-01。\n\n", "")
    result = evaluate_export("x", export, LOOSE)
    assert not result["ok"] and any("as_of_missing" in f for f in result["failures"])


def test_as_of_edits_are_measured_against_the_deliverys_own_date():
    result = evaluate_export("x", make_export(), LOOSE)
    assert result["mutation"]["as_of"] == [3, 3]  # 2026 / 11 / 01 each moved +1: all later than the delivery's own date


def test_the_mutation_thresholds_are_enforced():
    result = evaluate_export("x", make_export(), Thresholds(body_detection_min=1.01, citation_id_detection_min=1.01))
    assert any("mutation: body" in f for f in result["failures"]) and any("citation ids" in f for f in result["failures"])


def test_registry_warnings_are_reported_but_do_not_fail():
    export = make_export()
    export["evidence"]["EV-X-Q"]["value"]["invented_field"] = 1
    result = evaluate_export("x", export, LOOSE)
    assert result["ok"] and any("registry" in w for w in result["warnings"])


# ------------------------------------------------------------ isolation

def test_isolation_passes_for_independent_deliveries():
    result = evaluate_isolation({"a": make_export("A"), "b": make_export("B", sha="b" * 64)})
    assert result["ok"] and result["evidence"] == 4 and result["articles"] == 2


def test_isolation_catches_an_id_collision():
    result = evaluate_isolation({"a": make_export("A"), "b": make_export("A")})
    assert not result["ok"] and any("already used" in f for f in result["failures"])


def test_isolation_catches_a_result_that_depends_on_another_delivery():
    """Article B cites an id that only exists in delivery A: alone it is an unknown
    citation, with A present it resolves. A new delivery must never do that to an old one."""
    b = make_export("B")
    b["articles"][0]["text"] = b["articles"][0]["text"].replace("[EV-B-Q]", "[EV-A-Q]")
    result = evaluate_isolation({"a": make_export("A"), "b": b})
    assert not result["ok"] and any("changes when other exports" in f for f in result["failures"])


def test_near_duplicate_drafts_across_deliveries_are_a_warning_not_a_failure():
    a, b = make_export("A"), make_export("B", sha="b" * 64)
    result = evaluate_isolation({"a": a, "b": b})
    assert result["near_duplicates"] and result["ok"] and any("near-duplicate" in w for w in result["warnings"])


# --------------------------------------------------------------- golden

def test_golden_view_comparison_names_what_changed():
    view = golden_view(evaluate_export("x", make_export(), LOOSE))
    assert compare_to_baseline("x", view, copy.deepcopy(view)) == []
    drifted = copy.deepcopy(view)
    drifted["per_article"]["X-art"] = {"ok": False, "findings": ["quantity_mismatch"], "notices": []}
    drifted["mutation"]["body"] = [1, 9]
    diffs = compare_to_baseline("x", view, drifted)
    assert len(diffs) == 2 and any("per_article" in d for d in diffs) and any("mutation" in d for d in diffs)


def test_baseline_roundtrip_and_schema_guard(tmp_path: Path):
    path = tmp_path / "base.json"
    rr.write_baseline({"b": {"records": 1}, "a": {"records": 2}}, path)
    assert list(rr.load_baseline(path)) == ["a", "b"]
    path.write_text(json.dumps({"schema_version": 99, "exports": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        rr.load_baseline(path)
    assert rr.load_baseline(tmp_path / "missing.json") == {}


# ---------------------------------------------------------------- junit

JUNIT = """<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="5" failures="1" errors="0" skipped="1">
<testcase classname="tests.a" name="test_ok"/><testcase classname="tests.a" name="test_bad"><failure message="boom"/></testcase>
<testcase classname="tests.b" name="test_skipped"><skipped message="needs the data"/></testcase>
<testcase classname="tests.b" name="test_ok2"/><testcase classname="tests.b" name="test_ok3"/></testsuite></testsuites>"""


def test_junit_counts_name_the_skipped_and_failed_tests(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    t = rr.parse_junit(path)
    assert (t["total"], t["passed"], t["failed"], t["errors"], t["skipped"]) == (5, 3, 1, 0, 1)
    assert t["skipped_tests"] == [{"test": "tests.b::test_skipped", "reason": "needs the data"}]
    assert t["failed_tests"] == ["tests.a::test_bad"]


# --------------------------------------------------------------- report

def _clean_junit(tmp_path, skipped=0, failed=0):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuite tests="10" failures="{failed}" errors="0" skipped="{skipped}"></testsuite>', encoding="utf-8")
    return path


def _report(tmp_path, exports, baseline=None, **kw):
    inbox = write_inbox(tmp_path, exports)
    base = tmp_path / "baseline.json"
    if baseline is not None:
        rr.write_baseline(baseline, base)
    return rr.build_report(inbox=inbox, baseline_path=base, thresholds=LOOSE, run_audit=False, generated_at="T", **kw)


def test_report_with_no_baseline_flags_the_new_export_but_passes(tmp_path: Path):
    r = _report(tmp_path, {"h/samples/claude-compatible-export.json": make_export()}, junit=_clean_junit(tmp_path))
    assert r["verdict"]["ok"] and r["baseline"]["new_without_baseline"] == ["h/samples/claude-compatible-export.json"]
    assert "新しい export（要・ベースライン登録）" in rr.render_markdown(r)


def test_report_fails_on_a_skipped_test_when_asked(tmp_path: Path):
    exports = {"h/samples/claude-compatible-export.json": make_export()}
    ok = _report(tmp_path, exports, junit=_clean_junit(tmp_path, skipped=2))
    assert ok["verdict"]["ok"] and ok["tests"]["skipped"] == 2  # counted and shown, not hidden
    strict = _report(tmp_path, exports, junit=_clean_junit(tmp_path, skipped=2), fail_on_skip=True)
    assert not strict["verdict"]["ok"] and any("skipped" in r for r in strict["verdict"]["reasons"])
    assert "**2**" in rr.render_markdown(strict)


def test_cli_exit_codes_and_files(tmp_path: Path):
    inbox = write_inbox(tmp_path, {"h/samples/claude-compatible-export.json": make_export()})
    base = tmp_path / "base.json"
    out = tmp_path / "out"
    common = ["--inbox", str(inbox), "--baseline", str(base), "--out-dir", str(out)]
    assert rr.main([*common, "--update-baseline", "--junit", str(_clean_junit(tmp_path))]) == 0
    assert list(rr.load_baseline(base)) == ["h/samples/claude-compatible-export.json"]
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# 回帰テストの報告")
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["verdict"]["ok"] is True
    skipped = _clean_junit(tmp_path, skipped=1)
    assert rr.main([*common, "--junit", str(skipped)]) == 0  # counted and shown
    assert rr.main([*common, "--junit", str(skipped), "--fail-on-skip"]) == 1  # ... but a skip is not a pass
    assert rr.main([*common, "--junit", str(_clean_junit(tmp_path, failed=1))]) == 1


def test_report_fails_on_test_failures(tmp_path: Path):
    r = _report(tmp_path, {"h/samples/claude-compatible-export.json": make_export()}, junit=_clean_junit(tmp_path, failed=1))
    assert not r["verdict"]["ok"] and any("failed" in x for x in r["verdict"]["reasons"])


def test_a_new_delivery_cannot_silently_change_an_old_ones_golden_results(tmp_path: Path):
    key = "h/samples/claude-compatible-export.json"
    old = make_export()
    baseline = {key: golden_view(evaluate_export(key, old, LOOSE))}
    unchanged = _report(tmp_path, {key: old}, baseline=baseline, junit=_clean_junit(tmp_path))
    assert unchanged["verdict"]["ok"] and unchanged["baseline"]["unchanged"] == [key]
    # a later edit to the old delivery (or to the QA) changes the committed result
    edited = copy.deepcopy(old)
    edited["evidence"]["EV-X-Q"]["value"]["invented_field"] = 1  # -> a registry warning: golden_view changes
    changed = _report(tmp_path, {key: edited}, baseline=baseline, junit=_clean_junit(tmp_path))
    assert not changed["verdict"]["ok"] and changed["baseline"]["changed"]


def test_report_fails_when_a_baselined_delivery_disappears(tmp_path: Path):
    key, gone = "h/samples/claude-compatible-export.json", "old/samples/claude-compatible-export.json"
    baseline = {key: golden_view(evaluate_export(key, make_export(), LOOSE)), gone: {"records": 1}}
    r = _report(tmp_path, {key: make_export()}, baseline=baseline, junit=_clean_junit(tmp_path))
    assert not r["verdict"]["ok"] and any("no longer delivered" in x for x in r["verdict"]["reasons"])


def test_report_fails_when_there_is_nothing_to_check(tmp_path: Path):
    (tmp_path / "inbox").mkdir()
    r = rr.build_report(inbox=tmp_path / "inbox", baseline_path=tmp_path / "b.json", run_audit=False)
    assert not r["verdict"]["ok"] and any("no claude-compatible-export" in x for x in r["verdict"]["reasons"])


# ------------------------------------------------ audit with several exports

def test_audit_checks_every_export_of_a_handoff_and_does_not_skip_them_silently(tmp_path: Path):
    root = tmp_path / "handoff"
    for case in ("niigata", "osaka"):
        p = root / "samples" / case / "claude-compatible-export.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(make_export(case[:3].upper()), ensure_ascii=False), encoding="utf-8")
    report = audit_handoff.audit(root)
    assert report["summary"]["exports_checked"] == ["samples/niigata/claude-compatible-export.json", "samples/osaka/claude-compatible-export.json"]
    assert report["export"]["status"] == "pass" and report["export"]["evidence_records"] == 4
    assert report["values_in_quotes"]["integers_checked"] == 4 and report["values_in_quotes"]["status"] == "pass"
    bad = json.loads((root / "samples" / "osaka" / "claude-compatible-export.json").read_text(encoding="utf-8"))
    bad["evidence"]["EV-OSA-Q"]["fact_key"] = "brand_new_key"
    (root / "samples" / "osaka" / "claude-compatible-export.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert audit_handoff.audit(root)["export"]["status"] == "fail"


def test_audit_reports_skipped_pdf_verification_when_no_pdf_is_present(tmp_path: Path):
    root = tmp_path / "handoff"
    p = root / "samples" / "claude-compatible-export.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(make_export(), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "pdfs").mkdir()
    result = audit_handoff.audit(root, pdf_dir=tmp_path / "pdfs")["source_pdfs"]
    assert result["status"] == "skipped" and "NOT verified" in result["reason"]
