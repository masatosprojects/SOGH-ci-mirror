"""The practising person's own (INVENTED) 志望理由書 and 活動情報, and the questions that are made from them.

SYNTHETIC ONLY.  The profile is typed or loaded by the person for one practice; it lives in memory only (nothing is written, logged or sent).
Rules that the tests fix:
  * Every document-based question QUOTES the person's own words, verbatim, between 「」, and says whose words they are.  The tool never adds a detail the person did not write
    (no invented motive, activity, number, name or official fact).  The wording around the quote comes from a fixed list of templates.
  * A sentence that touches a sensitive topic, contains a claim this tool must never make, or looks like personal information is never quoted.
  * Personal information shapes (e-mail, phone, link, account, postal code) are masked when the profile is accepted.
  * Size limits: a profile cannot be used to push an unbounded amount of text through the sandbox.
  * If nothing in the profile can be quoted safely for a category, the ordinary invented practice question of the case is asked instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import guards
from .models import CandidateProfile, ActivityEntry

MAX_MOTIVATION_CHARS = 1500
MAX_ACTIVITIES = 5
MAX_FIELD_CHARS = 300
QUOTE_LIMIT = 40

OFFICIAL_CLAIM_WORDS = guards.OFFICIAL_CLAIM_WORDS  # the test is shared with the answers (guards.official_claim_in)
OFFICIAL_CLAIM_PATTERN = guards.OFFICIAL_CLAIM_PATTERN

PROVENANCE = "あなたが入力した"  # every document-based question says that the quoted words are the person's own


def _text(value, label: str, limit: int, *, required: bool) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    if len(value) > limit * 4:  # refused before any scanning
        raise ValueError(f"{label} is far longer than {limit} characters")
    value, _removed = guards.clean_text(value)
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is empty")
    if len(value) > limit:
        raise ValueError(f"{label} is longer than {limit} characters")
    return guards.mask_personal(value)


def build_profile(motivation, activities=()) -> CandidateProfile:
    """Validate and accept a profile.  Raises ValueError for anything that is not plain, bounded text."""
    motivation = _text(motivation, "motivation", MAX_MOTIVATION_CHARS, required=True)
    if type(activities) not in (list, tuple):
        raise ValueError("activities must be a list")
    if len(activities) > MAX_ACTIVITIES:
        raise ValueError(f"at most {MAX_ACTIVITIES} activities")
    entries = []
    for a in activities:
        if not isinstance(a, dict) or set(a) - {"title", "role", "description"}:
            raise ValueError("an activity has only title, role and description")
        entries.append(ActivityEntry(_text(a.get("title"), "activity title", MAX_FIELD_CHARS, required=True),
                                     _text(a.get("role", ""), "activity role", MAX_FIELD_CHARS, required=False),
                                     _text(a.get("description", ""), "activity description", MAX_FIELD_CHARS, required=False)))
    return CandidateProfile(motivation, tuple(entries))


def _sentences(text: str):
    # the same sentence rule as the engine (kept local to avoid a circular import)
    spans, start = [], 0
    for m in re.finditer(r"[。！？!?\n]", text):
        if m.end() > start:
            spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def _quotable(text: str, a: int, b: int):
    """A clipped span of one sentence that is safe to quote, or None."""
    a2, b2 = a, b
    while a2 < b2 and text[a2].isspace():
        a2 += 1
    while b2 > a2 and text[b2 - 1] in "。！？!?\n ":
        b2 -= 1
    b2 = min(b2, a2 + QUOTE_LIMIT)
    piece = text[a2:b2]
    if not piece.strip() or "「" in piece or "」" in piece:
        return None
    sentence = text[a:b]
    if guards.sensitive_in(sentence) or guards.forbidden_claims_in(sentence) or guards.has_personal(sentence) or "[" in piece:
        return None
    if guards.opaque_token_in(sentence):
        return None  # a machine-like token (a key, an id, a mixed-script word) is not quoted, whether or not a pattern recognised it
    if guards.official_claim_in(sentence):
        return None  # the person's statement about the university (rates, quotas, dates, interview length) is not repeated, not even as a quotation: it is not a verified official fact
    return a2, b2


@dataclass(frozen=True)
class DocQuestion:
    question_id: str
    category: str
    text: str
    doc_ref: tuple[str, int, int]  # (which part of the profile, start, end) of the quoted words


def document_questions(profile: CandidateProfile) -> dict[str, list[DocQuestion]]:
    """Deterministic: the same profile always gives the same questions.  Keys are the three categories of the cases."""
    out: dict[str, list[DocQuestion]] = {"志望理由": [], "これまでの活動": [], "学びたいこと": []}
    m = profile.motivation
    spans = [(a, b, _quotable(m, a, b)) for a, b in _sentences(m)]
    spans = [(a, b, q) for a, b, q in spans if q]
    learn_words = ("学", "研究", "関心", "興味", "知りたい")
    learn_spans = [s for s in spans if any(w in m[s[0]:s[1]] for w in learn_words)][-1:]   # the last sentence about learning is kept for the "学びたいこと" question
    reason_spans = [s for s in spans if s not in learn_spans] or spans                      # the others (or, if there is only one, that one) for the "志望理由" question
    for i, (_a, _b, (qa, qb)) in enumerate(reason_spans[:2]):
        out["志望理由"].append(DocQuestion(f"doc-m{i + 1}", "志望理由",
                                          f"{PROVENANCE}志望理由書に「{m[qa:qb]}」とあります。そう考えるようになった具体的な出来事やきっかけを教えてください。", ("motivation", qa, qb)))
    for i, (_a, _b, (qa, qb)) in enumerate(learn_spans[:2]):
        out["学びたいこと"].append(DocQuestion(f"doc-l{i + 1}", "学びたいこと",
                                           f"{PROVENANCE}志望理由書に「{m[qa:qb]}」とあります。入学後、具体的に何をどのように学びたいですか。", ("motivation", qa, qb)))
    for i, e in enumerate(profile.activities):
        q = _quotable(e.title, 0, len(e.title))
        if not q:
            continue
        out["これまでの活動"].append(DocQuestion(f"doc-a{i + 1}", "これまでの活動",
                                           f"{PROVENANCE}活動情報に「{e.title[q[0]:q[1]]}」とあります。その活動で、あなた自身が果たした役割と、そこで学んだことを具体的に話してください。", (f"activity{i + 1}.title", q[0], q[1])))
        if e.description:
            d = next(((a, b, _quotable(e.description, a, b)) for a, b in _sentences(e.description) if _quotable(e.description, a, b)), None)
            if d:
                qa, qb = d[2]
                out["これまでの活動"].append(DocQuestion(f"doc-a{i + 1}d", "これまでの活動",
                                                   f"{PROVENANCE}活動情報の「{e.description[qa:qb]}」について、うまくいかなかった点や工夫した点があれば教えてください。", (f"activity{i + 1}.description", qa, qb)))
    return out
