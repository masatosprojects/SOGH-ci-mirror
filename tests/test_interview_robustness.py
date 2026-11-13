"""SELF_TEST (Claude, the author): hostile and odd input for the interview sandbox — very long text, control and invisible characters, right-to-left and combining marks, lone surrogates.
SYNTHETIC_ONLY, deterministic, no network, no files.  Not an independent QA and not an acceptance.

Found while writing these (and fixed with them):
  * guards.mask_personal took ~6 s for ONE answer of 20,000 characters (the e-mail pattern is quadratic on a long run of word characters) -> an answer is limited to guards.MAX_ANSWER_CHARS
    and refused before any scanning; the profile fields are limited the same way.
  * a zero-width character inside 合格できます hid the claim from the claim guard -> control / invisible / bidi / surrogate / private-use characters are removed BEFORE any guard runs.
  * an escape sequence in an answer reached the terminal when the answer was quoted back -> same cleaning.
"""
import io
import sys
import time
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import InterviewSession, get_case, guards  # noqa: E402
from interview_sandbox import profile as prof  # noqa: E402
from interview_sandbox.__main__ import run  # noqa: E402

ESC = chr(27)
NUL = chr(0)
BEL = chr(7)
ZW = "​"
RLO = "‮"
BOM = "﻿"
LRI = "⁦"
LONE = "\ud800"
BAD_CATS = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")


def invisible(text):
    return [c for c in text if c not in "\n\t" and unicodedata.category(c) in BAD_CATS]


def start(profile=None, case="fiction-ac-1"):
    s = InterviewSession(get_case(case), profile=profile)
    return s, s.start()


def everything_shown(s):
    texts = [t.text for t in s.turns] + [s.briefing().text()]
    if s.state == "ended":
        texts.append(s.feedback().text())
    return "\n".join(texts)


# ------------------------------------------------------------------ very long text
def test_H1_an_answer_over_the_limit_is_refused_at_once_and_the_question_stays_open():
    s, t = start()
    big = "あ" * (guards.MAX_ANSWER_CHARS + 1)
    began = time.perf_counter()
    r = s.answer(t.turn_id, big, 10)
    assert time.perf_counter() - began < 0.5
    assert not r.accepted and r.rejected_reason == "answer_too_long" and s.rejected_events == 1 and s.state == "in_progress"
    ok = s.answer(t.turn_id, "図書館での活動から、情報の届け方に関心を持ちました。", 10)    # the same question can still be answered, shortly
    assert ok.accepted


def test_H2_ten_million_characters_cost_no_time_at_all():
    s, t = start()
    began = time.perf_counter()
    assert not s.answer(t.turn_id, "a" * 10_000_000, 1).accepted
    assert time.perf_counter() - began < 0.5


def test_H3_an_answer_of_exactly_the_limit_is_processed_in_bounded_time_even_if_it_is_the_worst_case_for_the_masker():
    for worst in ("a" * guards.MAX_ANSWER_CHARS, "a." * (guards.MAX_ANSWER_CHARS // 2), "1-" * (guards.MAX_ANSWER_CHARS // 2)):
        s, t = start()
        began = time.perf_counter()
        r = s.answer(t.turn_id, worst, 10)
        assert r.accepted and time.perf_counter() - began < 5.0


def test_H4_a_session_of_maximum_size_inputs_ends_in_bounded_time():
    many = [{"title": "活動" + str(i) + "の取り組み" + "あ" * 250, "description": "担当しました。" * 40} for i in range(prof.MAX_ACTIVITIES)]
    p = prof.build_profile(("私は図書館の活動から情報に関心を持ちました。" * 70)[:prof.MAX_MOTIVATION_CHARS], many)
    s, t = start(p)
    began, turn, n = time.perf_counter(), t, 0
    while turn is not None and s.state == "in_progress" and n < 40:
        r = s.answer(turn.turn_id, ("いろいろ頑張りました。" * 360)[:guards.MAX_ANSWER_CHARS], 1)
        assert r.accepted
        turn, n = r.next_turn, n + 1
    assert s.state == "ended" and n < 40 and time.perf_counter() - began < 20.0
    s.feedback()


@pytest.mark.parametrize("field", ["motivation", "title", "description", "role"])
def test_H5_huge_profile_fields_are_refused_immediately(field):
    huge = "あ" * 5_000_000
    began = time.perf_counter()
    with pytest.raises(ValueError):
        if field == "motivation":
            prof.build_profile(huge, [])
        else:
            prof.build_profile("私は読み聞かせに関心があります。", [{"title": "x", field: huge}] if field != "title" else [{"title": huge}])
    assert time.perf_counter() - began < 1.0


# ------------------------------------------------------------------ control and invisible characters
def test_H6_clean_text_removes_exactly_the_invisible_kinds_and_keeps_text():
    text = "日本語" + ESC + "[31m" + ZW + RLO + BOM + LRI + LONE + NUL + BEL + " " + "abc\nデータ\t終わり😀"
    clean, n = guards.clean_text(text)
    assert not invisible(clean) and n == 9                                # ESC, ZW, RLO, BOM, LRI, lone surrogate, NUL, BEL, U+2028
    assert clean == "日本語[31mabc\nデータ\t終わり😀"                       # letters, line break, tab, kana, emoji stay
    assert guards.clean_text("")[1] == 0 and guards.clean_text("普通の文章。") == ("普通の文章。", 0)


def test_H7_control_characters_in_an_answer_never_reach_anything_that_is_shown():
    s, t = start()
    r = s.answer(t.turn_id, "いろいろ" + ESC + "[2J" + ESC + "[31m頑張りました" + BEL + "。" + NUL, 10)
    assert r.accepted and "control_characters_removed" in [n.code for n in r.notices]
    turn = r.next_turn
    for _ in range(3):
        if turn is None:
            break
        turn = s.answer(turn.turn_id, "活動に参加" + ESC + "し" + ZW + "ました。", 10).next_turn
    if s.state != "ended":
        s.end("closed")
    shown = everything_shown(s)
    assert not invisible(shown) and ESC not in shown
    assert all(not invisible(t.text) for t in s.turns)


def test_H8_a_zero_width_character_cannot_hide_a_claim_from_the_claim_guard():
    for hidden in ("私は合" + ZW + "格できます。", "私は必" + RLO + "ず聞かれると思います。", "合格" + BOM + "確実です。"):
        s, t = start()
        r = s.answer(t.turn_id, hidden, 10)
        assert r.accepted
        said = " ".join(x.text for x in s.turns if x.role == "interviewer")
        assert "合格できます" not in said and "必ず聞かれ" not in said and "合格確実" not in said     # the claim is not repeated
        assert any(n.code == "claim_not_repeated" for n in s.notices)                                  # and the person is told so


def test_H9_a_lone_surrogate_does_not_crash_the_command_line_output():
    out = io.StringIO()
    code = run("fiction-ac-1", ["図書館" + LONE + "での活動" + "\udfff" + "に参加しました。", "掲示を作り直しました。"], out=out)
    assert code == 0
    out.getvalue().encode("utf-8")                                         # printing it would have raised UnicodeEncodeError with the surrogate in it


def test_H10_the_profile_is_cleaned_the_same_way_and_the_questions_stay_clean():
    p = prof.build_profile("私は" + RLO + "地域の図書館" + ZW + "での手伝いから、" + ESC + "情報の届け方に関心を持ちました。", [{"title": "読み聞かせ" + BOM + "ボランティア", "description": "毎週" + NUL + "手伝いました。"}])
    assert not invisible(p.motivation) and not invisible(p.activities[0].title) and not invisible(p.activities[0].description)
    s, t = start(p)
    assert t.origin == "document_based" and not invisible(t.text)
    assert "地域の図書館での手伝い" in t.text or "情報の届け方に関心" in t.text


def test_H11_the_claim_guard_also_sees_through_invisible_characters_in_the_profile():
    p = prof.build_profile("この方法なら合" + ZW + "格できます。私は情報の届け方に関心があります。", [])
    s, _t = start(p)
    said = " ".join(x.text for x in s.turns if x.role == "interviewer")
    assert "合格できます" not in said and "情報の届け方" in said


# ------------------------------------------------------------------ other scripts, combining marks, emoji
@pytest.mark.parametrize("text", [
    "أنا أحب المكتبة وأريد أن أدرس علم المعلومات.",                        # Arabic (right to left)
    "אני אוהב ספריות ורוצה ללמוד מידע.",                                 # Hebrew
    "ฉันชอบห้องสมุดและอยากเรียนสารสนเทศ",                                # Thai (no spaces)
    "図書館📚での活動👨‍👩‍👧に参加しました😀。",                              # emoji, with joiners
    "a" + "́" * 300 + "。",                                         # a long stack of combining marks
    "ＡＢＣ１２３　全角と半角ｱｲｳ。",                                      # full-width and half-width
])
def test_H12_other_scripts_do_not_crash_are_deterministic_and_stay_bounded(text):
    results = []
    for _ in range(2):
        s, t = start()
        r = s.answer(t.turn_id, text, 10)
        assert r.accepted
        shown = [x.text for x in s.turns]
        assert not invisible("".join(shown)) and all(len(x) < 600 for x in shown)
        results.append(shown)
    assert results[0] == results[1]


def test_H13_a_bidi_override_cannot_reorder_a_quoted_sentence_on_screen():
    s, t = start()
    r = s.answer(t.turn_id, "私は" + RLO + "ですます。いろいろ頑張りました。", 10)
    assert r.accepted
    quoted = [x.text for x in s.turns if x.origin == "follow_up_to_the_answer"]
    assert all(RLO not in q for q in quoted)


# ------------------------------------------------------------------ types
@pytest.mark.parametrize("bad", [None, 5, b"bytes", ["x"], True])
def test_H14_an_answer_that_is_not_text_is_refused_without_changing_the_session(bad):
    s, t = start()
    n = len(s.turns)
    with pytest.raises(ValueError):
        s.answer(t.turn_id, bad, 10)
    assert len(s.turns) == n and s.state == "in_progress" and s.answer(t.turn_id, "掲示を作りました。", 10).accepted


# ------------------------------------------------------------------ the claim patterns (found by measuring every guard on its worst input)
def test_H15_a_claim_word_followed_by_a_long_run_of_blanks_costs_linear_time():
    # before the fix three adjacent whitespace quantifiers in the 合格率 pattern made this cubic: 1,000 blanks took 2 s, 2,000 took 18 s, 4,000 would have taken minutes
    began = time.perf_counter()
    assert guards.forbidden_claims_in("合格率" + " " * (guards.MAX_ANSWER_CHARS - 3)) == []
    s, t = start()
    assert s.answer(t.turn_id, "合格率" + "　" * (guards.MAX_ANSWER_CHARS - 3), 10).accepted
    assert time.perf_counter() - began < 5.0


@pytest.mark.parametrize("claim", ["合格率は80%です", "合格率 約 8割", "合格率：９０", "合格確率が　およそ　5", "合格可能性 は 約 3", "合格率\n\t1"])
def test_H16_the_fixed_pattern_still_catches_every_spacing_of_a_stated_rate(claim):
    assert guards.forbidden_claims_in(claim)


@pytest.mark.parametrize("text", ["合格率は高いと聞きました", "合格率について調べました", "合格率 は", "合格率"])
def test_H17_a_rate_word_without_a_number_is_not_a_claim(text):
    assert guards.forbidden_claims_in(text) == []


def test_H18_no_guard_is_slow_on_the_worst_input_it_can_be_given_at_the_answer_limit():
    n = guards.MAX_ANSWER_CHARS
    worst = ["合格率" + " " * n, "1" * n, "0-" * (n // 2), "a@" * (n // 2), "http://" + "a" * n, "www." * (n // 4), "〒1" * (n // 2), "必ず出題" * (n // 4),
             "合格できます" + "あ" * n, "再現度" + " " * n, "1" + " " * n + "点", "@" * n, "あ" * n, "(at)" * (n // 4)]
    for text in worst:
        text = text[:n]
        for fn in (guards.forbidden_claims_in, guards.mask_personal, guards.has_personal, guards.sensitive_in):
            began = time.perf_counter()
            fn(text)
            assert time.perf_counter() - began < 5.0, (fn.__name__, text[:12])
