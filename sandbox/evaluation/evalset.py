"""Invented answer scripts, the rating sheet and the agreement measure. SYNTHETIC ONLY.

Why: the sandbox's rubric (stages computed from visible rules) has not been compared with people. This module (1) runs fixed scripts through the deterministic mock and writes what a person
would see, (2) writes a rating sheet with blank cells for human raters (follow-up fit, feedback concreteness, anything harmful), and (3) measures how well the mock's stage agrees with human stages
once raters have filled the sheet. With no human ratings, agreement is NOT computed and is reported as `not_run` (never as a number).
"""
from __future__ import annotations

from dataclasses import dataclass

from interview_sandbox import InterviewSession, get_case
from interview_sandbox.feedback import RUBRIC, STAGES

SCRIPTS = {  # name -> (case, answers); every answer is invented
    "concrete": ("fiction-ac-1", ["私は高校の探究活動で、地域の防災について研究しました。例えば、3か月間で50人にアンケートを行い、その結果、避難経路の認知が低いと分かりました。大学では防災の社会学を学びたいです。なぜなら、研究で見えた課題を政策につなげたいからです。",
                                  "防災の研究では私は調査の担当でした。その調査の経験から、地域の課題を学びたいと考えました。", "将来は、調査で分かったことを地域の計画に活かしたいです。"]),
    "vague": ("fiction-ac-1", ["私はいろいろな活動を頑張りました。とても楽しかったです。", "たくさんの経験をして、様々なことを学びました。", "これからも頑張りたいです。"]),
    "short": ("fiction-rec-2", ["はい、研究です。", "理由は特にありません。"]),
    "no_reason": ("fiction-rec-2", ["部活でキャプテンをしていました。大会にも参加しました。", "後輩の指導を担当しました。"]),
    "personal_topic": ("fiction-ac-1", ["家庭の事情で活動を続けられませんでした。私は部活で研究に取り組みました。宗教的な理由で参加できない行事もありました。", "研究では私は記録の担当でした。"]),
    "general_practice": ("fiction-gen-3", ["私は高校で委員会活動に取り組みました。例えば、2年間で月1回の会議を運営しました。", "その経験から、人の意見を整理する力を学びたいと考えました。"]),
}


@dataclass
class Run:
    script: str
    case_id: str
    transcript: list[tuple[str, str]]  # (who, text)
    stages: dict[str, str]  # rubric key -> stage given by the mock


def run_script(name: str, elapsed: int = 30) -> Run:
    case, answers = SCRIPTS[name]
    s = InterviewSession(get_case(case))
    turn = s.start()
    for a in answers:
        if s.state != "in_progress":
            break
        turn = s.answer(turn.turn_id, a, elapsed).next_turn
    if s.state == "in_progress":
        s.end("script_finished")
    fb = s.feedback()
    return Run(name, case, [("面接官" if t.role == "interviewer" else "回答", t.text) for t in s.turns], {i.key: i.stage for i in fb.items})


def rating_sheet() -> str:
    """Markdown a rater can fill in. Blank cells are blank on purpose; nothing here is a rating."""
    out = ["# 模擬面接 Sandbox の人手評価シート（架空の台本。評価者が空欄を埋める）", "",
           "評価の観点：A=追質問は回答の内容に即していたか（1〜5）／B=追質問は深すぎず、個人的な事柄に踏み込んでいないか（はい・いいえ）／C=フィードバックの該当箇所は適切か（1〜5）／D=改善例は具体的で、事実を作っていないか（1〜5）／"
           "E=本文に断定的な表現（合否の予測、公認をうたう表現、実際の出題や過去問と呼ぶ表現）はなかったか（なし・あり）／F=ルーブリックの各項目について、あなたの段階（要改善・一部できている・できている・判定できない）", ""]
    for name in SCRIPTS:
        r = run_script(name)
        out += [f"## {name}（{r.case_id}）", ""] + [f"- **{who}**：{text}" for who, text in r.transcript] + ["", "| 観点 | 評価者の記入 | （参考）Sandbox の段階 |", "|---|---|---|"]
        for key, label in RUBRIC:
            out.append(f"| F:{label} |  | {r.stages[key]} |")
        out += ["| A 追質問の適合 |  |  |", "| B 踏み込みすぎ |  |  |", "| C 該当箇所 |  |  |", "| D 改善例 |  |  |", "| E 問題のある表現 |  |  |", ""]
    out.append("**注意**：段階は練習用の目安で、実際の面接や合否の評価ではない。評価者は同意を得た人に限り、実在の個人情報を入れない。")
    return "\n".join(out)


def agreement(human: dict[tuple[str, str], str], mock: dict[tuple[str, str], str]) -> dict:
    """Exact agreement of the mock's stage with the human stage over the (script, rubric key) cells BOTH have judged. 'Not enough data' on either side is left out and counted, never a match.
    No human rating at all -> status not_run, no number."""
    keys = sorted(set(human) & set(mock))
    judged = [k for k in keys if human[k] in STAGES and mock[k] in STAGES]
    left_out = len(keys) - len(judged)
    if not judged:
        return {"status": "not_run", "reason": "no cell was judged by both a person and the mock", "left_out_cells": left_out}
    same = sum(human[k] == mock[k] for k in judged)
    within_one = sum(abs(STAGES.index(human[k]) - STAGES.index(mock[k])) <= 1 for k in judged)
    return {"status": "measured", "cells": len(judged), "exact": same / len(judged), "within_one_stage": within_one / len(judged), "left_out_cells": left_out,
            "caution": "a few raters and invented scripts: a rough check of the rubric, not a validation of interview quality"}


def mock_cells() -> dict[tuple[str, str], str]:
    return {(name, key): stage for name in SCRIPTS for key, stage in run_script(name).stages.items()}
