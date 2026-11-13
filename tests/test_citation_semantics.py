"""Issue #10: a citation id swapped for a *different real* record. No unknown-id check can see it;
only whether the sentence is about the cited fact. Cues per fact_key live in the registry."""
import copy
import json
import re
from pathlib import Path

import pytest

from src.article_qa.evaluate import evaluate_article
from src.article_qa.mutation_sweep import swap_sweep
from src.verify import fact_registry as fr
from src.verify.strict_claims import check_article_strict

REPO = Path(__file__).parent.parent
REGISTRY = fr.get_registry()
RAW = json.loads(fr.DEFAULT_PATH.read_text(encoding="utf-8"))
CLAIM = {"university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試", "fiscal_year": 2027}


def ev(eid, key, value):
    return {"evidence_id": eid, "university": "〇〇大学", "faculty": "環境学部", "admission_method": "夏秋AO入試",
            "fiscal_year": 2027, "fact_key": key, "value": value, "scope": "target_admission_cycle",
            "proofs": [{"page": 5, "quote": "x"}]}


EVIDENCE = {
    "EV-S1": ev("EV-S1", "first_stage", {"text": "書類選考"}),
    "EV-R1": ev("EV-R1", "first_stage_result", {"date": "2026-10-08", "time": "11:00"}),
    "EV-FN": ev("EV-FN", "final_result", {"date": "2026-11-02", "time": "11:00"}),
    "EV-CT": ev("EV-CT", "common_test", {"required": False}),
    "EV-IS": ev("EV-IS", "interview_scope", {"text": "面接の配点に書類審査を含む"}),
    "EV-IV": ev("EV-IV", "interview", {"date": "2026-11-28", "time": "13:00", "type": "starting_time_not_duration"}),
    "EV-SL": ev("EV-SL", "statement_length", {"max_characters": 800}),
    "EV-PS": ev("EV-PS", "personal_statement", {"essay_max_ja_chars": 2000}),
}
SENTENCES = {
    "EV-S1": "第1次選考は、提出書類で選考する方式です。",
    "EV-R1": "第1次選考の結果発表は、2026年10月8日 11:00からです。",
    "EV-FN": "最終段階の合格発表は、2026年11月2日 11:00からです。",
    "EV-CT": "大学入学共通テストは免除されます。",
    "EV-IS": "面接の配点には、書類審査を含みます。",
    "EV-IV": "面接は2026年11月28日 13:00からです。",
    "EV-SL": "志願理由書は800字以内でまとめます。",
    "EV-PS": "文章は日本語2000字以内です。",
}


def article(**swaps):
    """One paragraph per sentence; `swaps` maps an evidence id to the id actually written."""
    parts = [f"{SENTENCES[e]}[{swaps.get(e, e)}]" for e in SENTENCES]
    return "# 〇〇大学 環境学部 夏秋AO入試\n\n" + "\n\n".join(parts) + "\n\n最新情報は大学公式サイトでご確認ください。\n"


def topic(text):
    return [i for i in check_article_strict(text, CLAIM, EVIDENCE) if i.category == "citation_topic_mismatch"]


def test_the_correct_citations_raise_nothing():
    assert topic(article()) == []


@pytest.mark.parametrize("sentence_of,cited", [
    ("EV-S1", "EV-R1"),   # the method of the first stage vs. its result announcement
    ("EV-R1", "EV-FN"),   # first-stage result vs. final result
    ("EV-FN", "EV-R1"),
    ("EV-CT", "EV-IS"),   # common test vs. what the interview covers: both mention 面接 / 選抜 in real drafts
    ("EV-IS", "EV-IV"),   # interview scope vs. interview date/time
    ("EV-IV", "EV-IS"),
    ("EV-SL", "EV-PS"),   # statement length vs. essay limits
    ("EV-PS", "EV-SL"),
    ("EV-CT", "EV-FN"),
])
def test_a_swapped_citation_to_a_different_real_fact_is_flagged(sentence_of, cited):
    found = topic(article(**{sentence_of: cited}))
    assert found and cited in found[0].detail, found


def test_two_citations_on_one_sentence_must_both_fit_one_claim_one_evidence():
    text = "# 〇〇大学 環境学部 夏秋AO入試\n\n第1次選考は、提出書類で選考する方式です。[EV-S1][EV-FN]\n\n最新情報は大学公式サイトでご確認ください。\n"
    found = topic(text)
    assert [i.detail.split()[0] for i in found] == ["EV-FN"]  # EV-S1 fits; EV-FN (the final result) does not


def test_the_finding_names_the_cues_the_paragraph_lacked():
    found = topic(article(**{"EV-S1": "EV-R1"}))
    assert "first_stage_result" in found[0].detail and "cues" in found[0].detail


# ----------------------------------------------- the registry's cues

def test_every_active_key_has_cues_and_every_cue_compiles():
    for key, spec in REGISTRY.fact_keys.items():
        if spec["status"] == "active":
            assert spec.get("cues"), key
        for cue in spec.get("cues", []):
            if cue.startswith("re:"):
                re.compile(cue[3:])


def test_each_keys_own_cues_accept_a_sentence_made_from_them_and_reject_unrelated_text():
    for key, spec in REGISTRY.fact_keys.items():
        for cue in spec["cues"]:
            if not cue.startswith("re:"):
                assert REGISTRY.cue_match(key, f"……{cue}……") is True, (key, cue)
        assert REGISTRY.cue_match(key, "天気は晴れです。") is False, key


def test_a_key_registered_without_cues_falls_back_to_its_topic_keywords_and_unknown_keys_are_unconstrained():
    data = copy.deepcopy(RAW)
    data["fact_keys"]["waitlist"] = {"description": "補欠", "status": "proposed", "since": "1.5.0", "scopes": ["*"],
                                     "topic_keywords": ["補欠"], "value": {"seats": {"type": "integer", "kind": "persons"}}}
    registry = fr.Registry(data)
    assert registry.cue_match("waitlist", "補欠の人数") is True and registry.cue_match("waitlist", "天気") is False
    assert registry.cue_match("not_registered", "天気") is None


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d["fact_keys"]["quota"].pop("cues"), "active key must have cues"),
    (lambda d: d["fact_keys"]["quota"].update(cues=[]), "cues must be a non-empty list"),
    (lambda d: d["fact_keys"]["quota"].update(cues=["re:("]), "bad cue regex"),
])
def test_a_malformed_cue_list_is_rejected(mutate, expected):
    data = copy.deepcopy(RAW)
    mutate(data)
    assert any(expected in p for p in fr.validate_registry_data(data))


def test_a_cue_change_in_data_changes_the_verdict_without_touching_python():
    data = copy.deepcopy(RAW)
    data["fact_keys"]["common_test"]["cues"] = ["共通テストの成績"]
    strict = fr.Registry(data)
    text = article()
    assert not [i for i in check_article_strict(text, CLAIM, EVIDENCE, REGISTRY) if i.category == "citation_topic_mismatch"]
    assert [i for i in check_article_strict(text, CLAIM, EVIDENCE, strict) if i.category == "citation_topic_mismatch"]


# ----------------------- through evaluate_article, and on Work's real data

def test_evaluate_article_reports_the_swap_as_a_failure():
    report = evaluate_article("a", article(**{"EV-S1": "EV-R1"}), CLAIM, EVIDENCE)
    assert not report.ok and "citation_topic_mismatch" in {f["category"] for f in report.findings}


EXPORTS = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
           for p in sorted((REPO / "research" / "inbox").rglob("claude-compatible-export.json"))}


@pytest.mark.parametrize("name", list(EXPORTS))
def test_every_real_citation_swapped_for_every_other_real_fact_is_almost_always_caught(name):
    export = EXPORTS[name]
    result = swap_sweep(export, reference_date="2026-11-01", require_as_of=True)
    assert result["swaps"] > 50 and result["detection_rate"] >= 0.98, (name, result["survivors"][:5])


def test_the_swaps_that_survive_are_ones_the_sentence_really_cannot_tell_apart():
    """Honest limit: a first-stage sentence that names 自己推薦書 and 志願理由書 is genuinely about
    those documents too. These are recorded, not hidden."""
    result = swap_sweep(EXPORTS["samples"], reference_date="2026-11-01", require_as_of=True)
    assert 0 < result["survived"] <= 12
    assert {s["from"] for s in result["survivors"]} <= {"first_stage", "interview_scope", "generative_ai_policy"}
