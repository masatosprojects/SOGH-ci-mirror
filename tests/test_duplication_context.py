"""Tests of the report-only duplication context (src/article_qa/duplication_context.py, contract docs/QA_DUPLICATION_CONTEXT_CONTRACT.md).

SYNTHETIC_ONLY: invented articles. The module explains the repeats the QA gate reports; it never changes the gate. These tests therefore also pin that the gate (thresholds and findings) is unchanged."""
import copy

import pytest

from src.article_qa import checks
from src.article_qa import duplication_context as D

NOTICE = "本記事は公式資料の内容を確認するための参考情報であり、最新の募集要項を必ずご確認ください。"
HEADING = "根拠資料"
RULES = {"version": "dup-rules-test-1", "entries": [
    {"id": "N-1", "kind": "mandatory_notice", "text": NOTICE, "rationale": "readers must be told to check the official source", "contract_ref": "POLICY-NOTICE-1", "approved_by": "qa-owner"},
    {"id": "H-1", "kind": "heading", "text": HEADING, "rationale": "the section where sources are listed", "contract_ref": "POLICY-STRUCT-1", "approved_by": "qa-owner"},
]}


def article(i, prose, notice=True, source=True):
    lines = [f"# 架空大学{i}の案内", prose, f"募集人員は{10 + i}名です。[EV-{i}]"]
    if notice:
        lines.append(NOTICE)
    if source:
        lines += ["## " + HEADING, f"- [EV-{i}] 架空大学{i} 募集要項 https://example.invalid/doc/{i}"]
    return "\n".join(lines)


def corpus(prose_for, n=6, **kw):
    return {f"a{i}": article(i, prose_for(i), **kw) for i in range(n)}


def distinct(i):
    return ["春の説明会は三月に開かれます。", "書類は郵送で受け付けます。", "面接は対面で行います。", "出願期間は一月です。", "試験会場は本部棟です。", "合否は後日通知します。"][i % 6] + f"（その{i}）固有の文{i * 7}。"


@pytest.fixture
def rules():
    return D.load_rules(RULES)


def test_a_registered_notice_repeated_in_every_article_is_scaffold_only_while_the_gate_still_reports_it(rules):
    arts = corpus(distinct)
    gate = checks.find_overused_phrases(arts)
    report = D.classify_repeats(arts, rules)
    assert gate and report["total"] == len({f.detail.split("'")[1] for f in gate}) and D.gate_unchanged(arts, rules)
    notice_phrase = D._gate_flat(NOTICE)[:12]
    row = next(r for r in report["repeats"] if r["phrase"] == notice_phrase)
    assert row["scaffold_only"] and set(row["kinds"]) == {"mandatory_notice"}


def test_the_same_phrase_in_prose_is_uncovered_even_when_it_is_also_a_registered_notice_elsewhere(rules):
    arts = corpus(distinct)
    for aid in ("a0", "a1"):
        arts[aid] = arts[aid].replace(distinct(int(aid[1])), "私たちはこの大学の特色を丁寧にお伝えします。" + NOTICE[:20])
    arts["a2"] = arts["a2"] + "\n" + NOTICE[:20] + "という点にも注意してください。"
    row = next(r for r in D.classify_repeats(arts, rules)["repeats"] if r["phrase"] == D._gate_flat(NOTICE)[:12])
    assert not row["scaffold_only"] and "prose" in row["kinds"]


def test_a_body_sentence_that_merely_contains_the_notice_is_not_the_notice(rules):
    arts = corpus(distinct, notice=False)
    for aid in arts:
        arts[aid] += "\n" + NOTICE + "なお締切は今年だけ変更されました。"  # the registered text plus a fact: not an exact line
    report = D.classify_repeats(arts, rules)
    inside = [r for r in report["repeats"] if r["phrase"] in D._gate_flat(NOTICE)]
    assert inside and all(not r["scaffold_only"] and "mandatory_notice" not in r["kinds"] for r in inside)


def test_a_prose_line_placed_under_the_source_heading_is_not_a_source_item(rules):
    arts = corpus(distinct, source=False)
    for aid in arts:
        arts[aid] += "\n## " + HEADING + "\n- [EV-9] この大学は全国で最も入りやすいと言われています。詳しくは本文を読んでください。"
    report = D.classify_repeats(arts, rules)
    sentence = D._gate_flat("この大学は全国で最も入りやすいと言われています")[:12]
    assert not next(r for r in report["repeats"] if r["phrase"] == sentence)["scaffold_only"]


def test_a_window_across_a_line_break_is_never_scaffold(rules):
    arts = {f"a{i}": f"# 題{i}\n手続きの流れは次のとおり。\n受付は窓口で行います。固有{i}" for i in range(6)}
    report = D.classify_repeats(arts, rules)
    crossing = [r for r in report["repeats"] if "cross_line" in r["kinds"]]
    assert crossing and all(not r["scaffold_only"] for r in crossing)


def test_an_unregistered_heading_is_not_scaffold(rules):
    arts = {f"a{i}": f"# 全ての記事に共通して置かれている見出しです\n本文{i}の固有の内容がここに入ります。" for i in range(6)}
    row = next(r for r in D.classify_repeats(arts, rules)["repeats"] if "heading_unregistered" in r["kinds"])
    assert not row["scaffold_only"]


def test_whitespace_and_width_differences_do_not_hide_a_registered_line(rules):
    arts = corpus(distinct, notice=False)
    for aid in arts:
        arts[aid] += "\n" + "　".join(NOTICE.replace("公式", "公式 "))
    assert D.line_kind(arts["a0"].splitlines()[-1], rules) == "mandatory_notice"  # the same line under a different spacing is still the registered line
    assert D.line_kind(NOTICE.replace("公式", "ＡＩ"), rules) == "prose"  # a different word is a different line


@pytest.mark.parametrize("mutate,message", [
    (lambda r: r["entries"][0].pop("rationale"), "exactly"),
    (lambda r: r["entries"][0].update(approved_by=" "), "non-empty"),
    (lambda r: r["entries"][0].update(contract_ref=""), "non-empty"),
    (lambda r: r["entries"][0].update(kind="source_item"), "kind must be"),
    (lambda r: r["entries"][0].update(text="短い注意書き"), "shorter than"),
    (lambda r: r["entries"][1].update(text="あ"), "shorter than"),
    (lambda r: r["entries"].append(copy.deepcopy(r["entries"][0])), "twice"),
    (lambda r: r.update(thresholds={"phrase_len": 4}), "nothing else"),
    (lambda r: r["entries"][0].update(pattern=".*注意.*"), "exactly"),
    (lambda r: r.update(version=""), "nothing else"),
])
def test_a_registry_that_is_loose_or_claims_thresholds_is_refused(mutate, message):
    bad = copy.deepcopy(RULES)
    mutate(bad)
    with pytest.raises(D.RuleError, match=message):
        D.load_rules(bad)


def test_a_change_of_the_registry_changes_its_sha_and_the_report_names_both_version_and_sha(rules):
    other = copy.deepcopy(RULES)
    other["entries"][0]["rationale"] = "changed"
    assert D.load_rules(other)["sha256"] != rules["sha256"]
    report = D.classify_repeats(corpus(distinct), rules)
    assert report["rules_version"] == "dup-rules-test-1" and report["rules_sha256"] == rules["sha256"] and report["contract"] == "duplication-context-v1"


def test_the_thresholds_of_the_report_are_the_thresholds_of_the_gate():
    assert D.thresholds_are_the_gates()
    assert checks.find_near_duplicates.__defaults__ == (0.8,)


def test_removing_the_registry_makes_the_notice_uncovered_so_the_exclusion_is_only_what_is_registered():
    empty = D.load_rules({"version": "empty", "entries": []})
    report = D.classify_repeats(corpus(distinct), empty)
    row = next(r for r in report["repeats"] if r["phrase"] == D._gate_flat(NOTICE)[:12])
    assert not row["scaffold_only"] and row["kinds"] == {"prose": 6}  # an unregistered notice is just text


def test_two_articles_with_identical_scaffold_and_different_prose_are_scaffold_driven(rules):
    a = article(1, "春の説明会は三月に開かれ、オンラインでも参加できます。事前の申し込みは不要です。")
    b = article(1, "書類は郵送のみで受け付けます。締切日の消印が有効となり、窓口提出はできません。")
    p = D.similarity_profile(a, b, rules)
    assert p["whole"] > p["body_only"] and p["reading"] != "substantive"


def test_two_articles_that_say_the_same_thing_are_substantive_even_with_different_scaffold(rules):
    prose = "書類は郵送のみで受け付けます。締切日の消印が有効となり、窓口提出はできません。提出先は入試課です。"
    head = "# 同じ題の記事\n" + prose + "\n募集人員は十名です。[EV-1]\n"
    a = head + NOTICE + "\n## " + HEADING + "\n- [EV-1] 資料 https://example.invalid/a"
    b = head + "## " + HEADING + "\n- [EV-2] 別の資料 https://example.invalid/b"
    p = D.similarity_profile(a, b, rules)
    assert p["body_only"] > 0.8 and p["reading"] == "substantive"


def test_a_gate_finding_is_never_removed_by_the_context():
    arts = corpus(distinct)
    before = [f.detail for f in checks.find_overused_phrases(arts)]
    D.classify_repeats(arts, D.load_rules(RULES))
    assert [f.detail for f in checks.find_overused_phrases(arts)] == before and before
