"""Three INVENTED practice cases. The universities do not exist; the facts, the report and the questions are made up for tests and demos.
Nothing here describes a real university, a real past question or a real result."""
from __future__ import annotations

from .guards import assert_clean
from .models import ExperienceReport, InterviewContext, OfficialFact, PracticeQuestion, SessionPlan

CATEGORIES = ("志望理由", "これまでの活動", "学びたいこと")


def _q(case: str, category: str, n: int, text: str, basis: tuple[str, ...] = ()) -> PracticeQuestion:
    return PracticeQuestion(f"{case}-{CATEGORIES.index(category) + 1}{chr(96 + n)}", category, assert_clean(text), basis)


def _questions(case: str, duration_fact: str | None) -> tuple[PracticeQuestion, ...]:
    qs = [
        _q(case, "志望理由", 1, "この大学・学部を志望する理由を、自己紹介とあわせて話してください。"),
        _q(case, "志望理由", 2, "数ある進路のなかで、この方式で受験しようと考えた理由は何ですか。"),
        _q(case, "これまでの活動", 1, "高校生活で最も力を入れた活動について、あなたの役割と学びを話してください。"),
        _q(case, "これまでの活動", 2, "うまくいかなかった経験と、そこから何を変えたかを教えてください。"),
        _q(case, "学びたいこと", 1, "入学後に学びたいことと、その関心が生まれたきっかけを話してください。"),
        _q(case, "学びたいこと", 2, "将来、学んだことをどのように活かしたいと考えていますか。"),
    ]
    if duration_fact:  # a question that touches an official fact names it with its pinned version
        qs.insert(0, _q(case, "志望理由", 3, "面接時間は公式に確認できた条件（下に版を表示）です。限られた時間で、最初に伝えたいことは何ですか。", (duration_fact,)))
    return tuple(qs)


def case_ac() -> InterviewContext:
    facts = (
        OfficialFact("interview_present", "面接の有無", "あり", "confirmed", "架空要項 v1"),
        OfficialFact("interview_duration", "面接の時間", "約10分", "confirmed", "架空要項 v1"),
        OfficialFact("second_stage_date", "第2次選考の日程", None, "unknown", "架空要項 v1"),
        OfficialFact("evaluation_criteria", "評価の観点", None, "unknown", "架空要項 v1"),
    )
    reports = (ExperienceReport("fiction-report-1", 2026, "（架空の例）面接は志望理由の確認から始まったと記憶している。", "unsure", "public"),)
    # the first facts are invented; ExperienceReport is a single invented memory, shown apart from the facts and never called a trend
    return InterviewContext("fiction-ac-1", "架空第一大学", "練習学部", "架空総合型方式", 2027, facts, reports, _questions("fiction-ac-1", "interview_duration"),
                            SessionPlan(CATEGORIES, 600), True)


def case_recommendation() -> InterviewContext:
    facts = (
        OfficialFact("interview_present", "面接の有無", "あり", "confirmed", "架空要項 v2"),
        OfficialFact("interview_duration", "面接の時間", None, "unknown", "架空要項 v2"),
        OfficialFact("interview_format", "面接の形式", None, "unknown", "架空要項 v2"),
    )
    return InterviewContext("fiction-rec-2", "架空第二大学", "練習学部", "架空学校推薦型方式", 2027, facts, (), _questions("fiction-rec-2", None),
                            SessionPlan(CATEGORIES, 480), True)


def case_no_interview() -> InterviewContext:
    facts = (OfficialFact("interview_present", "面接の有無", "なし", "confirmed", "架空要項 v1"),)
    return InterviewContext("fiction-gen-3", "架空第三大学", "練習学部", "架空一般方式", 2027, facts, (), _questions("fiction-gen-3", None),
                            SessionPlan(CATEGORIES[:2], 300, 1, 2), False)  # no confirmed interview: general practice only, never shown as "the" interview


CASES = {"fiction-ac-1": case_ac, "fiction-rec-2": case_recommendation, "fiction-gen-3": case_no_interview}


def get_case(case_id: str) -> InterviewContext:
    try:
        return CASES[case_id]()
    except KeyError:
        raise KeyError(f"unknown practice case {case_id!r}: choose one of {sorted(CASES)}") from None
