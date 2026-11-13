"""SELF_TEST (Claude, the author) of the candidate-profile extension of the interview sandbox.  SYNTHETIC_ONLY: invented people, invented documents, a deterministic mock.

This is the author's own check, NOT an independent QA, NOT an acceptance of the sandbox or of any M1 gate.  It runs no model and no network, writes no file, reads no real data.
It covers the seven steps (input a profile -> questions from it -> answers -> follow-ups -> end -> feedback tied to the answer -> retry) and the failure modes of the instruction:
unsupported official claims, fabricated motives/activities, unrelated or endless follow-ups, duplicate events and cut-off sessions, personal data kept or logged, and outside communication.
"""
import builtins
import io
import json
import logging
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import InterviewSession, compare, get_case  # noqa: E402
from interview_sandbox import profile as prof  # noqa: E402
from interview_sandbox.__main__ import main as cli_main, run  # noqa: E402

MOTIVATION = "私は地域の図書館で子どもの読み聞かせを手伝った経験から、情報の届け方に関心を持ちました。大学では、誰もが使いやすい情報の探し方を研究したいと考えています。"
ACTIVITIES = [
    {"title": "地域図書館の読み聞かせボランティア", "role": "運営補助", "description": "毎週土曜日に絵本の選定を手伝いました。参加者が減った時期に、案内の掲示を作り直しました。"},
    {"title": "探究学習の発表", "description": "校内の発表会で資料づくりを担当しました。"},
]
ANSWERS = [
    "読み聞かせの手伝いで、本の紹介の仕方によって子どもの反応が変わると気づいたからです。",
    "毎週土曜日に絵本を選び、案内の掲示を作り直したところ、参加者が増えました。",
    "掲示の文字を大きくし、絵を添えました。",
    "情報の探し方を研究し、誰でも使える案内を作りたいと考えています。",
]
TEMPLATES = [
    re.compile(r"あなたが入力した志望理由書に「(.+)」とあります。そう考えるようになった具体的な出来事やきっかけを教えてください。"),
    re.compile(r"あなたが入力した志望理由書に「(.+)」とあります。入学後、具体的に何をどのように学びたいですか。"),
    re.compile(r"あなたが入力した活動情報に「(.+)」とあります。その活動で、あなた自身が果たした役割と、そこで学んだことを具体的に話してください。"),
    re.compile(r"あなたが入力した活動情報の「(.+)」について、うまくいかなかった点や工夫した点があれば教えてください。"),
]


def profile(motivation=MOTIVATION, activities=ACTIVITIES):
    return prof.build_profile(motivation, activities)


def session(p=None, case="fiction-ac-1", variant=0):
    return InterviewSession(get_case(case), variant=variant, profile=p if p is not None else profile())


def drive(s, answers, *, secs=20, limit=40):
    """Answer until the session ends or the answers run out.  Returns the number of answers given."""
    turn, n = s.start(), 0
    while turn is not None and s.state == "in_progress" and n < limit:
        a = answers[n % len(answers)] if answers else "はい。"
        r = s.answer(turn.turn_id, a, secs)
        assert r.accepted
        turn, n = r.next_turn, n + 1
    return n


def quotes_of(text):
    return re.findall(r"「([^」]*)」", text)


def whole_text(p):
    return p.motivation + "\n" + "\n".join(e.title + "\n" + e.description for e in p.activities)


# ------------------------------------------------------------------ the seven steps, end to end
def test_P1_the_whole_practice_runs_from_a_profile_and_back_again_with_a_retry():
    p = profile()                                                      # 1 input
    s = session(p)
    assert "あなたが入力した志望理由書・活動情報" in s.briefing().text()  # the person is told that their own words are quoted and not kept
    first = s.start()                                                  # 2 questions made from the profile
    assert first.origin == "document_based" and first.doc_ref is not None
    n = drive(session(p), ANSWERS)                                     # (a complete run in a second session of the same profile)
    s2 = session(p)
    turn, given = s2.start(), 0
    kinds = [turn.origin]
    while turn is not None and s2.state == "in_progress":               # 3 answers  4 follow-ups
        r = s2.answer(turn.turn_id, ANSWERS[given % len(ANSWERS)], 20)
        turn, given = r.next_turn, given + 1
        if turn:
            kinds.append(turn.origin)
    assert "document_based" in kinds and "follow_up_to_the_answer" in kinds and given == n
    assert s2.state == "ended" and s2.end_reason in ("all_questions_asked", "time_up")   # 5 the end
    report = s2.feedback()                                             # 6 feedback tied to the answer
    cand = {t.turn_id: t.text for t in s2.turns if t.role == "candidate"}
    for item in report.items:
        if item.evidence and not item.evidence.redacted:
            assert item.evidence.text in cand[item.evidence.turn_id]   # the evidence is the person's own words, at the place stated
            assert cand[item.evidence.turn_id][item.evidence.start:item.evidence.end] == item.evidence.text
    again = s2.retry()                                                 # 7 a retry with the same conditions AND the same profile
    assert again is not s2 and again.profile is p and again.state == "setup"
    drive(again, ANSWERS)
    assert again.turns[0].text == s2.turns[0].text                       # the same first question: the same conditions
    assert isinstance(compare(report, again.feedback()), dict)


def test_P2_the_same_profile_and_answers_always_give_the_same_questions():
    runs = []
    for _ in range(2):
        s = session()
        drive(s, ANSWERS)
        runs.append([t.text for t in s.turns])
    assert runs[0] == runs[1]


def test_P3_without_a_profile_nothing_changes():
    s = InterviewSession(get_case("fiction-ac-1"))
    t = s.start()
    assert t.origin == "ai_practice_material" and t.doc_ref is None and "あなたが入力した" not in s.briefing().text()


# ------------------------------------------------------------------ 大学公式情報の根拠なき断言／志望理由・活動の捏造
def test_P4_every_document_question_is_a_fixed_template_around_the_persons_own_words():
    p = profile()
    for case in ("fiction-ac-1", "fiction-rec-2", "fiction-gen-3"):
        for variant in (0, 1):
            s = session(p, case, variant)
            drive(s, ANSWERS)
            for t in s.turns:
                if t.origin != "document_based":
                    continue
                m = [x.fullmatch(t.text) for x in TEMPLATES]
                assert any(m), t.text                                      # nothing but a fixed template: no invented detail
                for q in quotes_of(t.text):
                    assert q in whole_text(p)                              # the quote is verbatim from what the person wrote
                part, a, b = t.doc_ref
                assert part and 0 <= a < b                                 # and where it came from is recorded


def test_P5_the_tool_adds_no_official_fact_and_no_claim_of_its_own():
    base = InterviewSession(get_case("fiction-ac-1")).briefing()
    withp = session().briefing()
    assert withp.conditions == base.conditions and withp.unknown == base.unknown   # official facts come from the case only, never from the profile
    s = session(profile("面接は必ず10分です。大学の公式発表では倍率は3倍だと聞きました。私は図書館の活動から情報に関心を持ちました。", []))
    drive(s, ANSWERS)
    asked = " ".join(t.text for t in s.turns if t.role == "interviewer" and t.origin == "document_based")
    assert "倍率" not in asked and "必ず10分" not in asked                   # a claim the person made about the university is not repeated as if it were a fact
    assert all(q in "私は図書館の活動から情報に関心を持ちました" or q in whole_text(s.profile) for q in quotes_of(asked))


def test_P6_sentences_with_forbidden_claims_sensitive_topics_or_contact_details_are_never_quoted():
    text = "家庭の事情で進路に悩みましたが、図書館で働く人に出会いました。この方法なら合格できます。連絡は taro.invented@example.com まで。私は情報の届け方に関心があります。"
    s = session(profile(text, []))
    drive(s, ANSWERS)
    asked = " ".join(t.text for t in s.turns if t.role == "interviewer")
    for bad in ("家庭の事情", "合格できます", "taro.invented", "example.com", "["):
        assert bad not in asked
    assert any("情報の届け方" in t.text for t in s.turns if t.origin == "document_based")      # a safe sentence of the same profile is still used


def test_P7_a_profile_with_nothing_safe_to_quote_falls_back_to_the_invented_case_question():
    s = session(profile("家庭の事情と持病のことを書きます。合格できます。", []))
    t = s.start()
    assert t.origin == "ai_practice_material" and t.doc_ref is None


# ------------------------------------------------------------------ 回答と関係のない追質問／過剰・無限の追質問
def test_P8_every_follow_up_quotes_words_the_person_just_wrote():
    s = session()
    drive(s, ["いろいろ頑張りました。", "地域の活動に参加して学びました。", "とてもよい経験でした。", "なんとなく関心がありました。"])
    by_id = {t.turn_id: t for t in s.turns}
    ups = [t for t in s.turns if t.origin == "follow_up_to_the_answer"]
    assert ups
    for f in ups:
        cand = by_id[f.followup_of]
        assert cand.role == "candidate" and f.quote and cand.text[f.quote[0]:f.quote[1]] in f.text


def test_P9_follow_ups_and_the_whole_session_are_bounded_even_for_endless_vague_answers():
    s = session()
    n = drive(s, ["いろいろ頑張りました。"], secs=1, limit=500)
    plan = s.context.plan
    ups = [t for t in s.turns if t.origin == "follow_up_to_the_answer"]
    assert len(ups) <= plan.max_total_followups and s.state == "ended" and n < 500
    per_q = {}
    for t in ups:
        per_q[t.question_id] = per_q.get(t.question_id, 0) + 1
    assert all(c <= plan.max_followups_per_question for c in per_q.values())


def test_P10_many_activities_do_not_make_the_session_longer():
    many = [{"title": f"活動{i}の取り組み", "description": f"活動{i}を担当しました。"} for i in range(prof.MAX_ACTIVITIES)]
    a = session(profile(MOTIVATION, many))
    b = session(profile(MOTIVATION, []))
    na, nb = drive(a, ANSWERS), drive(b, ANSWERS)
    assert sum(1 for t in a.turns if t.role == "interviewer" and t.origin == "document_based") <= len(a.context.plan.categories)
    assert na <= len(a.context.plan.categories) + a.context.plan.max_total_followups and nb <= len(b.context.plan.categories) + b.context.plan.max_total_followups


# ------------------------------------------------------------------ 二重イベント・途中切断
def test_P11_a_duplicate_a_stale_or_a_late_answer_changes_nothing():
    s = session()
    t = s.start()
    r = s.answer(t.turn_id, ANSWERS[0], 20)
    assert r.accepted
    count = len(s.turns)
    dup = s.answer(t.turn_id, ANSWERS[0], 20)                             # the same turn answered twice
    assert not dup.accepted and dup.rejected_reason == "duplicate_or_stale_turn" and len(s.turns) == count
    assert not s.answer("no-such-turn", "x", 1).accepted
    s.end("user")
    late = s.answer(r.next_turn.turn_id if r.next_turn else t.turn_id, "x", 1)
    assert not late.accepted and s.state == "ended"
    assert s.rejected_events >= 3


def test_P12_a_session_cut_off_after_the_first_question_still_gives_an_honest_feedback_and_a_retry():
    s = session()
    t = s.start()
    s.answer(t.turn_id, ANSWERS[0], 20)
    s.end("connection_lost")
    report = s.feedback()
    assert report.ended_because == "connection_lost"
    note = next(n for n in report.notes if "質問されなかった分野" in n)
    asked_part = note.split("。")[0]
    assert "志望理由" not in asked_part and "これまでの活動" not in asked_part and "学びたいこと" in asked_part   # the two questions already asked (both document-based) count as asked
    assert s.retry().start().origin == "document_based"
    with pytest.raises(RuntimeError):
        session().feedback()                                               # no feedback while the session is still open


# ------------------------------------------------------------------ 個人情報・保存・ログ・外部通信
def test_P13_personal_data_shapes_are_masked_when_the_profile_is_accepted_and_never_logged(caplog):
    secret = "taro.invented@example.com"
    p = profile("私は読み聞かせに関心があります。連絡先は " + secret + " と 090-1234-5678 です。", [{"title": "ボランティア（連絡 090-1234-5678）", "description": "掲示を作りました。"}])
    blob = whole_text(p)
    assert secret not in blob and "090-1234-5678" not in blob and "[メール]" in blob and "[電話番号]" in blob
    with caplog.at_level(logging.DEBUG):
        s = session(p)
        s.briefing()
        drive(s, ["私の電話は 080-9999-0000 です。読み聞かせが好きです。"])
        s.feedback()
    log = caplog.text
    for word in ("読み聞かせ", "図書館", "taro.invented", "090-1234", "080-9999", "ボランティア"):
        assert word not in log                                             # counts and codes only: neither the profile nor an answer is logged
    out = s.feedback().text()
    assert "080-9999" not in out and "taro.invented" not in out


def test_P14_nothing_is_written_to_disk_and_nothing_goes_out_on_the_network(monkeypatch):
    real_open = builtins.open

    def guarded_open(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            raise AssertionError(f"the sandbox tried to write {file!r}")
        return real_open(file, mode, *a, **k)

    def no_net(*a, **k):
        raise AssertionError("the sandbox tried to use the network")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", no_net)
    s = session()
    s.briefing()
    drive(s, ANSWERS)
    s.feedback()
    s.retry()


def test_P15_a_profile_is_kept_in_memory_only_and_can_not_switch_persistence_on():
    s = session()
    assert not hasattr(s, "save") and s.config.persist is False
    with pytest.raises(NotImplementedError):
        InterviewSession(get_case("fiction-ac-1"), config=__import__("interview_sandbox.models", fromlist=["x"]).SessionConfig(persist=True), profile=profile())


# ------------------------------------------------------------------ 入力の検証
@pytest.mark.parametrize("motivation", ["", "   ", None, 5, True, ["x"], "あ" * (prof.MAX_MOTIVATION_CHARS + 1)])
def test_P16_a_bad_motivation_is_refused(motivation):
    with pytest.raises(ValueError):
        prof.build_profile(motivation, [])


@pytest.mark.parametrize("activities", [
    [{"title": "x"}] * (prof.MAX_ACTIVITIES + 1), "text", [("title", "x")], [{"title": ""}], [{"title": 5}], [{"title": "x", "salary": "1"}], [{"title": "あ" * (prof.MAX_FIELD_CHARS + 1)}], [{"title": "x", "description": None}],
])
def test_P17_bad_activities_are_refused(activities):
    with pytest.raises(ValueError):
        prof.build_profile(MOTIVATION, activities)


def test_P18_the_engine_accepts_only_a_validated_profile():
    for bad in ("motivation text", {"motivation": "x"}, MOTIVATION):
        with pytest.raises(TypeError):
            InterviewSession(get_case("fiction-ac-1"), profile=bad)


# ------------------------------------------------------------------ the command line
def test_P19_the_command_line_runs_with_a_profile_file_and_changes_nothing(tmp_path):
    pf = tmp_path / "profile.json"
    pf.write_text(json.dumps({"motivation": MOTIVATION, "activities": ACTIVITIES}, ensure_ascii=False), encoding="utf-8")
    sc = tmp_path / "answers.txt"
    sc.write_text("\n".join(ANSWERS) + "\n", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert cli_main(["--case", "fiction-ac-1", "--profile", str(pf), "--script", str(sc)]) == 0
    out = io.StringIO()                                                   # the printed text, captured through run() with the same profile
    assert run("fiction-ac-1", list(ANSWERS), out=out, profile=profile()) == 0
    assert "あなたが入力した" in out.getvalue() and "練習のフィードバック" in out.getvalue()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before   # nothing was written next to the inputs


def test_P20_the_command_line_refuses_a_profile_file_with_other_keys(tmp_path):
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps({"motivation": MOTIVATION, "name": "x"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli_main(["--profile", str(pf)])
