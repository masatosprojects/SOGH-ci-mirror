"""Article-text quality checks for the note bot's output.

These operate on plain article text (and optionally a small amount of
metadata) and never touch the note bot itself — they're an independent
QA pass meant to run on drafts or published articles and emit a report,
per Phase D / CLAUDE.md ("既存のnoteボットを変更しない").
"""
from __future__ import annotations

import dataclasses
import re
from collections import Counter

from src.verify.consistency import check_numeric_citation_traceability

__all__ = [
    "Finding",
    "find_unsupported_numbers",
    "find_overconfident_assertions",
    "has_sufficient_caveat",
    "near_duplicate_score",
    "find_near_duplicates",
    "find_overused_phrases",
]


@dataclasses.dataclass
class Finding:
    category: str
    detail: str


def find_unsupported_numbers(text: str, known_evidence_ids: set[str]) -> list[Finding]:
    """事実に基づかない数値の検出: reuses the citation-traceability check."""
    issues = check_numeric_citation_traceability(text, known_evidence_ids)
    return [Finding(i.category, i.detail) for i in issues]


_OVERCONFIDENT_RE = re.compile(
    r"(必ず(合格|受かる)|絶対(に)?(合格|受かる)|100%|間違いなく|確実に(合格|受かる))"
)


def find_overconfident_assertions(text: str) -> list[Finding]:
    """不正確な断定の検出: flags language that promises exam outcomes with
    certainty admissions info can never actually guarantee.
    """
    findings = []
    for match in _OVERCONFIDENT_RE.finditer(text):
        findings.append(Finding("overconfident_assertion", f"text asserts certainty: {match.group()!r}"))
    return findings


_CAVEAT_PHRASES = (
    "最新情報は大学公式",
    "必ず大学公式サイト",
    "公式サイトでご確認",
    "変更される場合があります",
    "詳細は大学の発表を",
)


def has_sufficient_caveat(text: str) -> bool:
    """不十分な注意書きの検出: an admissions article citing numbers that can
    change (quotas, dates) should tell the reader to confirm with the
    official source. Returns False when no such caveat phrase is present.
    """
    return any(phrase in text for phrase in _CAVEAT_PHRASES)


def _shingles(text: str, k: int = 5) -> set[str]:
    normalized = re.sub(r"\s+", "", text)
    return {normalized[i : i + k] for i in range(max(0, len(normalized) - k + 1))}


def near_duplicate_score(text_a: str, text_b: str, k: int = 5) -> float:
    """Jaccard similarity over character k-shingles — language-agnostic,
    works fine on Japanese text without a tokenizer. 1.0 == identical.
    """
    a, b = _shingles(text_a, k), _shingles(text_b, k)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_near_duplicates(articles: dict[str, str], threshold: float = 0.8) -> list[Finding]:
    """重複記事の検出 across a corpus of (article_id -> text)."""
    findings = []
    ids = list(articles)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            score = near_duplicate_score(articles[ids[i]], articles[ids[j]])
            if score >= threshold:
                findings.append(
                    Finding("near_duplicate_article", f"{ids[i]} and {ids[j]} are {score:.0%} similar")
                )
    return findings


def find_overused_phrases(articles: dict[str, str], phrase_len: int = 12, min_occurrences: int = 5) -> list[Finding]:
    """テンプレート的な文章の過度な反復: finds fixed-length character n-grams
    that recur across many *different* articles far more than normal prose
    would, suggesting a template string is being stamped out verbatim.
    """
    counts: Counter[str] = Counter()
    for text in articles.values():
        normalized = re.sub(r"\s+", "", text)
        seen_in_this_article = {normalized[i : i + phrase_len] for i in range(max(0, len(normalized) - phrase_len + 1))}
        counts.update(seen_in_this_article)
    findings = []
    for phrase, count in counts.items():
        if count >= min_occurrences:
            findings.append(
                Finding("overused_template_phrase", f"{phrase!r} appears verbatim in {count} articles")
            )
    return findings
