"""The deterministic mock interviewer. No model, no network, no storage: the same context and the same answers always give the same questions.

Flow: briefing() -> start() -> answer(...) ... -> end / time up -> feedback() -> retry() with the same conditions.
Follow-up questions quote the person's OWN words (their span is recorded), are limited per question and per session, and never probe the sensitive topics of guards.SENSITIVE_TERMS.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import guards
from .models import CandidateProfile, InterviewContext, Notice, SessionConfig, Turn

log = logging.getLogger("interview_sandbox")  # counts and codes only: an answer's text is never logged

VAGUE = ("いろいろ", "色々", "たくさん", "とても", "なんとなく", "頑張", "がんばり", "様々", "いろんな")
ACTIVITY = ("活動", "研究", "取り組", "参加", "部活", "大会", "委員", "ボランティア", "留学", "探究")
REASON = ("ため", "から", "なぜなら", "理由", "きっかけ", "ので")
NOT_AN_ACTIVITY = re.compile(r"参加(?:者|費|率|人数)")  # "参加者が増えました" is a result, not "I took part in an activity"
ROLE_STATED = re.compile(r"担当|役割|リーダー|代表|部長|委員長|責任者|務め|任され|まとめ役|運営|(?<!関)係")  # the person already said what their own part was
FUTURE_CATEGORIES = ("学びたいこと",)  # a question about what the person wants to learn is about the future: "what was your role?" does not fit it
DISCLAIMERS = (
    "これは練習用です。大学の公式の面接・採点ではなく、大学公認でもありません。",
    "質問は AI が練習のために作ったもの（このモックは決まった文型から作ります）で、実際に出題される質問とは限りません。",
    "合格・不合格の予測や、実際の面接との一致度は示しません。",
    "この練習の内容は保存しません（このプログラムの中にだけあります）。電話番号・メールアドレスは入力しないでください。",
)


@dataclass
class Briefing:
    title: str
    conditions: list[str]
    unknown: list[str]
    experience_notes: list[str]
    disclaimers: tuple[str, ...]
    plan: str

    def text(self) -> str:
        lines = [self.title, ""]
        lines += ["【公式に確認できた条件】"] + (self.conditions or ["（確認できた条件はありません）"])
        lines += ["", "【公式には確認できていない事項（推測しません）】"] + (self.unknown or ["（なし）"])
        if self.experience_notes:
            lines += ["", "【受験経験の報告（公式情報ではありません）】"] + self.experience_notes
        lines += ["", "【この練習の進め方】", self.plan, "", "【ご注意】"] + list(self.disclaimers)
        return "\n".join(lines)


@dataclass
class AnswerResult:
    accepted: bool
    next_turn: Turn | None = None
    ended: bool = False
    end_reason: str | None = None
    rejected_reason: str | None = None
    notices: list[Notice] = field(default_factory=list)


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in re.finditer(r"[。！？!?\n]", text):
        if m.end() > start:
            spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def analysable(text: str) -> list[tuple[int, int]]:
    """The sentences that may be quoted or probed (those that touch a sensitive topic never are)."""
    return [(a, b) for a, b in _sentences(text) if not guards.sensitive_in(text[a:b]) and not guards.official_claim_in(text[a:b]) and not guards.opaque_token_in(text[a:b])]


def _clip(text: str, a: int, b: int, limit: int = 30) -> tuple[int, int]:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1] in "。！？!?\n ":
        b -= 1
    return a, min(b, a + limit)


class InterviewSession:
    def __init__(self, context: InterviewContext, *, variant: int = 0, config: SessionConfig | None = None, profile: CandidateProfile | None = None):
        self.config = config or SessionConfig()
        self.context = context
        if profile is not None and type(profile) is not CandidateProfile:
            raise TypeError("profile must be a CandidateProfile made by profile.build_profile")
        self.profile = profile
        from .profile import document_questions
        self._doc_questions = document_questions(profile) if profile is not None else {}
        self._doc_category: dict[str, str] = {}
        self.focus = None  # a RubricItem of the earlier practice, set by retry(report)
        self.variant = variant
        self.state = "setup"
        self.turns: list[Turn] = []
        self.notices: list[Notice] = []
        self.rejected_events = 0
        self._category_index = 0
        self._followups_here = 0
        self._followups_total = 0
        self._claim_withheld = False
        self._open: Turn | None = None
        self._elapsed = 0
        self._counter = 0
        self.end_reason: str | None = None

    # ---------------------------------------------------------------- 1-2: conditions and briefing
    def briefing(self) -> Briefing:
        c = self.context
        conditions = [f"{f.label}：{f.value}（{f.source_version}・架空の資料）" for f in c.official_facts if f.status == "confirmed"]
        unknown = [f"{f.label}：公式には確認できていません" for f in c.unknown_facts()]
        notes = [f"{r.fiscal_year}年度・{ {'sure': '記憶は確か', 'unsure': '記憶は不確か'}[r.certainty] }・1件のみ。傾向とは言えません：{r.summary}" for r in c.experience_reports]
        title = f"{c.university} {c.faculty}／{c.method}／{c.fiscal_year}年度（すべて架空の練習ケース）"
        if not c.interview_is_official:
            title += "　※この方式で面接が行われることは確認できていません。以下は一般的な面接練習です。"
        mins = c.plan.total_seconds // 60
        plan = f"想定 {mins} 分、質問のテーマは {'→'.join(c.plan.categories)}。1 つの質問への深掘りは最大 {c.plan.max_followups_per_question} 回、全体で最大 {c.plan.max_total_followups} 回です。"
        if self.profile is not None:
            plan += "\nあなたが入力した志望理由書・活動情報の言葉を引用した質問を含みます（引用以外の部分は固定の文型で、書かれていないことは加えません）。入力した内容は保存せず、このプログラムの中にだけあります。"
        if self.focus is not None:
            plan += f"\n前回の講評を踏まえた今回の練習の焦点：「{self.focus.label}」（前回の段階：{self.focus.stage}）。{self.focus.improvement}"
        b = Briefing(guards.assert_clean(title), conditions, unknown, notes, DISCLAIMERS, plan)
        guards.assert_clean(b.text())
        return b

    # ---------------------------------------------------------------- 3: first question
    def start(self) -> Turn:
        if self.state != "setup":
            raise RuntimeError("the session has already started")
        self.state = "in_progress"
        log.info("session started case=%s variant=%s", self.context.case_id, self.variant)
        return self._ask_next_category()

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self.context.case_id}:v{self.variant}:t{self._counter}"

    def _ask_next_category(self) -> Turn | None:
        if self._category_index >= len(self.context.plan.categories):
            return None
        category = self.context.plan.categories[self._category_index]
        docs = self._doc_questions.get(category) or []
        if docs:  # the person's own words, quoted: one document-based question for this category (deterministic by variant); else the invented question of the case
            d = docs[self.variant % len(docs)]
            self._doc_category[d.question_id] = category
            t = Turn(self._next_id(), "interviewer", guards.assert_clean(d.text), "document_based", d.question_id, doc_ref=d.doc_ref)
            self.turns.append(t)
            self._open = t
            self._followups_here = 0
            return t
        pool = [q for q in self.context.practice_questions if q.category == category]
        if not pool:
            raise ValueError(f"no practice question for {category}")
        q = pool[self.variant % len(pool)]
        text = q.text
        for fid in q.basis_fact_ids:  # a question that touches an official fact shows the fact and its pinned version, or says it is unknown
            f = self.context.fact(fid)
            text += f"\n（公式に確認できた条件：{f.label}＝{f.value}、{f.source_version}）" if f and f.status == "confirmed" else f"\n（{fid} は公式には確認できていません）"
        t = Turn(self._next_id(), "interviewer", guards.assert_clean(text), "ai_practice_material", q.question_id, q.basis_fact_ids)
        self.turns.append(t)
        self._open = t
        self._followups_here = 0
        return t

    # ---------------------------------------------------------------- 4-5: answers, follow-ups, time
    @property
    def remaining_seconds(self) -> int:
        return max(0, self.context.plan.total_seconds - self._elapsed)

    def answer(self, turn_id: str, text: str, elapsed_seconds: int) -> AnswerResult:
        if self.state != "in_progress" or self._open is None or turn_id != self._open.turn_id:
            self.rejected_events += 1  # a duplicate, a late or a foreign event changes nothing
            log.info("event rejected (duplicate or stale) case=%s", self.context.case_id)
            return AnswerResult(False, rejected_reason="duplicate_or_stale_turn")
        if type(elapsed_seconds) is not int or not 0 <= elapsed_seconds <= 3600:  # `type is int`: a bool is an int in Python, so True would have advanced the clock by one second (found by Work, Issue #75)
            raise ValueError("elapsed_seconds must be an integer from 0 to 3600")
        if type(text) is not str:
            raise ValueError("an answer is text")
        if len(text) > guards.MAX_ANSWER_CHARS:  # refused before any scanning; the question stays open so the person can answer in fewer words
            self.rejected_events += 1
            log.info("answer rejected (too long) case=%s chars=%d", self.context.case_id, len(text))
            return AnswerResult(False, rejected_reason="answer_too_long")
        notices: list[Notice] = []
        text, removed = guards.clean_text(text)
        if removed:
            notices.append(Notice("control_characters_removed", "目に見えない文字や制御文字を取り除きました。", {"count": removed}))
        stored = guards.mask_personal(text)
        if stored != text:
            notices.append(Notice("personal_info_masked", "電話番号・メールアドレス・リンク・アカウント名・郵便番号・パスワードやキーらしい文字列を伏せました。氏名や住所は自動では伏せられないので、個人情報は入力しないでください。"))
        asked = self._open
        self._elapsed += elapsed_seconds
        cand = Turn(self._next_id(), "candidate", stored, "user_input", asked.question_id, followup_of=asked.turn_id, elapsed_seconds=elapsed_seconds)
        self.turns.append(cand)
        self._open = None
        if any(guards.official_claim_in(text[a:b]) for a, b in _sentences(text)):
            notices.append(Notice("official_claim_not_repeated", "大学についての人数・倍率・日程・料金・面接時間などの記述は、公式に確認できたものではないため、質問や講評にそのまま引用しません。募集要項などの原典で確認してください。"))
        if any(guards.opaque_token_in(text[a:b]) for a, b in _sentences(text)):
            notices.append(Notice("opaque_token_not_repeated", "長い英数字の並び（キーやIDのように見えるもの）を含む文は、質問や講評にそのまま引用しません。"))
        if guards.sensitive_in(text):
            notices.append(Notice("sensitive_topic_not_probed", "個人的な事柄に関する部分には、これ以上質問しません。", {"terms": guards.sensitive_in(text)}))
        self.notices += notices
        log.info("answer accepted case=%s chars=%d elapsed=%d", self.context.case_id, len(text), elapsed_seconds)
        if self.remaining_seconds == 0:  # time is up: stop here, never in the middle of a question
            return self._finish("time_up", notices)
        plan = self.context.plan
        follow = None
        self._claim_withheld = False
        if self._followups_here < plan.max_followups_per_question and self._followups_total < plan.max_total_followups:
            follow = self._follow_up(cand, asked)
        if self._claim_withheld:
            withheld = Notice("claim_not_repeated", "回答の中に、この練習ツールが言ってはいけない種類の断定（合格の保証や出題の予告など）が含まれていたため、そのまま引用していません。このツールはそのような断定をしません。")
            notices.append(withheld)
            self.notices.append(withheld)
        if follow:
            self._followups_here += 1
            self._followups_total += 1
            self.turns.append(follow)
            self._open = follow
            return AnswerResult(True, follow, notices=notices)
        self._category_index += 1
        nxt = self._ask_next_category()
        if nxt is None:
            return self._finish("all_questions_asked", notices)
        return AnswerResult(True, nxt, notices=notices)

    def _follow_up(self, cand: Turn, asked: Turn) -> Turn | None:
        text = cand.text
        spans = analysable(text)
        if not spans:
            return None
        # The same WORDS are never asked about twice. (Found by the quality set: the old check compared a raw sentence span with the clipped quote of an earlier turn, so it never matched when the
        # quote was clipped, and a repeated sentence was asked about again. It also compared positions of different answers; the words are what matter.)
        by_id = {t.turn_id: t for t in self.turns}
        used = {by_id[t.followup_of].text[t.quote[0]:t.quote[1]] for t in self.turns if t.role == "interviewer" and t.quote and t.followup_of in by_id}
        fresh = [(a, b) for a, b in spans if text[slice(*_clip(text, a, b))] not in used]

        def first_with(words: tuple[str, ...]):
            for a, b in fresh:
                if any(w in text[a:b] for w in words):
                    return a, b
            return None

        category = self.context.plan.categories[self._category_index] if self._category_index < len(self.context.plan.categories) else ""
        role_unfit = category in FUTURE_CATEGORIES or bool(ROLE_STATED.search(text))  # asking "what was your role?" about a wish for the future, or again after the person said it, would be unrelated or redundant
        chosen = None
        sp = first_with(VAGUE)
        if sp and not re.search(r"\d", text[sp[0]:sp[1]]):
            qa, qb = _clip(text, *sp)
            chosen = (f"「{text[qa:qb]}」とありますが、具体的にはどのような場面や数字で示せますか。", (qa, qb))
        if chosen is None and not role_unfit:
            sp = next(((a, b) for a, b in fresh if any(w in NOT_AN_ACTIVITY.sub("", text[a:b]) for w in ACTIVITY)), None)
            if sp:
                qa, qb = _clip(text, *sp)
                chosen = (f"「{text[qa:qb]}」について、あなた自身が果たした役割は何でしたか。", (qa, qb))
        if chosen is None and fresh and not any(w in "".join(text[a:b] for a, b in spans) for w in REASON):
            qa, qb = _clip(text, *fresh[0])
            chosen = (f"「{text[qa:qb]}」と考えた理由を教えてください。", (qa, qb))
        if chosen is None and fresh and len(text.strip()) < 40:
            qa, qb = _clip(text, *fresh[0])
            chosen = (f"「{text[qa:qb]}」について、きっかけや経過をもう少し詳しく話してください。", (qa, qb))
        if chosen is None:
            return None
        q, quote = chosen
        if guards.forbidden_claims_in(q):
            # The person's own words contain a claim this tool must never make (a guaranteed pass, a promised question, ...). The guard is for what the TOOL says, so those words are not
            # repeated back; a neutral question asks for the basis instead. The span is still recorded, so the same words are not asked about twice.
            q = "いま述べたことについて、ご自身の経験や、確かめられる情報に基づいて言い換えてもらえますか。"
            self._claim_withheld = True
        return Turn(self._next_id(), "interviewer", guards.assert_clean(q), "follow_up_to_the_answer", asked.question_id, followup_of=cand.turn_id, quote=quote)

    # ---------------------------------------------------------------- 6: end
    def end(self, reason: str = "user") -> AnswerResult:
        if self.state != "in_progress":
            return AnswerResult(False, rejected_reason="not_in_progress")
        return self._finish(reason, [])

    def _finish(self, reason: str, notices: list[Notice]) -> AnswerResult:
        self.state = "ended"
        self.end_reason = reason
        self._open = None
        log.info("session ended case=%s reason=%s", self.context.case_id, reason)
        return AnswerResult(True, None, True, reason, notices=notices)

    # ---------------------------------------------------------------- 7-9: feedback and retry (feedback.py)
    def feedback(self):
        from .feedback import build_feedback
        if self.state != "ended":
            raise RuntimeError("the feedback is made after the session has ended")
        return build_feedback(self)

    def retry(self, report=None) -> "InterviewSession":
        """The same conditions again (same case, plan, questions, profile): a fresh session whose result can be compared with the earlier one.
        With the earlier feedback report, the new session also carries a practice FOCUS (the weakest judged item and its improvement example), shown in its briefing."""
        again = InterviewSession(self.context, variant=self.variant, config=self.config, profile=self.profile)
        if report is not None:
            from .feedback import FeedbackReport, focus_of
            if type(report) is not FeedbackReport or report.case_id != self.context.case_id:
                raise ValueError("the feedback report must be this case's FeedbackReport")
            again.focus = focus_of(report)
        return again

    def candidate_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "candidate"]
