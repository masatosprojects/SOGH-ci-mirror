"""Issue #36: the whole view is checked on its own — a legitimate reuse of an id is told from a collision.

Synthetic data (an invented 〇〇大学). Every negative case changes ONE thing of an otherwise correct view.
"""
import copy
import json
from pathlib import Path

import pytest

from src.regression import fullview as fv
from src.regression.checks import Thresholds
from tests.test_regression_harness import make_export, write_inbox

# synthetic drafts are too small for the detection RATES to mean anything; the rates are gated on the real data
LOOSE = Thresholds(body_detection_min=0.0, citation_id_detection_min=0.0, citation_swap_detection_min=0.0)

PRIORS = {"old/claude-compatible-export.json": make_export("A")}


def view_of(*exports, extra=None):
    view = {"evidence": {}, "articles": []}
    for e in exports:
        view["evidence"].update(copy.deepcopy(e["evidence"]))
        view["articles"] += copy.deepcopy(e["articles"])
    if extra:
        view["articles"] += extra
    return view


def check(view, priors=None):
    return fv.check_view("current/active-state.json", view, priors if priors is not None else PRIORS, LOOSE)


def quick(view, priors=None):
    """Only the id / history checks (no QA sweeps): fast, for the cases that are about ids."""
    priors = priors if priors is not None else PRIORS
    reuse, history = fv.evidence_reuse(view, priors), fv.article_history(view, priors)
    return {"evidence_reuse": reuse, "article_history": history,
            "failures": [f"{c['evidence_id']}: {c['differs']}" for c in reuse["collisions"]] + history["failures"],
            "warnings": history["notices"], "ok": not reuse["collisions"] and not history["failures"]}


def revision_of(article, text_suffix=" なお、詳しい日程は公式サイトをご覧ください。", **over):
    base_id = article["article_id"]
    h = "0123456789abcdef"
    rev = {"article_id": f"{base_id}:revision:{h}", "base_article_id": base_id, "parent_article_id": f"{base_id}:revision:fedcba9876543210",
           "revision_hash": h + "f" * 48, "as_of": "2026-11-01", "claim": article["claim"], "publish_allowed": False,
           "text": article["text"].replace("\n\n最新情報", f"{text_suffix}\n\n最新情報"), "evidence_ids": sorted(
               {e for e in __import__("re").findall(r"EV-[A-Za-z0-9_\-]+", article["text"])})}
    rev.update(over)
    return rev


# ------------------------------------------------------------ legitimate reuse

def test_a_view_that_repeats_old_ids_with_identical_content_is_fine_and_counted():
    r = check(view_of(PRIORS["old/claude-compatible-export.json"], make_export("B")))
    assert r["ok"], r["failures"]
    assert r["evidence_reuse"]["reused"] == 2 and r["evidence_reuse"]["new"] == 2 and r["evidence_reuse"]["collisions"] == []
    assert r["article_history"]["same_text"] == 1 and r["article_history"]["new"] == 1


def test_a_new_retrieval_date_alone_is_not_a_collision_but_is_listed():
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["evidence"]["EV-A-Q"]["retrieved_at"] = "2026-11-02"
    r = quick(view)
    assert r["ok"] and r["evidence_reuse"]["retrieved_at_differs"] == ["EV-A-Q"]


# ------------------------------------------------------------ collisions: same id, different meaning

@pytest.mark.parametrize("field,value", [
    ("value", {"count": 151, "unit": "名"}),
    ("fiscal_year", 2026),
    ("admission_method", "一般選抜"),
    ("faculty", "文学部"),
    ("university", "△△大学"),
    ("source_url", "https://example.ac.jp/other.pdf"),
    ("source_pdf_sha256", "b" * 64),
    ("fact_key", "interview"),
    ("scope", "faculty_annual_AO_aggregate"),
])
def test_the_same_evidence_id_with_a_different_meaning_is_a_collision(field, value):
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["evidence"]["EV-A-Q"][field] = value
    r = quick(view)
    assert not r["ok"]
    assert any(c["evidence_id"] == "EV-A-Q" for c in r["evidence_reuse"]["collisions"]), field


def test_the_same_evidence_id_at_another_quote_position_is_a_collision():
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["evidence"]["EV-A-Q"]["proofs"] = [{"page": 9, "quote": "募集人員は150名です。"}]
    assert "proofs" in quick(view)["evidence_reuse"]["collisions"][0]["differs"]
    view["evidence"]["EV-A-Q"]["proofs"] = [{"page": 2, "quote": "募集人員は160名です。"}]
    assert "proofs" in quick(view)["evidence_reuse"]["collisions"][0]["differs"]


def test_a_collision_against_any_of_several_priors_is_found():
    other = make_export("A")
    other["evidence"]["EV-A-Q"]["value"] = {"count": 99, "unit": "名"}
    priors = {**PRIORS, "other/claude-compatible-export.json": other}
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"]), priors)
    assert [c["against"] for c in r["evidence_reuse"]["collisions"]] == ["other/claude-compatible-export.json"]


# ------------------------------------------------------------ articles and their revisions

def test_the_same_article_id_with_a_different_text_is_a_failure():
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["articles"][0]["text"] = view["articles"][0]["text"].replace("30分程度", "30分程度（変更）")
    r = quick(view)
    assert not r["ok"] and any("its text differs" in f for f in r["article_history"]["failures"])


def test_a_proper_revision_is_a_legitimate_update():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    view = view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base)])
    r = check(view)
    assert r["ok"], r["failures"]
    assert r["article_history"]["revisions"] == 1 and r["article_history"]["same_text"] == 1


def test_revision_that_is_identical_to_its_base_is_not_a_revision():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base, text_suffix="")]))
    assert any("identical to its base" in f for f in r["failures"])


def test_revision_whose_id_hash_does_not_match_is_a_failure():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base, revision_hash="9" * 64)]))
    assert any("revision hash" in f for f in r["failures"])


def test_revision_without_as_of_or_with_a_wrong_base_is_a_failure():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base, as_of=None)]))
    assert any("no as_of" in f for f in r["failures"])
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base, base_article_id="something-else")]))
    assert any("not the base" in f for f in r["failures"])


def test_revision_whose_base_is_unknown_is_reported_not_silently_accepted():
    base = copy.deepcopy(PRIORS["old/claude-compatible-export.json"]["articles"][0])
    rev = revision_of(base)
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["articles"] = [rev]  # the base article is in neither the view nor any prior
    r = quick(view, priors={})
    assert r["ok"] and any("is in no delivery here" in w for w in r["warnings"])


def test_citing_evidence_the_article_does_not_list_or_the_view_lacks_is_a_failure():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    r = quick(view_of(PRIORS["old/claude-compatible-export.json"], extra=[revision_of(base, evidence_ids=["EV-A-Q"])]))
    assert any("does not list" in f for f in r["failures"])
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    del view["evidence"]["EV-A-I"]
    assert any("does not contain" in f for f in quick(view)["failures"])


def test_publish_allowed_true_is_warned_about():
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["articles"][0]["publish_allowed"] = True
    r = quick(view)
    assert any("never approves publication" in w for w in r["warnings"])


# ------------------------------------------------------------ the whole view goes through the whole QA

def test_a_wrong_number_in_the_view_fails_the_view():
    view = view_of(PRIORS["old/claude-compatible-export.json"])
    view["articles"][0]["text"] = view["articles"][0]["text"].replace("150名", "999名")
    r = check(view)
    assert not r["ok"] and r["checks"]["article_qa_and_mutations"] == "failed"


def test_a_revision_with_a_wrong_number_fails_even_though_revisions_are_legitimate():
    base = PRIORS["old/claude-compatible-export.json"]["articles"][0]
    rev = revision_of(base)
    rev["text"] = rev["text"].replace("150名", "151名")
    assert not check(view_of(PRIORS["old/claude-compatible-export.json"], extra=[rev]))["ok"]


# ------------------------------------------------------------ what the report says it did not do

def test_original_source_comparison_is_not_run_and_never_counted_as_passed():
    r = check(view_of(PRIORS["old/claude-compatible-export.json"]))
    assert r["checks"]["original_source_comparison"] == "not_run" and r["counts"]["not_run"] == 2
    assert r["counts"]["passed"] + r["counts"]["failed"] + r["counts"]["not_run"] == len(r["checks"])


def test_the_report_never_approves_publication(tmp_path: Path):
    inbox = write_inbox(tmp_path, {"old/claude-compatible-export.json": PRIORS["old/claude-compatible-export.json"],
                                   "old/samples/current/active-state.json": view_of(PRIORS["old/claude-compatible-export.json"])})
    report = fv.build_report(inbox)
    assert report["publication_approved"] is False and report["ci_success_is_publication_approval"] is False
    assert report["original_source_check"]["status"] == "not_run"
    text = fv.render_markdown(report)
    assert "not_run" in text and "公開承認ではない" in text


# ------------------------------------------------------------ discovery and CLI

def test_views_are_found_by_name_and_deliveries_never_are(tmp_path: Path):
    export = PRIORS["old/claude-compatible-export.json"]
    inbox = write_inbox(tmp_path, {"h/claude-compatible-export.json": export, "h/samples/current/active-state.json": view_of(export),
                                   "h/other/full-view-2.json": view_of(export), "h/notes/active-state-notes.json": {"hello": 1}})
    assert [p.name for p in fv.find_views(inbox)] == ["full-view-2.json", "active-state.json"] or \
        sorted(p.name for p in fv.find_views(inbox)) == ["active-state.json", "full-view-2.json"]


def test_a_view_is_not_its_own_prior(tmp_path: Path):
    export = PRIORS["old/claude-compatible-export.json"]
    inbox = write_inbox(tmp_path, {"h/samples/current/active-state.json": view_of(export)})
    report = fv.build_report(inbox)
    assert report["verdict"]["ok"] and report["priors"] == []


def test_cli_exit_codes(tmp_path: Path, capsys):
    export = PRIORS["old/claude-compatible-export.json"]
    good = write_inbox(tmp_path / "good", {"h/claude-compatible-export.json": export, "h/samples/active-state.json": view_of(export)})
    assert fv.main(["--inbox", str(good), "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "fullview.json").exists() and (tmp_path / "out" / "fullview.md").exists()
    broken = copy.deepcopy(view_of(export))
    broken["evidence"]["EV-A-Q"]["fiscal_year"] = 2020
    bad = write_inbox(tmp_path / "bad", {"h/claude-compatible-export.json": export, "h/samples/active-state.json": broken})
    assert fv.main(["--inbox", str(bad)]) == 1
    empty = write_inbox(tmp_path / "empty", {"h/claude-compatible-export.json": export})
    assert fv.main(["--inbox", str(empty)]) == 0 and fv.main(["--inbox", str(empty), "--require-view"]) == 1


def test_github_summary_is_written(tmp_path: Path, monkeypatch):
    export = PRIORS["old/claude-compatible-export.json"]
    inbox = write_inbox(tmp_path, {"h/claude-compatible-export.json": export, "h/active-state.json": view_of(export)})
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert fv.main(["--inbox", str(inbox), "--github-summary"]) == 0
    assert "全体ビュー検査" in summary.read_text(encoding="utf-8")


# ------------------------------------------------------------ the real deliveries

def test_the_union_of_the_real_deliveries_is_a_clean_view_of_pure_reuse():
    """Every real delivery together, as one view, is exactly the legitimate-reuse case: no collision, no failure."""
    from src.regression.handoffs import find_exports
    refs = find_exports()
    assert refs
    exports = {ref.key: ref.load() for ref in refs}
    view = view_of(*exports.values())
    r = fv.check_view("union", view, exports)
    assert r["ok"], r["failures"]
    assert r["evidence_reuse"]["new"] == 0 and r["evidence_reuse"]["reused"] == len(view["evidence"])
    assert r["article_history"]["same_text"] == len(view["articles"])


def test_a_real_evidence_id_changed_in_the_union_is_a_collision():
    from src.regression.handoffs import find_exports
    exports = {ref.key: ref.load() for ref in find_exports()}
    view = view_of(*exports.values())
    eid = next(iter(view["evidence"]))
    view["evidence"][eid]["fiscal_year"] = int(view["evidence"][eid]["fiscal_year"]) - 1
    assert any(c["evidence_id"] == eid for c in fv.evidence_reuse(view, exports)["collisions"])


def test_base_state_is_used_to_find_what_a_revision_changed_but_never_for_id_reuse():
    export = PRIORS["old/claude-compatible-export.json"]
    base_article = copy.deepcopy(export["articles"][0])
    rev = revision_of(base_article)
    view = view_of(export)
    view["articles"] = [rev]
    bases = {"samples/current/base-state.json": {"evidence": {}, "articles": [base_article]}}
    assert any("is in no delivery here" in n for n in fv.article_history(view, {}, None)["notices"])
    h = fv.article_history(view, {}, bases)
    assert h["failures"] == [] and h["notices"] == []
    identical = revision_of(base_article, text_suffix="")
    view["articles"] = [identical]
    assert any("identical to its base" in f for f in fv.article_history(view, {}, bases)["failures"])
    # a base state with a CHANGED evidence record is not a prior for the id check
    bases["samples/current/base-state.json"]["evidence"] = {"EV-A-Q": {**export["evidence"]["EV-A-Q"], "fiscal_year": 2000}}
    assert fv.evidence_reuse(view_of(export), {})["collisions"] == []


def test_find_base_states(tmp_path: Path):
    export = PRIORS["old/claude-compatible-export.json"]
    inbox = write_inbox(tmp_path, {"h/samples/current/base-state.json": view_of(export), "h/samples/current/active-state.json": view_of(export)})
    assert list(fv.find_base_states(inbox)) == ["h/samples/current/base-state.json"]


# ------------------------------------------------------------ the same fact under two evidence ids (G-05)
def test_the_same_fact_under_a_new_id_is_reported_with_an_alias_proposal_not_failed():
    old = PRIORS["old/claude-compatible-export.json"]
    view = view_of(old)
    twin = copy.deepcopy(old["evidence"]["EV-A-Q"])
    twin["evidence_id"] = "EV-A2-Q"  # the same fact re-extracted under another profile code
    view["evidence"]["EV-A2-Q"] = twin
    ident = fv.evidence_identity(view, PRIORS)
    assert len(ident["groups"]) == 1 and ident["groups"][0]["kinds"] == ["duplicate"] and not ident["conflicts"]
    assert ident["alias_proposal"] == {"EV-A2-Q": "EV-A-Q"}  # the id the delivery already uses is kept


def test_two_different_statements_about_the_same_place_fail_the_view():
    old = PRIORS["old/claude-compatible-export.json"]
    view = view_of(old)
    twin = copy.deepcopy(old["evidence"]["EV-A-Q"])
    twin["evidence_id"] = "EV-A2-Q"
    twin["value"] = {"count": 151, "unit": "名"}
    view["evidence"]["EV-A2-Q"] = twin
    ident = fv.evidence_identity(view, PRIORS)
    assert ident["conflicts"] and ident["alias_proposal"] == {}
    reuse, history = fv.evidence_reuse(view, PRIORS), fv.article_history(view, PRIORS)
    assert not reuse["collisions"] and not history["failures"]  # the id-reuse check does not see it: the identity check does


def test_the_real_whole_view_reports_the_duplicate_facts_as_a_warning_only():
    """The view holds EV-G27-02..06 (the quota EV-G27-01 was replaced by a revision, so it is not in the view): five duplicates against the
    EV-G27C-* export. The sixth (EV-G27-01 in the base state) is in docs/DB_SCHEMA_GAP_ANALYSIS.md and tests/test_evidence_identity.py."""
    from src.regression.handoffs import find_exports
    exports = {ref.key: ref.load() for ref in find_exports()}
    view = json.loads(fv.find_views()[0].read_text(encoding="utf-8"))
    ident = fv.evidence_identity(view, exports)
    assert len(ident["groups"]) == 5 and not ident["conflicts"] and len(ident["alias_proposal"]) == 5
