"""Behaviour of the g2 FAQ extraction proposal (patches/g2-faq/work-faq-g2.patch). SELF_TEST; synthetic FAQ page only.

This file is NOT collected by a normal run (its name does not match test_*.py): tests/test_g2_faq_patch.py copies it as test_behaviour_g2_faq.py into a COPY of
Work's pipeline that carries the patch, and runs pytest there (the same pattern as tests/behaviour_work_stage1.py). Nothing is written to Work's directories.

What it pins:
  1 every proof names the IMMEDIATE question of its quote (not the group heading in front of all questions), while quote text and normalized offsets are
    byte-for-byte what the delivered extractor produces;
  2 STR-076: the record carries no case / year / faculty / department; nothing can bind it; the sources of a binding are refused;
  3 the heading guard fails closed (absent / duplicated / undeclared question / two questions in one proof);
  4 the independent source audit catches the old carry-over and every swapped or invented section;
  5 downstream: an UNKNOWN-scope record cannot be attached to an article or staged into a cycle, and the driver holds it instead of staging it.
"""
import copy
import hashlib
import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

import pytest

from admissions_pipeline.extract import Extracted, normalize
from admissions_pipeline.faq_policy import FIELDS, audit_condition_source, extract_conditions, structured_record, validate_condition_bindings
from admissions_pipeline.headings import immediate_heading
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.supplements import extract_notice
from admissions_pipeline.store import EvidenceStore, canonical

Q0 = "ＡＣ入試の選考で重視されるのはどのようなことですか？"
Q1 = "生成AIを使用した場合は、どこまで下線を引けばよいのでしょうか？"
Q2 = "生成AIで作成した画像（図や表等も含む）はどのようにすればよいでしょうか？"
QX = "国際科学オリンピック特別入試に出願できるのはどのような者ですか？"
CLAUSES = ['文章チェックも含め、生成AIが実際に生成・修正した箇所には、すべて下線を引いてください。',
           'また、その修正によって間接的にでも内容が影響された場合には、影響した箇所すべてに下線を引いてください。',
           'MicrosoftWORD等の文書校正機能による単純な誤字脱字修正の場合は、下線を引く必要はありません。',
           '他人の添削・助言による修正等には、下線を引く必要はありませんが、活動経過報告書での記載は必須です。',
           '画像・図・表等の説明文や脚注に、生成AIで作成したことが分かるように明示してください。']
CASE = "tsukuba-klis-ac-2027"


def page(extra=""):
    return (f"<h3>{Q0}</h3><p>選考では多面的に評価します。</p><h3>{Q1}</h3><p>{CLAUSES[0]}{CLAUSES[1]}</p><p>{CLAUSES[2]}</p><p>{CLAUSES[3]}</p>{extra}"
            f"<h3>{Q2}</h3><p>{CLAUSES[4]}</p><h3>{QX}</h3><p>別方式の説明。</p>")


# STR-101 (H3=B): binding to a cycle needs an INDEPENDENT official evidence (a source other than the FAQ page, with the quote that states the year and the faculty).
SCOPE_EVIDENCE = {"evidence_id": "EV-FIXTURE-REQUIREMENTS", "source_sha256": "e" * 64, "case_id": CASE, "fiscal_year": 2027, "faculty": "知識情報・図書館学類",
                  "quote": "令和9年度（2027年度）アドミッションセンター入試 知識情報・図書館学類 学生募集要項"}


def spec_for(sha, *, unknown):
    spec = {"logical_id": "tsukuba-ac-ai-faq", "fact_key": "generative_ai_policy", "url": "https://fixture.ac.jp/faq", "expected_sha256": sha,
            "published_date": None, "profile_version": "fixture-g2",
            "anchors": [{"page": 1, "pattern": re.escape(normalize(Q1)) + ".*?" + re.escape(normalize(CLAUSES[3]))},
                        {"page": 1, "pattern": re.escape(normalize(Q2)) + ".*?" + re.escape(normalize(CLAUSES[4]))}],
            "value": {"allowed": "表示方法の案内", "not_accepted": ""}, "sentences": ["生成AIの利用を明示します。"], "applicability": "fixture",
            "temporal_status": "fixture", "section_start": Q0, "section_end": QX, "source_role": "faq", "condition_profile": "tsukuba-ac-faq-v1",
            "parent_evidence_id": None}
    if unknown:
        spec.update(scope_status="unknown", university="筑波大学", admission_method="アドミッションセンター入試", section_headings=[Q1, Q2])
    else:
        spec.update(case_id=CASE, fiscal_year=2027, scope_evidence=SCOPE_EVIDENCE)
    return spec


CYCLE = {"case_id": CASE, "university": "筑波大学", "faculty": "情報学群", "department": "知識情報・図書館学類", "admission_method": "アドミッションセンター入試",
         "fiscal_year": 2027, "exam_year": 2026}


@pytest.fixture
def world(tmp_path):
    def make(html):
        path = tmp_path / "faq.html"
        path.write_text(html, encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {"kind": "html", "url": "https://fixture.ac.jp/faq", "local_path": str(path), "sha256": sha, "retrieved_at": "2026-11-01T05:31:11Z"}
        return record, sha
    record, sha = make(page())
    return record, sha, make


def spans(candidate):
    return ([(p["page"], p["quote"], p["normalized_start"], p["normalized_end"]) for p in candidate["proofs"]],
            [(p["page"], p["quote"], p["normalized_start"], p["normalized_end"]) for p in candidate["base_record"]["proofs"]])


# ------------------------------------------------------------------ 1 immediate question, offsets unchanged
def test_every_proof_names_its_own_question_and_nothing_else_moves(world):
    record, sha, _ = world
    new = extract_conditions(record, spec_for(sha, unknown=True), None)
    old = extract_conditions(record, spec_for(sha, unknown=False), copy.deepcopy(CYCLE))  # the delivered (legacy) extractor path
    assert [p["section"] for p in old["proofs"]] == [Q0] * 6 and [p["section"] for p in old["base_record"]["proofs"]] == [Q0] * 2  # the defect
    assert [p["section"] for p in new["proofs"]] == [Q1, Q1, Q1, Q1, Q1, Q2]
    assert [p["section"] for p in new["base_record"]["proofs"]] == [Q1, Q2]
    assert spans(new) == spans(old)  # quotes and normalized offsets are exactly the delivered ones
    assert new["values"] == old["values"] and new["field_proofs"].keys() == old["field_proofs"].keys()
    assert hashlib.sha256(Path(record["local_path"]).read_bytes()).hexdigest() == sha == new["base_record"]["source_sha256"]


# ------------------------------------------------------------------ 2 STR-076: the record is UNKNOWN
def test_str076_record_has_no_case_year_faculty_or_department(world):
    record, sha, _ = world
    cand = extract_conditions(record, spec_for(sha, unknown=True), None)
    base = cand["base_record"]
    assert [base[k] for k in ("case_id", "faculty", "department", "fiscal_year", "published_date")] == [None] * 5
    assert base["scope"] == "general_admission_faq" and base["scope_status"] == "unknown" and base["scope_reverification"] == "required"
    assert base["temporal_status"] == "fixture" and base["publication_allowed"] is False
    assert all(b["applies_to"] is None for b in cand["field_proofs"].values())
    rec = structured_record(cand, None, "fixture-g2")
    validate_condition_bindings(rec)
    assert audit_condition_source(rec, record["local_path"])["status"] == "pass"
    assert rec["case_id"] is None and rec["fiscal_year"] is None and rec["faculty"] is None and rec["department"] is None


@pytest.mark.parametrize("how", ["cycle_passed", "case_in_spec", "year_in_spec", "no_headings", "empty_headings"])
def test_a_binding_or_a_missing_heading_declaration_is_refused(world, how):
    record, sha, _ = world
    spec = spec_for(sha, unknown=True)
    cycle = None
    if how == "cycle_passed":
        cycle = copy.deepcopy(CYCLE)
    if how == "case_in_spec":
        spec["case_id"] = CASE
    if how == "year_in_spec":
        spec["fiscal_year"] = 2027
    if how == "no_headings":
        spec.pop("section_headings")
    if how == "empty_headings":
        spec["section_headings"] = []
    with pytest.raises(ValueError):
        extract_conditions(record, spec, cycle)


@pytest.mark.parametrize("how", ["cycle_passed", "case_in_spec", "year_in_spec"])
def test_the_notice_extractor_itself_refuses_a_binding_for_an_unknown_spec(world, how):  # the same rule one layer below (defence in depth)
    record, sha, _ = world
    spec = spec_for(sha, unknown=True)
    cycle = None
    if how == "cycle_passed":
        cycle = copy.deepcopy(CYCLE)
    if how == "case_in_spec":
        spec["case_id"] = CASE
    if how == "year_in_spec":
        spec["fiscal_year"] = 2027
    with pytest.raises(ValueError, match="UNKNOWN"):
        extract_notice(spec, record, cycle)


@pytest.mark.parametrize("field,value", [("case_id", CASE), ("fiscal_year", 2027), ("faculty", "情報学群"), ("department", "知識情報・図書館学類")])
def test_an_unknown_record_that_carries_a_binding_is_rejected(world, field, value):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    rec[field] = value
    with pytest.raises(ValueError, match="STR-076"):
        validate_condition_bindings(rec)
    rec[field] = None
    rec["scope"] = "target_admission_cycle"
    with pytest.raises(ValueError, match="STR-076"):
        validate_condition_bindings(rec)


# ------------------------------------------------------------------ 3 the heading guard fails closed
def test_the_heading_guard_fails_closed():
    t = normalize("A章です。Q甲?甲の答え。Q乙?乙の答え。")
    heads = ["Q甲？", "Q乙？"]
    s = t.index(normalize("甲の答え"))
    assert immediate_heading(t, s, s + 4, 0, len(t), heads) == "Q甲？"
    assert immediate_heading(t, t.index("Q乙"), t.index("Q乙") + 6, 0, len(t), heads) == "Q乙？"  # a span that starts on the heading itself
    with pytest.raises(ValueError, match="absent or ambiguous"):
        immediate_heading(t, s, s + 4, 0, len(t), ["Q甲？", "Q丙？"])
    with pytest.raises(ValueError, match="absent or ambiguous"):
        immediate_heading(t + "Q甲?", s, s + 4, 0, len(t) + 3, heads)
    with pytest.raises(ValueError, match="no declared FAQ heading precedes"):
        immediate_heading(t, 0, 2, 0, len(t), heads)
    with pytest.raises(ValueError, match="no section headings"):
        immediate_heading(t, s, s + 4, 0, len(t), [])
    with pytest.raises(ValueError, match="starts inside a heading"):
        immediate_heading(t, t.index("Q乙") + 1, t.index("Q乙") + 4, 0, len(t), heads)
    with pytest.raises(ValueError, match="spans two"):
        immediate_heading(t, s, t.index(normalize("乙の答え")) + 2, 0, len(t), heads)
    t2 = normalize("Q甲?甲の答え。途中の質問ですか?続きの答え。")
    with pytest.raises(ValueError, match="undeclared question"):
        immediate_heading(t2, t2.index("続き"), t2.index("続き") + 3, 0, len(t2), ["Q甲？"])


def test_an_undeclared_question_inside_the_answer_stops_extraction(world):
    record, sha, make = world
    extra_record, extra_sha = make(page().replace(f"<p>{CLAUSES[2]}</p>", f"<p>途中の質問ですか？</p><p>{CLAUSES[2]}</p>"))
    with pytest.raises(ValueError, match="undeclared question"):
        extract_conditions(extra_record, spec_for(extra_sha, unknown=True), None)


def test_an_anchor_that_quotes_two_questions_is_refused(world):
    record, sha, _ = world
    spec = spec_for(sha, unknown=True)
    spec["anchors"][0]["pattern"] = re.escape(normalize(Q1)) + ".*?" + re.escape(normalize(CLAUSES[4]))  # runs over the next question
    with pytest.raises(ValueError, match="spans two"):
        extract_conditions(record, spec, None)


# ------------------------------------------------------------------ 4 the independent audit
@pytest.mark.parametrize("change", ["carry_over", "swapped", "invented", "empty", "later_question"])
def test_the_source_audit_rejects_a_wrong_section(world, change):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    assert audit_condition_source(rec, record["local_path"])["status"] == "pass"
    proof = rec["proofs"][0]
    proof["section"] = {"carry_over": Q0, "swapped": Q2, "invented": "存在しない質問ですか？", "empty": "", "later_question": QX}[change]
    with pytest.raises(ValueError, match="immediate question"):
        audit_condition_source(rec, record["local_path"])


def test_the_audit_also_catches_the_delivered_carry_over_on_the_real_shaped_page(world):
    record, sha, _ = world
    legacy = structured_record(extract_conditions(record, spec_for(sha, unknown=False), copy.deepcopy(CYCLE)), None, "fixture-g2")
    assert [p["section"] for p in legacy["proofs"]] == [Q0] * 6  # the delivered extractor
    with pytest.raises(ValueError, match="immediate question"):
        audit_condition_source(legacy, record["local_path"])


# ------------------------------------------------------------------ 5 downstream: held, never attached or staged
def test_an_unknown_scope_record_is_not_attached_to_any_article(world):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    base = {"article_id": "base", "case_id": CASE, "text": "# fixture\n\n## 書類\n\n公式の書類説明。\n\n### 練習（編集上の助言）\n\n練習。\n\n## 根拠資料\n", "evidence_ids": [], "claims": []}
    with pytest.raises(ValueError, match="no applicable notices"):
        revise_article(base, [rec], date(2026, 11, 8))


def native_store(tmp_path, record):
    db_path = tmp_path / "work.sqlite"
    base = EvidenceStore(db_path)
    profile = dict(CYCLE, sha256="a" * 64, url="https://fixture.ac.jp/guide")
    base.ingest(Extracted(CASE, profile, tmp_path / "dummy.pdf", ["fixture"], []), "2026-11-01")
    original = {"article_id": "base", "case_id": CASE, "input_hash": "a" * 64, "series": "overview", "title": "fixture", "text": "# fixture\n\n## 根拠資料\n",
                "claim": {k: CYCLE[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}, "evidence_ids": [], "publish_allowed": False}
    base.save_article(original, tmp_path / "original.md")
    return db_path, RevisionStore(db_path, tmp_path / "before.sqlite")


def test_an_unknown_scope_record_cannot_be_staged_into_a_cycle(world, tmp_path):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    _db, store = native_store(tmp_path, record)
    before = store.heads()
    with pytest.raises(ValueError, match="cross-cycle"):
        store.stage([rec], {"fact_keys": {"generative_ai_policy": {"status": "active", "value": {}}}})
    assert store.heads() == before


def test_the_driver_holds_an_unknown_scope_candidate_and_stages_nothing(world, tmp_path):
    from scripts.revise_notices import run
    record, sha, _ = world
    db_path, store = native_store(tmp_path, record)
    before = store.heads()
    root = tmp_path / "monitor"
    (root / "bodies").mkdir(parents=True)
    (root / "bodies" / (sha + ".html")).write_bytes(Path(record["local_path"]).read_bytes())
    with sqlite3.connect(root / "monitor.sqlite") as db:
        db.execute("CREATE TABLE targets(url TEXT,last_success REAL,last_error TEXT,last_sha TEXT)")
        db.execute("INSERT INTO targets VALUES(?,?,NULL,?)", (record["url"], time.time(), sha))
    qa = tmp_path / "qa"
    (qa / "src/verify/data").mkdir(parents=True)
    registry = {"fact_keys": {"generative_ai_policy": {"status": "active", "value": {}}}}
    (qa / "src/verify/data/fact_keys.json").write_text(json.dumps(registry))
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps([spec_for(sha, unknown=True)]), encoding="utf-8")
    out = tmp_path / "out"
    report = run(spec_path, root, tmp_path / "unused.json", db_path, db_path, qa, out, date(2026, 11, 8))
    assert len(report["scope_unknown_held"]) == 1 and report["candidate_count"] == 0 and not report["approved"] and report["revised_articles"] == 0
    assert report["source_review_pending"] == [] and store.heads() == before
    held = json.loads((out / "scope-unknown-held.json").read_text(encoding="utf-8"))
    assert [h["evidence_id"] for h in held] == report["scope_unknown_held"] and held[0]["case_id"] is None and held[0]["scope_status"] == "unknown"
    assert [p["section"] for p in held[0]["proofs"]] == [Q1, Q1, Q1, Q1, Q1, Q2]


# ------------------------------------------------------------------ the production spec (the patched config)
def test_the_patched_config_is_scope_unknown_and_declares_both_questions():
    spec = json.loads((Path(__file__).resolve().parents[1] / "config" / "faq-structured-v3.json").read_text(encoding="utf-8"))[0]
    assert spec["scope_status"] == "unknown" and "case_id" not in spec and "fiscal_year" not in spec and spec["parent_evidence_id"] is None
    assert spec["section_headings"] == [Q1, Q2] and spec["section_start"] == Q0
    assert spec["expected_sha256"] == "dad557c53e2e66f6f05807d90abb6cfc708a55b6200dec579d1bf2389cf9a770"
    assert spec["profile_version"] != "faq-conditions-2026-11-01-v1"  # a different scope is a different evidence identity
    assert set(FIELDS)  # the delivered field table is untouched
