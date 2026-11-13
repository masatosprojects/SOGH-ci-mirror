"""Answer cases for the clarity / specificity items of the practice rubric, and what may be checked about them WITHOUT a person. SYNTHETIC ONLY (every answer is invented).

Why: the rubric computes a stage from visible rules (length, numbers, broad words). A rule cannot tell whether an answer is good. This table separates (a) properties a rule CAN be held to, as
`objective` checks that must keep holding (a number alone never makes an answer concrete; adding words never raises a stage; a long vague first sentence is not clear), from (b) judgements that
need a person (`human_only`): there the mock's stage is recorded as an observation, never as correct. `human_label` is blank on purpose: nobody has rated these cases, and an agreement with the
mock is therefore NOT computed (see evalset.agreement). `stages_by_version` is the history of what each rubric version gave, so a change that makes a case worse is visible and must be justified.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def run_answers(answers: tuple[str, ...], case_id: str = "fiction-ac-1"):
    """Drive the deterministic mock with these answers in order and return (session, feedback). No network, no storage."""
    from interview_sandbox import InterviewSession, get_case
    s = InterviewSession(get_case(case_id))
    turn = s.start()
    for a in answers:
        if s.state != "in_progress":
            break
        turn = s.answer(turn.turn_id, a, 30).next_turn
    if s.state == "in_progress":
        s.end("script_finished")
    return s, s.feedback()


@dataclass(frozen=True)
class AnswerCase:
    case_id: str
    category: str
    answers: tuple[str, ...]  # the person's answers in order (the first one drives `clarity`)
    objective: tuple[str, ...] = ()  # machine-checkable properties (names understood by the tests)
    human_only: str = ""  # what only a person can judge about this case
    human_label: dict = field(default_factory=dict)  # blank: filled by raters, never by the mock
    stages_by_version: dict = field(default_factory=dict)  # version -> {"clarity": stage, "specificity": stage}


C = "practice-rubric-v1.1"
D = "practice-rubric-v1.2"
G, M, B = "できている", "一部できている", "要改善"

CASES: tuple[AnswerCase, ...] = (
    AnswerCase("numeric-vague", "数字だけ含む曖昧な回答", ("いろいろな活動を3回頑張りました。", "たくさん学びました。"),
               objective=("clarity_not_top", "specificity_not_top"), human_only="3回が何の3回かを人が判断する",
               stages_by_version={C: {"clarity": G, "specificity": M}, D: {"clarity": M, "specificity": M}}),
    AnswerCase("concrete", "活動・役割・結果が具体的な回答", ("私は高校の探究活動で防災を研究し、50人にアンケートを行いました。", "調査の担当として、避難経路の認知が低いと分かりました。"),
               objective=("clarity_top", "specificity_not_bottom"), human_only="内容の質（研究の深さ）",
               stages_by_version={C: {"clarity": G, "specificity": M}, D: {"clarity": G, "specificity": M}}),
    AnswerCase("abstract-meaningful", "抽象語が多いが意味のある回答", ("私は、他者の意見を尊重しながら合意を形成する力を大学で学びたいです。", "その力は将来の仕事にも必要だと考えます。"),
               human_only="抽象的でも意味があるかは人が判断する。規則は『広い語』を持たないので上位になり得るが、それが妥当とは言えない",
               stages_by_version={C: {"clarity": G, "specificity": B}, D: {"clarity": G, "specificity": B}}),
    AnswerCase("short-clear", "短いが十分明確な回答", ("私は防災を研究しました。", "調査を担当しました。"),
               objective=("clarity_top",), stages_by_version={C: {"clarity": G, "specificity": B}, D: {"clarity": G, "specificity": B}}),
    AnswerCase("long-vague", "長いが曖昧な回答", ("私はこれまでの高校生活の中で、いろいろな活動にたくさん取り組み、様々な経験をとても頑張って積み重ねてきましたが、その中でも特に色々なことを学べたと思っています。", "これからも頑張りたいです。"),
               objective=("clarity_not_top", "specificity_bottom"),
               stages_by_version={C: {"clarity": M, "specificity": B}, D: {"clarity": M, "specificity": B}}),
    AnswerCase("unfounded-confidence", "根拠のない自信や断定", ("私は絶対に合格できますし、必ず成果を出せます。", "間違いなく役に立てます。"),
               objective=("clarity_not_top", "experience_bottom"), human_only="自信そのものの妥当性は人が判断する",
               stages_by_version={C: {"error": "ValueError: the forbidden-claim guard fired on the person's own words"}, D: {"clarity": M, "specificity": B}}),
    AnswerCase("activity-reason-mismatch", "志望理由と活動内容が合わない回答", ("私は吹奏楽部で打楽器を担当しました。", "大学では素粒子物理の実験を学びたいです。"),
               objective=("consistency_bottom",), human_only="関連が薄く見えても、人は別の接点（リズム感と周期現象など）を認めるかもしれない",
               stages_by_version={C: {"clarity": G, "specificity": B}, D: {"clarity": G, "specificity": B}}),
    AnswerCase("padded", "回答を単に長くしただけの例", ("私は防災を研究しました。私は防災を研究しました。私は防災を研究しました。", "調査を担当しました。調査を担当しました。"),
               objective=("not_better_than:short-clear",), human_only="水増しの見え方は人が判断する",
               stages_by_version={C: {"clarity": G, "specificity": B}, D: {"clarity": G, "specificity": B}}),
    AnswerCase("sensitive", "個人情報やセンシティブな内容を含む例", ("家庭の事情で活動を続けられませんでした。私は部活で研究に取り組みました。", "宗教的な理由で参加できない行事もありました。"),
               objective=("no_probe_of_sensitive",), human_only="どこまで書くかは本人の選択",
               stages_by_version={C: {"clarity": G, "specificity": B}, D: {"clarity": G, "specificity": B}}),
)
