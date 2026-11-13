"""Issue #19: the fact_key registry — data, versioned, never silently permissive.

Synthetic data except where it says "real" (Work's v0.2 handoff, in the repo)."""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.integration.validate_export import validate_records
from src.run_qa_suite import run_articles
from src.verify import fact_registry as fr
from src.verify.strict_claims import QUANTITY_KINDS, check_article_strict, expected_from_evidence

REPO = Path(__file__).parent.parent
EXPORT = json.loads((REPO / "research/inbox/work-db-v02-20261101/samples/claude-compatible-export.json").read_text(encoding="utf-8"))
RAW = json.loads(fr.DEFAULT_PATH.read_text(encoding="utf-8"))
REGISTRY = fr.get_registry()
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}


def ev(eid, key, value, scope="target_admission_cycle", **extra):
    return {"evidence_id": eid, "university": "〇〇大学", "faculty": "環境学部", "department": None,
            "admission_method": "夏秋AO入試", "fiscal_year": 2027, "fact_key": key, "value": value, "scope": scope,
            "proofs": [{"page": 3, "quote": "x"}], **extra}


def categories(issues):
    return {i.category for i in issues}


def with_registry(mutate):
    data = copy.deepcopy(RAW)
    mutate(data)
    return fr.Registry(data)


# ------------------------------------------------------- the file itself

def test_registry_file_is_well_formed_and_versioned():
    assert fr.validate_registry_data(RAW) == []
    assert re.fullmatch(r"\d+\.\d+\.\d+", REGISTRY.version) and RAW["schema_version"] == fr.SCHEMA_VERSION


def test_every_registered_kind_is_one_the_article_checker_understands():
    assert set(RAW["kinds"]) == set(QUANTITY_KINDS)


def test_the_21_real_fact_keys_plus_fee_are_registered():
    real = {e["fact_key"] for e in EXPORT["evidence"].values()}
    assert len(real) == 21 and real <= set(REGISTRY.fact_keys)
    assert "fee" in REGISTRY.fact_keys


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d.update(registry_version="1.0"), "semver"),
    (lambda d: d.update(schema_version=2), "schema_version"),
    (lambda d: d["fact_keys"]["quota"]["value"]["count"].update(kind="nope"), "unknown kind"),
    (lambda d: d["fact_keys"]["quota"]["value"]["count"].update(type="string"), "quantity kind needs"),
    (lambda d: d["fact_keys"]["quota"]["value"]["count"].update(type="bignum"), "type must be one of"),
    (lambda d: d["semantic_triggers"][0].update(rule="no_such_rule"), "unknown rule"),
    (lambda d: d["semantic_triggers"][0].update(equals="x"), "exactly one of"),
    (lambda d: d["rules"]["aggregate_total"].update(forbidden_patterns=["("]), "bad regex"),
    (lambda d: d["fact_keys"]["quota"].update(status="maybe"), "status must be"),
    (lambda d: d["fact_keys"]["quota"].update(topic_keywords=[]), "topic_keywords is required"),
    (lambda d: d["fact_keys"]["quota"].update(stage=3), "stage must be"),
    (lambda d: d["fact_keys"]["quota"].update(scopes=["nowhere"]), "unknown scope"),
    (lambda d: d["fact_keys"]["quota"].update(status="deprecated"), "replaced_by"),
    (lambda d: d["fact_keys"].update({"Bad-Name": copy.deepcopy(d["fact_keys"]["quota"])}), "lower_snake_case"),
    (lambda d: d.pop("changelog"), "changelog must list"),
    (lambda d: d["changelog"][-1].update(version="9.9.9"), "last entry must be the current"),
    (lambda d: d["changelog"].append({"version": "1.0.0", "changes": ["x"]}), "strictly increasing"),
    (lambda d: d["changelog"][0].update(changes=[]), "needs `changes`"),
])
def test_a_malformed_registry_is_rejected_loudly(mutate, expected):
    data = copy.deepcopy(RAW)
    mutate(data)
    problems = fr.validate_registry_data(data)
    assert any(expected in p for p in problems), problems
    with pytest.raises(fr.RegistryError):
        fr.Registry(data)


# ------------------------------------------- real data: nothing weakened

def test_real_evidence_is_clean_against_the_registry():
    report = REGISTRY.check_evidence(EXPORT["evidence"])
    assert report["ok"] and report["by_severity"] == {"error": 0, "warning": 0, "notice": 0}, report["issues"]
    assert report["unregistered_fact_keys"] == [] and report["records"] == 30


def test_registry_classifies_every_real_number_exactly_as_the_old_name_hints_did():
    """The registry replaced hard-coded hints. For all 30 real records (and the
    synthetic ones used elsewhere) it must produce the same expectations."""
    bare = with_registry(lambda d: [d["fact_keys"].pop(k) for k in list(d["fact_keys"]) if k != "fee"])  # almost-empty registry => name hints only
    for eid, record in EXPORT["evidence"].items():
        assert expected_from_evidence(record, REGISTRY) == expected_from_evidence(record, bare), eid


def test_registry_topic_keywords_match_what_the_checker_used_to_hold():
    # spot-check the keys whose keywords carry the citation-swap detection
    assert REGISTRY.topic_keywords("common_test") == ("共通テスト",)
    assert "結果発表" in REGISTRY.topic_keywords("first_stage_result")
    assert REGISTRY.stage("first_stage_result") == 1 and REGISTRY.stage("second_stage_date") == 2
    assert REGISTRY.stage("interview") is None and REGISTRY.topic_keywords("not_registered") == ()


def test_the_four_real_drafts_still_pass_with_no_registry_notes():
    for a in EXPORT["articles"]:
        report = evaluate_article(a["article_id"], a["text"], a["claim"], EXPORT["evidence"])
        assert report.ok and report.notices == [], (a["article_id"], report.findings, report.notices)


# ---------------------------------------- unregistered keys are never ok

def _article(eid):
    return f"〇〇大学 環境学部 夏秋AO入試の募集人員は150名[{eid}]です。最新情報は大学公式サイトでご確認ください。"


def test_unregistered_fact_key_is_an_error_even_when_every_value_matches():
    record = ev("EV-X", "brand_new_key", {"count": 150}, quota=150)
    assert categories(REGISTRY.check_record(record)) == {"unregistered_fact_key"}
    report = evaluate_article("a", _article("EV-X"), CLAIM, {"EV-X": record})
    assert not report.ok
    assert "unregistered_fact_key" in {f["category"] for f in report.findings}  # reported, never silently verified


def test_unregistered_key_still_gets_value_checking():
    """Unregistered must not mean unchecked: the old name-based checking continues."""
    record = ev("EV-X", "brand_new_key", {"count": 150}, quota=150)
    wrong = _article("EV-X").replace("150名", "999名")
    cats = {f["category"] for f in evaluate_article("a", wrong, CLAIM, {"EV-X": record}).findings}
    assert {"unregistered_fact_key", "quantity_mismatch"} <= cats


def test_content_triggered_rules_still_apply_to_an_unregistered_key():
    record = ev("EV-X", "brand_new_interview", {"minutes": 30, "type": "allocated_time_window_not_net_question_time"})
    text = "〇〇大学 環境学部 夏秋AO入試の面接の質疑時間は30分[EV-X]です。最新情報は大学公式サイトでご確認ください。"
    cats = {f["category"] for f in evaluate_article("a", text, CLAIM, {"EV-X": record}).findings}
    assert {"unregistered_fact_key", "scope_reinterpretation"} <= cats


def test_export_gate_rejects_unregistered_keys_and_lists_them():
    export = {"EV-X": {**ev("EV-X", "brand_new_key", {"count": 1}), "source_url": "https://example.ac.jp/a.pdf",
                       "source_pdf_sha256": "a" * 64, "retrieved_at": "2026-11-01"}}
    result = validate_records(export)
    assert result["invalid_count"] == 1 and result["unregistered_fact_keys"] == ["brand_new_key"]
    assert any("unregistered_fact_key" in e for e in result["records"]["EV-X"]["errors"])
    assert result["registry_version"] == REGISTRY.version


# --------------------------------------------- field-level and other cases

@pytest.mark.parametrize("record,severity,category", [
    (ev("E", "quota", {"unit": "名"}), "error", "missing_required_field"),
    (ev("E", "quota", {"count": None}), "error", "missing_required_field"),
    (ev("E", "quota", {"count": "5"}), "error", "value_type_mismatch"),
    (ev("E", "quota", {"count": True}), "error", "value_type_mismatch"),
    (ev("E", "quota", {"count": 5.0}), "error", "value_type_mismatch"),
    (ev("E", "online_period", {"start": "2026-13-45", "end": "2026-09-01"}), "error", "value_type_mismatch"),
    (ev("E", "online_period", {"start": "2026-08-03T10:00:00+09:00", "end": "yesterday"}), "error", "value_type_mismatch"),
    (ev("E", "final_result", {"date": "2026-11-02", "time": "25:99"}), "error", "value_type_mismatch"),
    (ev("E", "entry", {"months": ["2027-13"]}), "error", "value_type_mismatch"),
    (ev("E", "second_stage_date", {"dates": ["2026-10-24", 5]}), "error", "value_type_mismatch"),
    (ev("E", "common_test", {"required": "no"}), "error", "value_type_mismatch"),
    (ev("E", "quota", [1, 2]), "error", "value_not_object"),
    (ev("E", "quota", {"count": 5, "invented_field": 1}), "warning", "unregistered_value_field"),
    (ev("E", "second_stage_date", {"dates": ["2026-10-24"], "selection": "lottery"}), "warning", "unregistered_value"),
    (ev("E", "quota", {"count": 5}, scope="some_new_scope"), "warning", "unregistered_scope"),
    (ev("E", "quota", {"count": 5}, scope="all_niigata_suisen"), "warning", "scope_unusual_for_key"),  # quota never applies to 'all units'
])
def test_field_level_checks(record, severity, category):
    hits = [i for i in REGISTRY.check_record(record) if i.category == category]
    assert hits and hits[0].severity == severity, [i.to_dict() for i in REGISTRY.check_record(record)]


def test_valid_variants_pass_cleanly():
    for record in (
        ev("E", "quota", {"count": 5, "summer_autumn_only_count": None}),
        ev("E", "online_period", {"start": "2026-08-03T10:00:00+09:00", "end": "2026-09-01T15:00:00+09:00"}),
        ev("E", "postal_period", {"start": "2026-09-01", "end": "2026-09-02"}),
        ev("E", "final_result", {"date": "2026-11-02", "time": "11:00"}, scope="all_niigata_suisen"),
    ):
        assert REGISTRY.check_record(record) == [], record


def test_a_warning_does_not_fail_the_article_but_is_not_hidden():
    record = ev("EV-X", "quota", {"count": 150, "invented_field": 1}, quota=150)
    report = evaluate_article("a", _article("EV-X"), CLAIM, {"EV-X": record})
    assert report.ok, report.findings
    assert [n["category"] for n in report.notices] == ["unregistered_value_field"] and report.notices[0]["severity"] == "warning"


def test_legacy_record_without_fact_key_is_still_checked_and_noted():
    fixture = json.loads((REPO / "tests/fixtures/sample_articles.json").read_text(encoding="utf-8"))
    article = next(a for a in fixture["articles"] if a["article_id"] == "sample-clean")
    report = evaluate_article("c", article["text"], article["claim"], fixture["evidence"])
    assert report.ok and [n["category"] for n in report.notices] == ["legacy_no_fact_key"]
    tampered = evaluate_article("t", article["text"].replace("30名", "999名"), article["claim"], fixture["evidence"])
    assert not tampered.ok  # legacy evidence is not exempt


def test_proposed_key_is_usable_but_always_flagged():
    registry = with_registry(lambda d: d["fact_keys"].update({"recommenders": {
        "description": "推薦者", "status": "proposed", "since": "1.1.0", "scopes": ["target_admission_cycle"],
        "topic_keywords": ["推薦者"], "value": {"count": {"type": "integer", "kind": "persons", "required": True}}}}))
    record = ev("EV-N", "recommenders", {"count": 3})
    assert [(i.severity, i.category) for i in registry.check_record(record)] == [("notice", "fact_key_proposed")]
    ok = "〇〇大学 環境学部 夏秋AO入試の推薦者は3名[EV-N]です。最新情報は大学公式サイトでご確認ください。"
    report = evaluate_article("a", ok, CLAIM, {"EV-N": record}, registry=registry)
    assert report.ok and [n["category"] for n in report.notices] == ["fact_key_proposed"]
    bad = evaluate_article("b", ok.replace("3名", "4名"), CLAIM, {"EV-N": record}, registry=registry)
    assert "quantity_mismatch" in {f["category"] for f in bad.findings}


def test_deprecated_key_warns_and_names_its_replacement():
    registry = with_registry(lambda d: d["fact_keys"]["fee"].update(status="deprecated", replaced_by="application_fee"))
    issues = registry.check_record(ev("E", "fee", {"amount": 17000}))
    assert [(i.severity, i.category) for i in issues] == [("warning", "fact_key_deprecated")] and "application_fee" in issues[0].detail


# ---------------------- a new fact_key needs data, not Python (the point of #19)

def test_adding_a_key_in_data_gives_unit_checks_topic_checks_and_stage_checks():
    registry = with_registry(lambda d: d["fact_keys"].update({"waitlist": {
        "description": "補欠", "status": "active", "since": "1.1.0", "stage": 2, "scopes": ["*"],
        "topic_keywords": ["補欠"], "cues": ["補欠"],
        "value": {"seats": {"type": "integer", "kind": "persons", "required": True},
                  "minutes_to_answer": {"type": "integer", "kind": "minutes"}}}}))
    record = ev("EV-W", "waitlist", {"seats": 8, "minutes_to_answer": 20})
    evidence = {"EV-W": record}
    good = "〇〇大学 環境学部 夏秋AO入試の補欠は第2次選考で8名[EV-W]、回答は20分[EV-W]以内です。"
    assert not check_article_strict(good, CLAIM, evidence, registry)
    assert {i.category for i in check_article_strict(good.replace("8名", "9名"), CLAIM, evidence, registry)} == {"quantity_mismatch"}
    assert {i.category for i in check_article_strict(good.replace("20分", "30分"), CLAIM, evidence, registry)} == {"quantity_mismatch"}
    assert "stage_mismatch" in {i.category for i in check_article_strict(good.replace("第2次", "第1次"), CLAIM, evidence, registry)}
    off_topic = "〇〇大学 環境学部 夏秋AO入試の出願は8名[EV-W]です。"
    assert "citation_topic_mismatch" in {i.category for i in check_article_strict(off_topic, CLAIM, evidence, registry)}


def test_wording_cues_are_data_too():
    """Change the cue word in the registry and the rule changes — no Python edited."""
    text = "〇〇大学 環境学部 夏秋AO入試の募集人員は年度内の合計で150名[EV-Q]です。"
    evidence = {"EV-Q": ev("EV-Q", "quota", {"count": 150}, scope="faculty_annual_AO_aggregate", quota=150)}
    assert not check_article_strict(text, CLAIM, evidence, REGISTRY)
    strict = with_registry(lambda d: d["rules"]["aggregate_total"].update(required_any=["年度内合算"]))
    assert "scope_reinterpretation" in {i.category for i in check_article_strict(text, CLAIM, evidence, strict)}


# ------------------------------------------------------------ reports

def test_qa_suite_report_carries_registry_version_and_unregistered_keys():
    data = {"evidence": {"EV-X": ev("EV-X", "brand_new_key", {"count": 150}, quota=150)},
            "articles": [{"article_id": "a", "text": _article("EV-X"), "claim": CLAIM}]}
    result = run_articles(data)
    assert result["registry"]["registry_version"] == REGISTRY.version
    assert result["registry"]["unregistered_fact_keys"] == ["brand_new_key"] and result["registry"]["ok"] is False
    assert result["per_article"][0]["ok"] is False


def test_check_report_lists_what_it_found():
    evidence = {"EV-1": ev("EV-1", "quota", {"count": 5}), "EV-2": ev("EV-2", "zzz", {}), "EV-3": {"evidence_id": "EV-3"},
                "EV-4": ev("EV-4", "fee", {"amount": 1}) | {"fact_key": "recommenders"}}
    report = REGISTRY.check_evidence(evidence)
    assert report["unregistered_fact_keys"] == ["recommenders", "zzz"] and report["records_without_fact_key"] == ["EV-3"]
    assert report["by_severity"]["error"] == 2 and not report["ok"]


# --------------------------------------------------- generated reference

def test_reference_document_is_generated_from_the_registry():
    expected = fr.render_markdown(REGISTRY)
    actual = (REPO / "docs" / "FACT_KEYS_REFERENCE.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, "regenerate: python -m src.verify.fact_registry markdown > docs/FACT_KEYS_REFERENCE.md"
    for key in REGISTRY.fact_keys:
        assert f"`{key}`" in actual


# --------------------------------------------------------------------- CLI

def _cli(*args):
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "src.verify.fact_registry", *args], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_cli_validate_list_show_check(tmp_path: Path):
    assert _cli("validate").returncode == 0
    listed = _cli("list")
    assert listed.returncode == 0 and "quota\tactive" in listed.stdout
    assert _cli("show", "quota").returncode == 0 and _cli("show", "nope").returncode == 1
    export = REPO / "research/inbox/work-db-v02-20261101/samples/claude-compatible-export.json"
    assert _cli("check", str(export)).returncode == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"evidence": {"EV-X": ev("EV-X", "brand_new_key", {"count": 1})}}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "report.json"
    r = _cli("check", str(bad), "--json-out", str(out))
    assert r.returncode == 1 and json.loads(out.read_text(encoding="utf-8"))["unregistered_fact_keys"] == ["brand_new_key"]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({**RAW, "registry_version": "x"}), encoding="utf-8")
    assert _cli("validate", "--registry", str(broken)).returncode == 1
