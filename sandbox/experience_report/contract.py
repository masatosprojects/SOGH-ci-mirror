"""Data contract v0 of an exam-experience report (an interview experience reported by a candidate). SYNTHETIC ONLY: nothing here collects, stores or sends anything; it defines the shape,
the cross-field rules and the checks, and is exercised with invented reports.

Principles (docs/PRODUCT_STRATEGY.md): an experience report is NOT an official fact; sharing with the reporter's own school, SOGH's internal use and public display are THREE separate permissions;
a reward is never tied to the public permission or to the amount written; a different answer from another report or from the official source is a reason to look, not proof of a lie; a small
number of reports is never turned into a "trend".  The age and guardian rules are PROPOSED (the user and counsel decide) and are marked as such.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal, get_args

Certainty = Literal["sure", "unsure", "unknown"]
InterviewFormat = Literal["individual", "group", "presentation_then_qa", "online", "other", "unknown"]
Phase = Literal["first_stage", "second_stage", "single_stage", "unknown"]  # the phase of the selection the interview belonged to; NOT the "stage" ordinal that an article quotes
Outcome = Literal["passed", "failed", "pending", "prefer_not_to_say"]  # optional, never required, never used to weight a report
Verification = Literal["unverified", "self_attested", "corroborated", "withheld", "rejected"]
AgeBand = Literal["under18", "18plus"]

CONSENT_TEXT_VERSION = "consent-v0-draft"
MAX_QUESTIONS = 20
MAX_QUESTION_CHARS = 300

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}")
_PERSON = re.compile(r"[一-龥ぁ-んァ-ヴー]{1,4}(?:教授|准教授|講師|先生|氏)")  # a named interviewer or examiner: never published as such
_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class Question:
    text: str
    is_followup: bool = False
    followup_of: int | None = None  # index of the question it follows
    certainty: Certainty = "unknown"


@dataclass(frozen=True)
class Consent:
    school_internal: bool = False  # the reporter's own school may keep it (e.g. a digitised school report)
    sogh_internal: bool = False  # SOGH may use it internally to improve practice material
    public: bool = False  # SOGH may show it to other candidates
    text_version: str = CONSENT_TEXT_VERSION
    given_at: str | None = None  # an ISO date; None when nothing was consented to


@dataclass(frozen=True)
class Report:
    reporter_key: str  # a pseudonym made by the service (never a name, an e-mail address or a school ID)
    university: str
    faculty: str
    method: str
    fiscal_year: int
    phase: Phase
    interview_format: InterviewFormat
    duration_minutes: int | None
    interviewers: int | None
    questions: tuple[Question, ...]
    overall_certainty: Certainty
    consent: Consent
    age_band: AgeBand = "18plus"
    guardian_consent: bool = False
    outcome: Outcome | None = None
    reward_requested: bool = False
    verification: Verification = "unverified"
    free_text: str = ""
    flags: tuple[str, ...] = field(default_factory=tuple)

    def key(self) -> tuple:
        return (self.university, self.faculty, self.method, self.fiscal_year)


# ------------------------------------------------------------------------------------------------------------------ the quick form (two stages)
STAGE1_FIELDS = ("target (prefilled when already known)", "interview_format", "duration_minutes", "one remembered question", "was there a follow-up (yes/no/unknown)", "overall_certainty")
STAGE2_FIELDS = ("more questions with their follow-ups", "free_text", "outcome (optional)", "consent: school_internal / sogh_internal / public (each separately)")
STAGE1_CHOICE_FIELDS = {"interview_format", "was there a follow-up", "overall_certainty"}  # a tap, no typing


def stage1_needs_at_most_one_free_text() -> bool:
    return sum(1 for f in STAGE1_FIELDS if "question" in f) == 1


# ------------------------------------------------------------------------------------------------------------------ closed value sets, checked at run time
# The Literal types above are only annotations: a direct call (not the HTTP adapter) could pass any string. These sets are the same values, checked by `validate`.
# "unknown" and "prefer_not_to_say" are VALUES (the reporter does not remember / does not want to say): never rejected. A blank or missing required value is a different problem.
_REQUIRED_CHOICES = {"phase": get_args(Phase), "interview_format": get_args(InterviewFormat), "overall_certainty": get_args(Certainty), "verification": get_args(Verification), "age_band": get_args(AgeBand)}
_OPTIONAL_CHOICES = {"outcome": get_args(Outcome)}  # None = not given: allowed and never filled in


def _choice_problems(r: Report) -> list[str]:
    p: list[str] = []
    for name, allowed in _REQUIRED_CHOICES.items():
        v = getattr(r, name)
        if v is None or (isinstance(v, str) and not v.strip()):
            p.append(f"missing_{name}")
        elif not isinstance(v, str) or v not in allowed:
            p.append(f"invalid_value_{name}")
    for name, allowed in _OPTIONAL_CHOICES.items():
        v = getattr(r, name)
        if v is not None and (not isinstance(v, str) or v not in allowed):
            p.append(f"invalid_value_{name}")
    for i, q in enumerate(r.questions):
        if q.certainty is None or (isinstance(q.certainty, str) and not q.certainty.strip()):
            p.append(f"question_{i}_missing_certainty")
        elif not isinstance(q.certainty, str) or q.certainty not in get_args(Certainty):
            p.append(f"question_{i}_invalid_value_certainty")
    for name in ("school_internal", "sogh_internal", "public"):
        if type(getattr(r.consent, name)) is not bool:  # "false" or 1 is not a permission and is not read as one
            p.append(f"consent_{name}_must_be_true_or_false")
    for name in ("guardian_consent", "reward_requested"):
        if type(getattr(r, name)) is not bool:
            p.append(f"{name}_must_be_true_or_false")
    for name in ("fiscal_year", "duration_minutes", "interviewers"):
        v = getattr(r, name)
        if v is not None and (type(v) is not int):  # a bool or a string is not a number of years or minutes
            p.append(f"{name}_must_be_an_integer")
    return p


# ------------------------------------------------------------------------------------------------------------------ validation of one report
def validate(r: Report) -> list[str]:
    """Problems that make a report unusable as submitted. A returned code is never a verdict that the reporter lied."""
    p: list[str] = _choice_problems(r)
    if p:  # the value checks below assume well-typed fields: report the type problems and stop, so a wrong type is never turned into a second, confusing error
        return p
    if not r.reporter_key or _EMAIL.search(r.reporter_key) or _PHONE.search(r.reporter_key) or len(r.reporter_key) < 8:
        p.append("reporter_key_must_be_a_pseudonym")
    for name in ("university", "faculty", "method"):
        if not getattr(r, name).strip():
            p.append(f"{name}_missing")
    if not 2000 <= r.fiscal_year <= 2100:
        p.append("fiscal_year_out_of_range")
    if r.duration_minutes is not None and not 1 <= r.duration_minutes <= 240:
        p.append("duration_implausible")
    if r.interviewers is not None and not 1 <= r.interviewers <= 12:
        p.append("interviewer_count_implausible")
    if not r.questions:
        p.append("no_question")
    if len(r.questions) > MAX_QUESTIONS:
        p.append("too_many_questions")
    for i, q in enumerate(r.questions):
        if not q.text.strip() or len(q.text) > MAX_QUESTION_CHARS:
            p.append(f"question_{i}_empty_or_too_long")
        if q.is_followup and (q.followup_of is None or not 0 <= q.followup_of < i):
            p.append(f"question_{i}_follow_up_of_nothing")
        if not q.is_followup and q.followup_of is not None:
            p.append(f"question_{i}_not_a_follow_up_but_has_a_parent")
    texts = " ".join([q.text for q in r.questions] + [r.free_text])
    if _EMAIL.search(texts) or _PHONE.search(texts):
        p.append("personal_contact_in_text")
    if _URL.search(texts):
        p.append("link_in_text")  # no link is followed or republished
    if (r.consent.school_internal or r.consent.sogh_internal or r.consent.public) and not r.consent.given_at:
        p.append("consent_without_a_date")
    if r.age_band == "under18" and (r.consent.public or r.consent.school_internal) and not r.guardian_consent:
        p.append("under18_needs_guardian_consent_to_share")  # PROPOSED rule: to be confirmed by the user and counsel
    return p


def review_flags(r: Report) -> list[str]:
    """Things a human should look at before the report is shown (not rejections)."""
    f: list[str] = []
    texts = " ".join([q.text for q in r.questions] + [r.free_text])
    if _PERSON.search(texts):
        f.append("possible_named_interviewer")
    norm = [re.sub(r"\s+", "", q.text) for q in r.questions]
    if len(set(norm)) < len(norm):
        f.append("repeated_question_text")  # padding
    if r.duration_minutes and len(r.questions) > max(3, r.duration_minutes // 2):
        f.append("implausible_volume_for_the_duration")
    if r.reward_requested and len(r.questions) >= 12:
        f.append("many_questions_with_a_reward_requested")  # volume is never what is paid for, but it is what padding looks like
    return f


# ------------------------------------------------------------------------------------------------------------------ across reports
def _grams(s: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def similarity(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def cross_checks(reports: list[Report], *, copy_threshold: float = 0.8) -> dict[int, list[str]]:
    """Per report index: duplicate submissions by one reporter for one target/year, near-copies of another reporter's question list, and the reports of one target that are reported by the same pseudonym
    too many times. Different answers for one target are NOT flagged: interviewers, years and sessions differ."""
    out: dict[int, list[str]] = {i: [] for i in range(len(reports))}
    for i, a in enumerate(reports):
        for j, b in enumerate(reports):
            if j <= i or a.key() != b.key():
                continue
            if a.reporter_key == b.reporter_key:
                out[i].append("duplicate_submission_same_reporter_and_target")
                out[j].append("duplicate_submission_same_reporter_and_target")
                continue
            ta, tb = " ".join(q.text for q in a.questions), " ".join(q.text for q in b.questions)
            if len(a.questions) >= 2 and similarity(ta, tb) >= copy_threshold:
                out[i].append("near_copy_of_another_reporters_text")
                out[j].append("near_copy_of_another_reporters_text")
    per_reporter: dict[str, int] = {}
    for r in reports:
        per_reporter[r.reporter_key] = per_reporter.get(r.reporter_key, 0) + 1
    for i, r in enumerate(reports):
        if per_reporter[r.reporter_key] > 3:
            out[i].append("one_reporter_many_reports")
    return out


def against_official(r: Report, official: dict[str, str | None]) -> list[str]:
    """Compare with what an official source says (invented here). A difference is information for review: it is never shown as the report being false."""
    notes: list[str] = []
    if official.get("interview_present") == "なし":
        notes.append("official_source_says_no_interview_review_needed")
    d = official.get("interview_duration_minutes")
    if d and r.duration_minutes and abs(int(d) - r.duration_minutes) > max(5, int(d) // 2):
        notes.append("duration_differs_from_the_official_figure_informational")
    return notes


def public_visibility(r: Report, extra_flags: list[str]) -> tuple[bool, list[str]]:
    """May this report be shown to other candidates, and with which labels. Visible only with the explicit public permission, a usable report, no open review flag, and never when withheld or rejected."""
    labels = ["受験経験の報告（公式情報ではありません）", {"sure": "記憶は確か", "unsure": "記憶は不確か"}.get(r.overall_certainty, "記憶の確かさは不明")]  # an invalid value is also "unknown" here, and validate() below refuses it
    if r.verification in ("unverified", "self_attested"):
        labels.append("未確認")
    if validate(r) or r.verification in ("withheld", "rejected") or not r.consent.public or r.flags or extra_flags:
        return False, labels
    return True, labels


# ------------------------------------------------------------------------------------------------------------------ never a trend from a few reports
MIN_REPORTS_FOR_ANY_SUMMARY = 5


def summarize(reports: list[Report]) -> dict:
    """Counts only, always with their limits. Below MIN_REPORTS_FOR_ANY_SUMMARY nothing is summarised; above it, the self-selection of reporters is still stated, and no question is called frequent."""
    n = len(reports)
    base = {"n": n, "years": sorted({r.fiscal_year for r in reports}), "reporters": len({r.reporter_key for r in reports}),
            "outcomes": {k: sum(1 for r in reports if r.outcome == k) for k in ("passed", "failed", "pending", "prefer_not_to_say")} | {"not_given": sum(1 for r in reports if r.outcome is None)}}
    if n < MIN_REPORTS_FOR_ANY_SUMMARY:
        return base | {"generalizable": False, "statement": f"{n}件のみ。傾向とは言えません。", "formats": None}
    fmt: dict[str, int] = {}
    for r in reports:
        fmt[r.interview_format] = fmt.get(r.interview_format, 0) + 1
    return base | {"generalizable": False, "formats": fmt,
                   "statement": f"{n}件の報告の集計です。報告は任意の提出で、報告した人に偏りがあり得ます（合否・記憶の確かさ・年度が異なります）。特定の質問が出るという意味ではありません。"}


def with_flags(r: Report, flags: list[str]) -> Report:
    return replace(r, flags=tuple(sorted(set(r.flags) | set(flags))))
