"""Data types of the interview sandbox. SYNTHETIC ONLY: every university, fact, report and question here is invented.

Four kinds of content are kept in four different types and are never merged, so that a screen or a log can always say where a sentence came from:
  OfficialFact          what an official source says (here: an invented source), with a pinned version; a missing fact is `unknown`, never a guess
  ExperienceReport      one candidate's experience (invented here); never an official fact
  PracticeQuestion      a question the AI made for practice; never described as an actual past question
  UserInput             what the practising person types (private; kept in memory only, never written anywhere)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FactStatus = Literal["confirmed", "unknown"]


@dataclass(frozen=True)
class OfficialFact:
    fact_id: str
    label: str  # e.g. "面接の有無"
    value: str | None  # None when the status is unknown
    status: FactStatus
    source_version: str  # the pinned version of the (invented) source this was read from
    kind: str = "official_fact"

    def __post_init__(self) -> None:
        if self.status == "confirmed" and not self.value:
            raise ValueError("a confirmed fact needs a value")
        if self.status == "unknown" and self.value is not None:
            raise ValueError("an unknown fact has no value: nothing is guessed")


@dataclass(frozen=True)
class ExperienceReport:
    report_id: str
    fiscal_year: int
    summary: str
    certainty: Literal["sure", "unsure"]
    consent_scope: Literal["school_internal", "sogh_internal", "public"]
    kind: str = "experience_report"  # never an official fact; shown separately and never called a trend


@dataclass(frozen=True)
class PracticeQuestion:
    question_id: str
    category: str
    text: str
    basis_fact_ids: tuple[str, ...] = ()  # official facts this question touches (each with its pinned version); empty = a general practice question
    kind: str = "ai_practice_material"


@dataclass(frozen=True)
class SessionPlan:
    categories: tuple[str, ...]
    total_seconds: int
    max_followups_per_question: int = 2
    max_total_followups: int = 5


@dataclass(frozen=True)
class InterviewContext:
    case_id: str
    university: str  # invented, always contains 架空
    faculty: str
    method: str
    fiscal_year: int
    official_facts: tuple[OfficialFact, ...]
    experience_reports: tuple[ExperienceReport, ...]
    practice_questions: tuple[PracticeQuestion, ...]
    plan: SessionPlan
    interview_is_official: bool  # False: this method has no confirmed interview; practice is shown as general practice, not as "the" interview

    def fact(self, fact_id: str) -> OfficialFact | None:
        return next((f for f in self.official_facts if f.fact_id == fact_id), None)

    def unknown_facts(self) -> tuple[OfficialFact, ...]:
        return tuple(f for f in self.official_facts if f.status == "unknown")


@dataclass(frozen=True)
class ActivityEntry:
    title: str
    role: str = ""
    description: str = ""


@dataclass(frozen=True)
class CandidateProfile:
    """What the practising person typed about themselves for ONE practice (INVENTED here; in memory only). Built and validated by profile.build_profile."""
    motivation: str
    activities: tuple[ActivityEntry, ...] = ()
    kind: str = "user_input"


@dataclass
class Turn:
    turn_id: str
    role: Literal["interviewer", "candidate"]
    text: str
    origin: str  # "ai_practice_material" | "official_fact_based" | "follow_up_to_the_answer" | "user_input"
    question_id: str | None = None
    basis: tuple[str, ...] = ()
    followup_of: str | None = None
    quote: tuple[int, int] | None = None  # where in the candidate's answer a follow-up quotes (start, end)
    elapsed_seconds: int = 0
    doc_ref: tuple[str, int, int] | None = None  # for a document-based question: which part of the person's profile it quotes, and where (part, start, end)


@dataclass
class SessionConfig:
    llm_enabled: bool = False  # external AI / voice / video APIs are OFF by default and not implemented
    persist: bool = False  # nothing is written anywhere

    def __post_init__(self) -> None:
        if self.llm_enabled:
            raise NotImplementedError("external AI, voice and video APIs are not approved: the sandbox runs on deterministic mocks only")
        if self.persist:
            raise NotImplementedError("persisting a session is not implemented: the sandbox keeps a session in memory only")


@dataclass
class Notice:
    code: str
    text: str
    extra: dict = field(default_factory=dict)
