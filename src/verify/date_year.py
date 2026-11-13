"""Date / fiscal-year plausibility checks.

Targets the "年度混在" (mixed fiscal years) failure mode: an article or
evidence record that states a fiscal year inconsistent with its own
retrieval date, or that mixes 学校年度 (April-start) reasoning incorrectly.
"""
from __future__ import annotations

import dataclasses
import datetime


@dataclasses.dataclass
class YearCheckResult:
    ok: bool
    reason: str | None = None


def japanese_fiscal_year(d: datetime.date) -> int:
    """Japan's fiscal/school year runs April 1 - March 31."""
    return d.year if d.month >= 4 else d.year - 1


def check_fiscal_year_plausible(
    fiscal_year: int,
    retrieved_at: datetime.date,
    *,
    max_years_ahead: int = 2,
    max_years_behind: int = 1,
) -> YearCheckResult:
    """A fiscal year cited by an evidence record should be within a small
    window of the date it was retrieved: admissions info is published up to
    ~2 school years ahead of the exam, and old articles may still reference
    last year's figures for comparison, but anything further out is almost
    always a 年度 bug (wrong year carried over, or a typo).
    """
    current_fy = japanese_fiscal_year(retrieved_at)
    if fiscal_year > current_fy + max_years_ahead:
        return YearCheckResult(False, f"fiscal_year {fiscal_year} is more than {max_years_ahead} years ahead of retrieval FY {current_fy}")
    if fiscal_year < current_fy - max_years_behind:
        return YearCheckResult(False, f"fiscal_year {fiscal_year} is more than {max_years_behind} year(s) behind retrieval FY {current_fy}")
    return YearCheckResult(True)


def check_claim_matches_evidence_year(claim_fiscal_year: int, evidence_fiscal_years: list[int]) -> YearCheckResult:
    """An article claim must cite evidence from the SAME fiscal year — citing
    a correct-looking number from the wrong year's announcement is the most
    common 年度混在 article bug.
    """
    if not evidence_fiscal_years:
        return YearCheckResult(False, "claim cites no evidence; cannot confirm fiscal year match")
    mismatched = [y for y in evidence_fiscal_years if y != claim_fiscal_year]
    if mismatched:
        return YearCheckResult(
            False,
            f"claim fiscal_year={claim_fiscal_year} but cited evidence has fiscal_year(s) {sorted(set(mismatched))}",
        )
    return YearCheckResult(True)
