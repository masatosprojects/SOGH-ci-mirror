"""M1.g2 Product Implementation Candidate: FAQ Structured Extraction & STR-076 / STR-099 / STR-102 Policy.

Aligned with STR-099, STR-101, STR-102, and STR-106:
- PR #286 is the sole g2 baseline implementation.
- No new VERIFIED promotion path (`build_scope_proof`, `_verify_scope_proof`,
  or `scope_status="verified"`) is exposed here.
- Enforces strict preservation of UNKNOWN applicability (STR-076 §4) and provides
  owner-adopted unconfirmed FAQ section rendering (#199 comment 6722534424)
  with derived condition summaries, planted-tag rejection, and leak verification.
"""
from __future__ import annotations

import dataclasses
import hashlib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "FAQRecord",
    "UNCONFIRMED_SECTION_HEADING",
    "UNCONFIRMED_PREAMBLE_TEXT",
    "parse_faq_candidate",
    "render_unconfirmed_faq_section",
    "verify_unconfirmed_faq_section",
]

UNCONFIRMED_SECTION_HEADING = "## 公式FAQの案内（適用年度・学類は未確認）"

# Exact wording adopted by owner on 2026-11-08 (Issue #199 comment 6722534424 / patches/g2-faq/regenerated/README.md)
UNCONFIRMED_PREAMBLE_TEXT = (
    "大学公式サイトのFAQ（AC入試の節）には、生成AIを使った場合の下線の引き方や、画像・図・表の扱いが書かれています。"
    "ただし、このFAQの文面からは、どの年度・どの学類の出願に当てはまるかを確認できていません。"
    "出願の際は、必ず最新の募集要項と、公式サイトのFAQ（https://ac.tsukuba.ac.jp/consultation/faq/）、"
    "大学の窓口の案内で確認してください。"
)

_PLANTED_EV_RE = re.compile(r"\[EV-[^\]]+\]")


@dataclasses.dataclass(frozen=True)
class FAQRecord:
    faq_id: str
    source_id: str
    question: str
    answer: str
    exact_quote: str
    evidence_id: str
    scope_status: str  # must be "unknown" under STR-102
    fiscal_year: Optional[int] = None
    faculty: Optional[str] = None
    admission_category: Optional[str] = None
    scope_source_ref: Optional[str] = None
    source_sha256: Optional[str] = None
    normalized_start: Optional[int] = None
    normalized_end: Optional[int] = None
    quote_positions: Optional[Tuple[int, int]] = None
    scope_proof: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        # STR-076 & STR-102 Invariant: PR #286 is the sole g2 baseline; no new VERIFIED promotion path is allowed
        if self.scope_status == "unknown":
            if (
                self.fiscal_year is not None
                or self.faculty is not None
                or self.admission_category is not None
                or self.scope_source_ref is not None
                or self.scope_proof is not None
            ):
                raise ValueError(
                    f"STR-076 VIOLATION: unknown scope FAQ record '{self.faq_id}' cannot carry fiscal_year, faculty, admission_category, scope_source_ref, or scope_proof"
                )
        elif self.scope_status == "verified":
            raise ValueError(
                f"STR-076 / STR-102 VIOLATION: Verified scope FAQ record '{self.faq_id}' cannot be constructed in PR #306; no new VERIFIED promotion path is permitted (PR #286 is sole g2 baseline)"
            )
        else:
            raise ValueError(f"Invalid scope_status: {self.scope_status}")


def parse_faq_candidate(
    faq_id: str,
    source_id: str,
    raw_question: str,
    raw_answer: str,
    evidence_id: str,
    scope_context: Optional[Dict[str, Any]] = None,
) -> FAQRecord:
    """Parse raw FAQ Q&A pair and strictly preserve STR-076 / STR-102 UNKNOWN scope.

    Caller-supplied `scope_context` fields (`fiscal_year`, `faculty`, `scope_verified_by_source`,
    `scope_source_ref`, `scope_proof`) never promote a candidate to 'verified' (STR-101 / STR-102).
    `source_sha256` is computed only when authentic `source_document_text` containing the
    answer is provided; it is never synthesized from a made-up 'Q:/A:' string.
    """
    q_clean = " ".join(raw_question.split())
    a_clean = " ".join(raw_answer.split())

    ctx = scope_context or {}
    raw_source_doc = ctx.get("source_document_text")
    if isinstance(raw_source_doc, str) and raw_source_doc.strip() and a_clean in raw_source_doc:
        doc_sha256: Optional[str] = hashlib.sha256(raw_source_doc.encode("utf-8")).hexdigest()
        ans_start: Optional[int] = raw_source_doc.index(a_clean)
        ans_end: Optional[int] = ans_start + len(a_clean)
        quote = raw_source_doc[ans_start:ans_end]
        positions: Optional[Tuple[int, int]] = (ans_start, ans_end)
    else:
        doc_sha256 = None
        ans_start = None
        ans_end = None
        quote = a_clean
        positions = None

    return FAQRecord(
        faq_id=faq_id,
        source_id=source_id,
        question=q_clean,
        answer=a_clean,
        exact_quote=quote,
        evidence_id=evidence_id,
        scope_status="unknown",
        fiscal_year=None,
        faculty=None,
        admission_category=None,
        scope_source_ref=None,
        source_sha256=doc_sha256,
        normalized_start=ans_start,
        normalized_end=ans_end,
        quote_positions=positions,
        scope_proof=None,
    )


def _derive_condition_sentence(raw_sentence: str) -> str:
    """Derive a neutral guidance summary from raw FAQ sentence without copying imperative instructions."""
    cleaned = _PLANTED_EV_RE.sub("", raw_sentence).strip().rstrip("。").strip()
    if not cleaned:
        return ""
    if "下線" in cleaned:
        return "生成AIによる生成・修正箇所への下線等の明示条件が案内されています"
    if "画像" in cleaned:
        return "AIで作成した画像・図・表等の明示条件が案内されています"
    return cleaned


def _format_cited_answer(answer: str, evidence_id: str) -> str:
    """Attach evidence citation [EV-...] to every derived sentence in the answer."""
    if "。" in answer:
        sentences = [s.strip() for s in answer.split("。") if s.strip()]
        derived = [_derive_condition_sentence(s) for s in sentences]
        derived = [d for d in derived if d]
        return " ".join(f"{d}。[{evidence_id}]" for d in derived)
    derived_single = _derive_condition_sentence(answer)
    return f"{derived_single} [{evidence_id}]"


def render_unconfirmed_faq_section(records: List[FAQRecord]) -> str:
    """Render isolated unconfirmed FAQ section with owner-adopted preamble and per-sentence citations."""
    unknown_records = [r for r in records if r.scope_status == "unknown"]
    if not unknown_records:
        return ""

    lines = [
        UNCONFIRMED_SECTION_HEADING,
        UNCONFIRMED_PREAMBLE_TEXT,
        "",
    ]

    for r in unknown_records:
        lines.append(f"- 質問: {r.question}")
        lines.append(f"  回答概要: {_format_cited_answer(r.answer, r.evidence_id)}")

    return "\n".join(lines)


def _find_year_or_faculty_leaks(body_text: str) -> List[str]:
    """Detect concrete fiscal year or faculty/college/school name leaks across all notations."""
    norm = unicodedata.normalize("NFKC", body_text)
    leaks: List[str] = []

    year_patterns = [
        r"(?:19|20)\d{2}\s*(?:年度|年)",
        r"(?<!\d)[2-9]\d\s*年度",
        r"(?:19|20)\d{2}\s*(?:春|秋|夏|冬|4月|9月|10月)\s*(?:入学|募集|出願)?",
        r"(?:19|20)\d{2}\s*/\s*(?:19|20|\d{2})\d{0,2}",
        r"(?:19|20)\d{2}-[01]\d",
        r"FY\s*(?:19|20)\d{2}",
        r"[〇零一二三四五六七八九]{4}\s*(?:年度|年)",
        r"(?:令和|平成|昭和)\s*(?:元|[0-9]+|[〇零一二三四五六七八九十]+)\s*(?:年度|年|入試)?",
        r"(?<![A-Za-z])[RHRh]\s*(?:元|[1-9][0-9]*)\s*(?:年度|年|入試|の|春|秋)?",
    ]
    for pat in year_patterns:
        for m in re.finditer(pat, norm):
            leaks.append(m.group(0))

    faculty_patterns = [
        r"[一-龠ァ-ヶー・]{2,}(?:学部|学群|学類|研究科)",
    ]
    for pat in faculty_patterns:
        for m in re.finditer(pat, norm):
            leaks.append(m.group(0))

    return leaks


def verify_unconfirmed_faq_section(section_text: str, expected_records: List[FAQRecord]) -> Tuple[bool, List[str]]:
    """Verify integrity and exact controlled rendering of unconfirmed FAQ section."""
    errors: List[str] = []

    if UNCONFIRMED_SECTION_HEADING not in section_text:
        errors.append("Missing required unconfirmed section heading")

    if UNCONFIRMED_PREAMBLE_TEXT not in section_text:
        errors.append("Missing owner-adopted unconfirmed preamble text")

    if section_text.count(UNCONFIRMED_SECTION_HEADING) > 1:
        errors.append("Duplicate unconfirmed section heading detected")

    # Strip the single authorized heading and preamble before scanning for year/faculty leaks
    body_for_leak_scan = section_text.replace(UNCONFIRMED_SECTION_HEADING, "", 1).replace(UNCONFIRMED_PREAMBLE_TEXT, "", 1)
    leaks = _find_year_or_faculty_leaks(body_for_leak_scan)

    unknown_records = [r for r in expected_records if r.scope_status == "unknown"]
    for r in unknown_records:
        leaks.extend(_find_year_or_faculty_leaks(r.question))
        leaks.extend(_find_year_or_faculty_leaks(r.answer))
        if _PLANTED_EV_RE.search(r.question) or _PLANTED_EV_RE.search(r.answer):
            errors.append(
                f"STR-076 VIOLATION: Planted evidence tag inside raw FAQ text for record {r.faq_id}"
            )

    if leaks:
        errors.append(f"STR-076 VIOLATION: Unauthorized fiscal year or faculty leaked in unconfirmed section: {leaks}")

    allowed_ev_tags = {f"[{r.evidence_id}]" for r in unknown_records}
    found_ev_tags = set(_PLANTED_EV_RE.findall(section_text))
    unauthorized_tags = found_ev_tags - allowed_ev_tags
    if unauthorized_tags:
        errors.append(
            f"SEGREGATION VIOLATION: Unauthorized evidence tags in unconfirmed section: {sorted(unauthorized_tags)}"
        )

    # Check evidence IDs for unknown records
    for r in unknown_records:
        ev_tag = f"[{r.evidence_id}]"
        if ev_tag not in section_text:
            errors.append(f"Missing required evidence citation '{ev_tag}' for FAQ record {r.faq_id}")

    # Enforce controlled rendering exact match (rejects fabricated answers, extra uncited lines, or duplicated text)
    expected_rendering = render_unconfirmed_faq_section(expected_records)
    if section_text != expected_rendering:
        errors.append("CONTROLLED_RENDERING_MISMATCH: Section text does not match canonical controlled rendering")

    return len(errors) == 0, errors
