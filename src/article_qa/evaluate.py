"""Whole-article evaluation: ties src/verify (fact-checking against
evidence) and src/article_qa.checks (text-quality heuristics) together into
one report for a single article.

This is the "記事中の数値と根拠IDの整合性チェック" + "大学・学部・方式の混同検出"
+ "募集人数の適用範囲チェック" + article-QA checks, run together, per
docs/NEXT_SESSION.md's next-task list.
"""
from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any

from src.article_qa.checks import (
    find_overconfident_assertions,
    find_unsupported_numbers,
    has_sufficient_caveat,
)
from src.verify.consistency import (
    check_entity_confusion,
    check_quota_scope,
    extract_citation_ids,
)
from src.verify.date_year import check_claim_matches_evidence_year
from src.verify.as_of import check_as_of
from src.verify.fact_registry import Registry, get_registry
from src.verify.qualitative import check_qualitative, semantic_coverage
from src.verify.strict_claims import check_article_strict


@dataclasses.dataclass
class ArticleReport:
    article_id: str
    ok: bool
    findings: list[dict[str, str]]
    # registry warnings/notices about the cited evidence (e.g. a proposed fact_key,
    # an unregistered value field). They never change `ok`, but they are not hidden.
    notices: list[dict[str, str]] = dataclasses.field(default_factory=list)
    # what the qualitative checks looked at and what NO rule covers (never assumed correct)
    coverage: dict[str, Any] = dataclasses.field(default_factory=dict)


def evaluate_article(
    article_id: str,
    text: str,
    claim: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    registry: Registry | None = None,
    reference_date: datetime.date | str | None = None,
    require_as_of: bool = False,
) -> ArticleReport:
    """Evaluate one article.

    Args:
        article_id: identifier for reporting only.
        text: the article's body text (should contain [EV-xxxx] citation markers).
        claim: the article's own stated scope, e.g.
            {"university": ..., "faculty": ..., "admission_method": ..., "fiscal_year": 2026}
        evidence_by_id: all known evidence records, keyed by evidence_id — used to
            resolve whatever the article actually cites and to catch citations
            that point at nothing.
    """
    findings: list[dict[str, str]] = []
    notices: list[dict[str, str]] = []

    def add(category: str, detail: str) -> None:
        findings.append({"category": category, "detail": detail})

    cited_ids = extract_citation_ids(text)
    # covers both "unsupported_number" (no citation marker at all) and
    # "unknown_citation" (marker present but doesn't resolve) in one pass
    for issue in find_unsupported_numbers(text, known_evidence_ids=set(evidence_by_id)):
        add(issue.category, issue.detail)

    for issue in find_overconfident_assertions(text):
        add(issue.category, issue.detail)

    if not has_sufficient_caveat(text):
        add("missing_caveat", "article cites changeable figures but has no official-source caveat phrase")

    cited_evidence = [evidence_by_id[eid] for eid in cited_ids if eid in evidence_by_id]
    if not cited_evidence:
        add("no_resolved_evidence", "article cites no evidence id that resolves to a known record")
    else:
        year_result = check_claim_matches_evidence_year(
            claim.get("fiscal_year"), [e["fiscal_year"] for e in cited_evidence]
        )
        if not year_result.ok:
            add("fiscal_year_mismatch", year_result.reason or "fiscal year mismatch")

        for evidence in cited_evidence:
            scope_issue = check_quota_scope(claim, evidence)
            if scope_issue:
                add(scope_issue.category, scope_issue.detail)
            confusion_issue = check_entity_confusion(text, evidence)
            if confusion_issue:
                add(confusion_issue.category, confusion_issue.detail)

    # Issue #7: a valid citation id must also carry the right *value*
    # (numbers, dates, units, scope), not just exist.
    registry = registry or get_registry()
    strict_notes: list = []
    for issue in check_article_strict(text, claim, evidence_by_id, registry, notices=strict_notes):
        if issue.category == "unknown_citation":
            cited = re.search(r"'(EV-[^']+)'", issue.detail)
            if cited and any(
                f["category"] == "unknown_citation" and repr(cited.group(1)) in f["detail"] for f in findings
            ):
                continue  # already reported next to a number by the older check
        add(issue.category, issue.detail)

    # not wrong, but not checked either (Issue #13): numbers the QA could not classify, a range end with no evidence
    for issue in strict_notes:
        notices.append({"severity": "warning", "category": issue.category, "detail": issue.detail})

    # 作業基準日 (Issue #11): the as-of date, and wording about deadlines relative to it
    for issue in check_as_of(text, evidence_by_id, reference_date=reference_date, require_as_of=require_as_of, registry=registry):
        add(issue.category, issue.detail)

    # meaning without numbers (Issue #9): yes/no flips, dropped limits and exceptions, omitted list items
    for issue in check_qualitative(text, evidence_by_id, registry):
        add(issue.category, issue.detail)

    # fact_key registry: an unregistered fact_key is an error (never "verified");
    # warnings and notices are reported separately and do not fail the article.
    for eid in sorted(cited_ids & set(evidence_by_id)):
        for issue in registry.check_record(evidence_by_id[eid], eid):
            if issue.severity == "error":
                add(issue.category, f"{eid}: {issue.detail}")
            else:
                notices.append({"severity": issue.severity, "category": issue.category, "detail": f"{eid}: {issue.detail}"})

    return ArticleReport(article_id=article_id, ok=not findings, findings=findings, notices=notices,
                         coverage=semantic_coverage(text, evidence_by_id, registry))
