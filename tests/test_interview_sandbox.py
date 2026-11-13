"""Acceptance tests of the interview sandbox (Issue #75, v0). SYNTHETIC_ONLY: invented universities, invented answers, a deterministic mock.
A pass here is not a result with real candidates, not a measure of interview quality, and not part of the M1 gates.
"""
import ast
import io
import logging
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import CASES, InterviewSession, compare, get_case  # noqa: E402
from interview_sandbox import guards  # noqa: E402
from interview_sandbox.__main__ import run  # noqa: E402
from interview_sandbox.engine import DISCLAIMERS, analysable  # noqa: E402
from interview_sandbox.feedback import NOT_ENOUGH, RUBRIC, STAGES  # noqa: E402
from interview_sandbox.models import ExperienceReport, InterviewContext, OfficialFact, SessionConfig  # noqa: E402

GOOD = "私は高校の探究活動で、地域の防災について研究しました。例えば、3か月間で50人にアンケートを行い、その結果、避難経路の認知が低いと分かりました。大学では防災の社会学を学びたいです。なぜなら、研究で見えた課題を政策につなげたいからです。"
VAGUE = "私はいろいろな活動を頑張りました。とても楽しかったです。"
LATER = "防災の研究では私は調査の担当でした。その調査の経験から、地域の課題を学びたいと考えました。"


def drive(ctx_or_id, answers, elapsed=30, session=None):
    s = session or InterviewSession(get_case(ctx_or_id) if isinstance(ctx_or_id, str) else ctx_or_id)
    t = s.start()
    for a in answers:
        if s.state != "in_progress":
            break
        r = s.answer(t.turn_id, a, elapsed)
        t = r.next_turn
    if s.state == "in_progress":
        s.end("test")
    return s


def all_text(s):
    return "\n".join([s.briefing().text()] + [t.text for t in s.turns if t.role == "interviewer"] + [s.feedback().text()])


# ---------------------------------------------------------------------------------------------------------------- 1: invented cases
def test_there_are_three_invented_cases_of_different_kinds_and_none_names_a_real_university():
    assert set(CASES) == {"fiction-ac-1", "fiction-rec-2", "fiction-gen-3"}
    for cid in CASES:
        c = get_case(cid)
        assert "架空" in c.university and "架空" in c.method and all("架空" in f.source_version for f in c.official_facts)
    assert get_case("fiction-gen-3").interview_is_official is False and get_case("fiction-ac-1").interview_is_official is True
    with pytest.raises(KeyError):
        get_case("a-real-university")


def test_the_four_kinds_of_content_are_separate_types_and_an_unknown_fact_is_never_filled_in():
    with pytest.raises(ValueError):
        OfficialFact("x", "面接の時間", "約10分", "unknown", "架空要項 v1")  # unknown with a value: a guess
    with pytest.raises(ValueError):
        OfficialFact("x", "面接の時間", None, "confirmed", "架空要項 v1")
    c = get_case("fiction-ac-1")
    assert c.fact("second_stage_date").status == "unknown" and c.fact("second_stage_date").value is None
    assert {f.kind for f in c.official_facts} == {"official_fact"} and {r.kind for r in c.experience_reports} == {"experience_report"}
    assert {q.kind for q in c.practice_questions} == {"ai_practice_material"}


# ---------------------------------------------------------------------------------------------------------------- 2: conditions and briefing
def test_the_briefing_separates_confirmed_unknown_experience_and_the_disclaimers():
    b = get_case("fiction-ac-1")
    text = InterviewSession(b).briefing().text()
    assert "面接の時間：約10分（架空要項 v1" in text and "第2次選考の日程：公式には確認できていません" in text and "評価の観点：公式には確認できていません" in text
    assert "公式情報ではありません" in text and "1件のみ。傾向とは言えません" in text
    assert all(d in text for d in DISCLAIMERS)
    assert text.index("【公式に確認できた条件】") < text.index("【公式には確認できていない事項") < text.index("【受験経験の報告")  # experience is shown apart from the facts


def test_a_method_without_a_confirmed_interview_is_shown_as_general_practice_not_as_the_interview():
    text = InterviewSession(get_case("fiction-gen-3")).briefing().text()
    assert "面接が行われることは確認できていません" in text and "一般的な面接練習" in text


def test_a_question_that_touches_an_official_fact_names_its_pinned_version_or_says_it_is_unknown():
    s = InterviewSession(get_case("fiction-ac-1"))
    first = s.start()
    assert first.basis == ("interview_duration",) and "架空要項 v1" in first.text and "約10分" in first.text and first.origin == "ai_practice_material"
    c = get_case("fiction-ac-1")
    unknown_basis = InterviewContext(c.case_id, c.university, c.faculty, c.method, c.fiscal_year, tuple(f for f in c.official_facts if f.fact_id != "interview_duration") + (OfficialFact("interview_duration", "面接の時間", None, "unknown", "架空要項 v1"),),
                                     (), c.practice_questions, c.plan, True)
    assert "公式には確認できていません" in InterviewSession(unknown_basis).start().text  # never a guessed duration


# ---------------------------------------------------------------------------------------------------------------- 3-5: the flow, follow-ups, limits, time
def test_the_whole_practice_runs_from_the_first_question_to_the_feedback_and_a_retry():
    s = InterviewSession(get_case("fiction-ac-1"))
    t = s.start()
    assert s.state == "in_progress" and t.role == "interviewer"
    r = s.answer(t.turn_id, VAGUE, 40)
    assert r.accepted and r.next_turn.origin == "follow_up_to_the_answer"  # a follow-up on what was said
    a, b = r.next_turn.quote
    assert r.next_turn.text.count(VAGUE[a:b]) == 1 and VAGUE[a:b] in VAGUE  # it quotes the person's own words, and says where
    while s.state == "in_progress":
        t = r.next_turn
        r = s.answer(t.turn_id, LATER, 40)
    assert s.state == "ended" and s.end_reason in ("all_questions_asked", "time_up")
    fb = s.feedback()
    assert fb.answered >= 2 and {i.key for i in fb.items} == {k for k, _ in RUBRIC}
    again = s.retry()
    assert again.state == "setup" and again.context == s.context and again.start().text == s.turns[0].text  # the same conditions, a fresh session


def test_follow_ups_follow_the_content_of_the_answer_and_are_limited_per_question_and_per_session():
    ctx = get_case("fiction-ac-1")
    s = InterviewSession(ctx)
    t = s.start()
    kinds = []
    for _ in range(30):
        r = s.answer(t.turn_id, "いろいろな活動を頑張りました。たくさんの経験をしました。様々な人と関わりました。", 5)
        if r.ended:
            break
        kinds.append(r.next_turn.origin)
        t = r.next_turn
    follow = [k for k in kinds if k == "follow_up_to_the_answer"]
    assert len(follow) <= ctx.plan.max_total_followups
    per_question = {}
    for turn in s.turns:
        if turn.role == "interviewer" and turn.origin == "follow_up_to_the_answer":
            per_question[turn.question_id] = per_question.get(turn.question_id, 0) + 1
    assert per_question and max(per_question.values()) <= ctx.plan.max_followups_per_question
    # a concrete, complete answer is not probed for vagueness
    s2 = InterviewSession(ctx)
    t2 = s2.start()
    r2 = s2.answer(t2.turn_id, GOOD, 40)
    assert r2.next_turn is None or "具体的にはどのような" not in r2.next_turn.text


def test_time_is_counted_and_a_session_ends_after_an_answer_when_time_is_up_never_in_the_middle():
    s = InterviewSession(get_case("fiction-gen-3"))  # 300 seconds
    t = s.start()
    assert s.remaining_seconds == 300
    r = s.answer(t.turn_id, GOOD, 120)
    assert s.remaining_seconds == 180 and not r.ended
    r = s.answer(r.next_turn.turn_id, LATER, 200)
    assert r.ended and r.end_reason == "time_up" and s.state == "ended" and s.remaining_seconds == 0 and r.next_turn is None
    assert s.feedback().answered == 2  # what was answered is still evaluated
    for bad in (-1, 3601, 1.5):
        s2 = InterviewSession(get_case("fiction-gen-3"))
        t2 = s2.start()
        with pytest.raises(ValueError):
            s2.answer(t2.turn_id, GOOD, bad)


def test_a_duplicate_a_stale_or_a_late_event_changes_nothing():
    s = InterviewSession(get_case("fiction-ac-1"))
    t = s.start()
    r1 = s.answer(t.turn_id, GOOD, 30)
    snapshot = (len(s.turns), s.remaining_seconds, s.state)
    dup = s.answer(t.turn_id, "again", 30)  # the same event twice
    assert not dup.accepted and dup.rejected_reason == "duplicate_or_stale_turn" and (len(s.turns), s.remaining_seconds, s.state) == snapshot
    assert not s.answer("someone-else", "x", 1).accepted and s.rejected_events == 2
    s.end("user")
    assert not s.answer(r1.next_turn.turn_id, "late", 1).accepted and not s.end().accepted


# ---------------------------------------------------------------------------------------------------------------- 7-9: feedback grounded in the answer
def test_feedback_ties_each_item_to_the_exact_place_in_the_answer_with_a_concrete_example():
    s = drive("fiction-ac-1", [GOOD, LATER, LATER])
    fb = s.feedback()
    by_id = {t.turn_id: t for t in s.turns}
    for item in fb.items:
        assert item.stage in STAGES or item.stage == NOT_ENOUGH and item.evidence is None
        if item.evidence:
            e = item.evidence
            assert by_id[e.turn_id].text[e.start:e.end] == e.text and by_id[e.turn_id].role == "candidate"  # a quote of the person's words, at a recorded place
            assert e.text in item.improvement or "〇" in item.improvement
    assert fb.stage_of("specificity") == STAGES[2] and fb.stage_of("learning_link") == STAGES[2]
    assert "大学公認" not in fb.text().replace("大学公認でもありません", "") and "練習用のルーブリック" in fb.text()


def test_a_vague_answer_is_marked_for_improvement_with_an_example_that_leaves_blanks_for_the_facts():
    fb = drive("fiction-ac-1", [VAGUE]).feedback()
    spec = next(i for i in fb.items if i.key == "specificity")
    assert spec.stage == STAGES[0] and "いろいろ" in spec.evidence.text and "〇〇" in spec.improvement  # blanks, not invented facts
    import re
    assert not re.search(r"\d", spec.improvement.replace(spec.evidence.text, "").replace("◇", ""))  # no invented number in the example


def test_a_short_first_sentence_made_of_broad_words_is_not_rated_clear_but_a_short_concrete_one_still_is():
    broad = drive("fiction-ac-1", ["私はいろいろ頑張りました。", "たくさん学びました。"]).feedback()
    item = next(i for i in broad.items if i.key == "clarity")
    assert item.stage == STAGES[1] and "広い言葉" in item.why
    concrete = drive("fiction-ac-1", ["私は防災を研究しました。", "調査を担当しました。"]).feedback()
    assert concrete.stage_of("clarity") == STAGES[2]  # the fix does not penalise a short concrete opening
    assert broad.rubric_version == "practice-rubric-v1.2"


def test_what_cannot_be_judged_is_said_so_and_never_counted_as_a_pass_or_a_change():
    empty = drive("fiction-ac-1", []).feedback()
    assert all(i.stage == NOT_ENOUGH for i in empty.items) and empty.answered == 0
    one = drive("fiction-ac-1", [GOOD]).feedback()
    assert one.stage_of("consistency") == NOT_ENOUGH
    assert set(compare(empty, one).values()) == {"比較できません"}


def test_a_retry_with_the_same_conditions_shows_what_improved():
    first = drive("fiction-ac-1", [VAGUE, VAGUE, VAGUE])
    second = drive("fiction-ac-1", [GOOD, LATER, LATER], session=first.retry())
    assert [t.text for t in first.turns if t.role == "interviewer"][0] == [t.text for t in second.turns if t.role == "interviewer"][0]
    delta = compare(first.feedback(), second.feedback())
    assert delta["specificity"] == "改善" and delta["learning_link"] == "改善" and "低下" not in delta.values()


def test_the_same_answers_always_give_the_same_session_and_feedback():
    a, b = drive("fiction-rec-2", [VAGUE, LATER, GOOD]), drive("fiction-rec-2", [VAGUE, LATER, GOOD])
    assert [(t.text, t.origin, t.quote) for t in a.turns] == [(t.text, t.origin, t.quote) for t in b.turns] and a.feedback().text() == b.feedback().text()


# ---------------------------------------------------------------------------------------------------------------- wording guards
def test_the_guard_catches_the_claims_the_product_must_never_make():
    for bad in ("合格確率 80%", "合格率: 80", "合格できます", "大学公認の模擬面接", "完全再現", "再現度95%", "必ず出題されます", "実際の面接と同じです", "この質問が出題されます"):
        assert guards.forbidden_claims_in(bad), bad
    for ok in ("実際に出題される質問とは限りません。", "大学公認でもありません。", "合格・不合格の予測は示しません。"):
        assert not guards.forbidden_claims_in(ok), ok
    assert guards.forbidden_claims_in("この練習は大学公認です")


def test_nothing_the_sandbox_says_makes_a_forbidden_claim_and_nothing_calls_a_question_a_past_exam_question():
    for cid in CASES:
        for answers in ([], [VAGUE], [GOOD, LATER], [VAGUE, VAGUE, VAGUE, VAGUE, VAGUE, VAGUE]):
            text = all_text(drive(cid, answers))
            assert guards.forbidden_claims_in(text) == [] and "過去問" not in text and "傾向" not in text.replace("傾向とは言えません", "") and "頻出" not in text


# ---------------------------------------------------------------------------------------------------------------- safety of what the person writes
def test_a_personal_topic_is_never_probed_nor_quoted_in_the_feedback():
    answer = "家庭の事情で活動を続けられませんでした。私は部活で研究に取り組みました。宗教的な理由で参加できない行事もありました。"
    s = InterviewSession(get_case("fiction-ac-1"))
    t = s.start()
    r = s.answer(t.turn_id, answer, 20)
    assert any(n.code == "sensitive_topic_not_probed" for n in r.notices)
    if r.next_turn is not None and r.next_turn.origin == "follow_up_to_the_answer":  # a follow-up may quote only a sentence that is not about a personal topic
        a, b = r.next_turn.quote
        assert not guards.sensitive_in(answer[a:b])
    assert all("家庭の事情" not in a for a in [x.text for x in s.turns if x.role == "interviewer"])
    s.end("test")
    for item in s.feedback().items:
        assert item.evidence is None or not guards.sensitive_in(item.evidence.text)
    assert all(not guards.sensitive_in(answer[a:b]) for a, b in analysable(answer))


def test_a_phone_number_or_an_address_is_masked_before_it_is_kept_or_quoted_and_is_never_logged(caplog):
    answer = "私の連絡先は090-1234-5678 と taro.yamada@example.com です。研究に取り組みました。"
    with caplog.at_level(logging.DEBUG, logger="interview_sandbox"):
        s = InterviewSession(get_case("fiction-ac-1"))
        t = s.start()
        r = s.answer(t.turn_id, answer, 20)
        s.end("test")
        report = s.feedback().text()
    assert any(n.code == "personal_info_masked" for n in r.notices)
    kept = " ".join(x.text for x in s.turns)
    assert "090-1234-5678" not in kept and "example.com" not in kept and "[電話番号]" in kept and "[メール]" in kept
    assert "090-1234-5678" not in report and "example.com" not in report
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert logged and "研究" not in logged and "090" not in logged and "example" not in logged  # counts and codes only, never an answer's text


# ---------------------------------------------------------------------------------------------------------------- isolation
def test_external_ai_and_persistence_are_off_and_cannot_be_switched_on():
    assert SessionConfig().llm_enabled is False and SessionConfig().persist is False
    with pytest.raises(NotImplementedError):
        SessionConfig(llm_enabled=True)
    with pytest.raises(NotImplementedError):
        SessionConfig(persist=True)


def test_a_whole_session_needs_no_network_and_writes_no_file(monkeypatch, tmp_path):
    def no_socket(*a, **k):
        raise AssertionError("the sandbox must not open a network connection")
    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    s = drive("fiction-ac-1", [GOOD, LATER, VAGUE])
    s.feedback().text()
    assert set(tmp_path.iterdir()) == before


def test_the_package_does_not_import_a_network_database_process_or_vendor_module_and_never_touches_sogh_code():
    banned = {"sqlite3", "socket", "urllib", "http", "requests", "httpx", "subprocess", "anthropic", "openai", "ftplib", "smtplib", "ssl", "shutil", "tempfile"}
    for f in sorted((ROOT / "sandbox" / "interview_sandbox").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods.add(n.module.split(".")[0])
        assert not (mods & banned), (f.name, mods & banned)
        assert "src.db_contract" not in f.read_text(encoding="utf-8") and "research/inbox" not in f.read_text(encoding="utf-8"), f.name
        assert "open(" not in "".join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith(("#", '"""'))) or f.name == "__main__.py"


def test_the_command_line_runs_a_scripted_practice_end_to_end(tmp_path):
    script = tmp_path / "answers.txt"
    script.write_text("\n".join([VAGUE, GOOD, LATER, LATER]) + "\n", encoding="utf-8")
    out = io.StringIO()
    answers = [ln for ln in script.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert run("fiction-ac-1", answers, out=out) == 0
    text = out.getvalue()
    assert "公式に確認できた条件" in text and "面接官（AI 練習用）" in text and "練習のフィードバック" in text and "この評価の限界" in text
    assert guards.forbidden_claims_in(text) == []
