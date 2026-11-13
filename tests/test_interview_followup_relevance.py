"""SELF_TEST (Claude, the author): is the follow-up question RELATED to the question that was asked and to what the person just said?  SYNTHETIC_ONLY, deterministic, no network.  Not an independent QA.

Found by probing, with plausible answers, which follow-up each (question category x answer) pair gets (PR #251's document-based questions made the problem visible, but the heuristic is the engine's own):
  * "what was YOUR ROLE?" was asked after an answer about what the person wants to LEARN (a wish for the future has no role);
  * it was asked again right after the person had said "私は絵本の選定を担当し…" (the role was already stated);
  * "参加者が増えました" (a RESULT) matched the keyword 参加 and was treated like "I took part in an activity".
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import InterviewSession, get_case  # noqa: E402
from interview_sandbox import profile as prof  # noqa: E402

MOTIVATION = "私は地域の図書館で子どもの読み聞かせを手伝った経験から、情報の届け方に関心を持ちました。大学では、誰もが使いやすい情報の探し方を研究したいと考えています。"
ACTIVITIES = [{"title": "地域図書館の読み聞かせボランティア", "role": "運営補助", "description": "毎週土曜日に絵本の選定を手伝いました。参加者が減った時期に、案内の掲示を作り直しました。"}]
ROLE_Q = "あなた自身が果たした役割は何でしたか"
REASON_Q = "と考えた理由を教えてください"
CONCRETE_Q = "具体的にはどのような場面や数字で示せますか"
DETAIL_Q = "きっかけや経過をもう少し詳しく話してください"


def follow_up(category, answer, *, with_profile=True, case="fiction-ac-1"):
    """Open the first question of `category` (the earlier categories are answered with a bare 'はい。'), answer it, and return the interviewer's next turn."""
    p = prof.build_profile(MOTIVATION, ACTIVITIES) if with_profile else None
    s = InterviewSession(get_case(case), profile=p)
    t = s.start()
    for _ in range(30):
        if s.context.plan.categories[s._category_index] == category and t.origin != "follow_up_to_the_answer":
            break
        t = s.answer(t.turn_id, "はい。", 5).next_turn
        assert t is not None, "category not reached"
    r = s.answer(t.turn_id, answer, 10)
    assert r.accepted
    return r.next_turn, s


LEARN = ["情報の探し方を研究し、誰でも使える案内の方法を学びたいです。", "利用者が迷わない検索の仕組みについて、大学の授業で学びたいと考えています。", "情報の整理の仕方を体系的に学び、将来は図書館の案内に生かしたいです。",
         "大学では地域の活動に参加しながら研究をしたいです。", "課外活動に取り組みたいです。"]


@pytest.mark.parametrize("with_profile", [True, False])
@pytest.mark.parametrize("answer", LEARN)
def test_F1_a_question_about_what_the_person_wants_to_learn_never_gets_a_what_was_your_role_follow_up(answer, with_profile):
    nxt, _s = follow_up("学びたいこと", answer, with_profile=with_profile)
    assert nxt is None or ROLE_Q not in nxt.text


@pytest.mark.parametrize("answer", ["私は絵本の選定を担当し、参加者の反応を見て案内の掲示を作り直しました。", "運営の補助として、受付の活動に取り組みました。", "委員長として大会の運営に参加しました。",
                                    "リーダーを務めた探究活動で、発表の準備をしました。"])
def test_F2_the_role_is_not_asked_again_after_the_person_has_said_it(answer):
    nxt, _s = follow_up("これまでの活動", answer)
    assert nxt is None or ROLE_Q not in nxt.text


def test_F3_a_result_that_contains_the_word_participants_is_not_taken_for_taking_part():
    nxt, _s = follow_up("これまでの活動", "毎週土曜日に絵本を選び、掲示を作りました。参加者が増えて嬉しかったです。")
    assert nxt is None or ROLE_Q not in nxt.text


@pytest.mark.parametrize("answer", ["高校の部活動に取り組みました。", "市の大会に参加しました。", "人との関係を大切にしながら、ボランティアに参加しました。", "探究の授業で調べ学習をしました。研究の発表もしました。"])
def test_F4_an_activity_answer_that_does_not_say_what_the_persons_part_was_still_gets_the_role_question(answer):
    nxt, _s = follow_up("これまでの活動", answer)
    assert nxt is not None and nxt.origin == "follow_up_to_the_answer" and ROLE_Q in nxt.text           # 関係 (relationship) must not count as the role word 係


def test_F5_the_follow_up_focus_follows_the_answer_and_always_quotes_it():
    shapes = {
        CONCRETE_Q: "いろいろな活動を頑張りました。",
        ROLE_Q: "高校の部活動に取り組みました。",
        REASON_Q: "地域の図書館で本の案内を見て、情報の届け方を大切だと感じました。",
        DETAIL_Q: "本が好きだからです。",                     # a reason is given but the answer is short: ask for the course of events, not for the reason again
    }
    got = {}
    for expected, answer in shapes.items():
        nxt, s = follow_up("これまでの活動", answer)
        assert nxt is not None and nxt.origin == "follow_up_to_the_answer" and expected in nxt.text, (answer, nxt and nxt.text)
        cand = [t for t in s.turns if t.turn_id == nxt.followup_of][0]
        assert nxt.text.startswith("「" + cand.text[nxt.quote[0]:nxt.quote[1]] + "」")                  # it quotes exactly the words just said, and says where they are
        got[expected] = nxt.text
    assert len(set(got.values())) == 4                                                                  # four different answers, four different questions
