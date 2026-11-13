"""Cross-field consistency checks between an article claim and its evidence:
quota scope, university/faculty/method confusion, and numeric-to-citation
traceability.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any


@dataclasses.dataclass
class ConsistencyIssue:
    category: str
    detail: str


def check_quota_scope(claim: dict[str, Any], evidence: dict[str, Any]) -> ConsistencyIssue | None:
    """A quota (募集人数) number is only valid for the exact
    (university, faculty, department, admission_method, fiscal_year) tuple
    it was published under. Reusing a quota across a different method or
    department is the "募集人数の適用範囲" bug this guards against.
    """
    scope_fields = ["university", "faculty", "admission_method", "fiscal_year"]
    mismatches = [f for f in scope_fields if claim.get(f) is not None and claim.get(f) != evidence.get(f)]
    if claim.get("department") and evidence.get("department") and claim["department"] != evidence["department"]:
        mismatches.append("department")
    if mismatches:
        return ConsistencyIssue(
            "quota_scope_mismatch",
            f"claim's quota scope differs from its cited evidence on: {mismatches}",
        )
    return None


def check_entity_confusion(claim_text: str, evidence: dict[str, Any]) -> ConsistencyIssue | None:
    """Flags a claim that names a university/faculty/method in its text that
    does not match the entity its cited evidence actually describes — the
    "大学・学部・方式の混同" bug (e.g. citing Faculty-of-Science evidence
    while the sentence talks about the Faculty of Engineering).
    """
    missing = []
    for field in ("university", "faculty", "admission_method"):
        value = evidence.get(field)
        if value and value not in claim_text:
            missing.append((field, value))
    if missing:
        return ConsistencyIssue(
            "entity_mismatch",
            f"claim text does not mention evidence's {', '.join(f'{f}={v!r}' for f, v in missing)}",
        )
    return None


_NUMBER_WITH_UNIT_RE = re.compile(r"\d[\d,]*\s*(?:人|名|名程度|名前後|倍|%|％)")
_CITATION_MARKER_RE = re.compile(r"\[(EV-[A-Za-z0-9_\-]+)\]")


def extract_citation_ids(text: str) -> set[str]:
    """All evidence ids referenced via [EV-xxxx] markers anywhere in text."""
    return {m.group(1) for m in _CITATION_MARKER_RE.finditer(text)}


def check_numeric_citation_traceability(claim_text: str, known_evidence_ids: set[str]) -> list[ConsistencyIssue]:
    """Every number-with-unit in an article's claim text (e.g. "約120名") should
    be followed (within a short window) by a citation marker like "[EV-0001]"
    that resolves to a real evidence id. Flags unsupported numbers and
    citations that point at an unknown evidence id.
    """
    issues: list[ConsistencyIssue] = []
    for match in _NUMBER_WITH_UNIT_RE.finditer(claim_text):
        window = claim_text[match.end(): match.end() + 20]
        marker = _CITATION_MARKER_RE.search(window)
        if not marker:
            issues.append(
                ConsistencyIssue("unsupported_number", f"number {match.group()!r} has no nearby citation marker")
            )
        elif marker.group(1) not in known_evidence_ids:
            issues.append(
                ConsistencyIssue(
                    "unknown_citation",
                    f"number {match.group()!r} cites {marker.group(1)!r}, which is not a known evidence id",
                )
            )
    return issues
