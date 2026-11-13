"""作業基準日（as-of date）の検証 — Issue #11.

A draft says "作業基準日：2026-11-01": the day its facts were last checked, and the day
its time-relative wording ("既に経過しています", "これから実施") is true *as of*. Nothing
used to check it. This module does, without ever reading the clock:

  as_of_missing             no as-of date (only when `require_as_of`; older drafts have none)
  as_of_unparsable          "作業基準日" is there but no date can be read
  as_of_conflict            two different as-of dates in one article
  as_of_in_future           the as-of date is after `reference_date` (the caller says what "now" is)
  as_of_before_retrieval    the as-of date is before a cited evidence's retrieved_at: a draft cannot
                            describe a state that was fetched later
  elapsed_claim_mismatch    wording says the event is over ("締切済み", "既に経過") but the cited
                            evidence puts it AFTER the as-of date
  upcoming_claim_mismatch   wording says it is still ahead ("これから実施", "受付中") but the cited
                            evidence puts it BEFORE the as-of date

Rules that keep this from crying wolf:
* No clock. `reference_date` is a parameter; without it the "in the future" check is skipped.
  Tests use fixed dates.
* The event date is the END of the cited evidence (end / date / latest of dates). A date equal
  to the as-of date is never flagged: a date-only comparison cannot tell whether 09:00 has passed.
* Sentences are matched to evidence by the citation governing them. A sentence with no citation
  ("記載する出願期間・面接日は既に経過しています") is matched to the article's cited evidence only
  through the fact_key's `temporal_keywords` in the registry; with no match it is left alone.
"""
from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any

from src.verify.consistency import ConsistencyIssue, extract_citation_ids
from src.verify.fact_registry import Registry, get_registry
from src.verify.strict_claims import sentences_with_citations

_DATE = r"(?:(?P<iso>\d{4}-\d{2}-\d{2})|(?:令和(?P<ry>\d{1,2})|(?P<y>\d{4}))年(?P<m>\d{1,2})月(?P<d>\d{1,2})日)"
_AS_OF = re.compile(r"作業基準日\s*:?\s*" + _DATE)
_MARKER = re.compile(r"作業基準日")


def _to_date(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def extract_as_of(text: str) -> tuple[list[datetime.date], int]:
    """(as-of dates found, number of "作業基準日" markers). Normalised first, so full-width
    digits and colons, 令和 and ISO forms all work."""
    norm = unicodedata.normalize("NFKC", text)
    dates: list[datetime.date] = []
    for m in _AS_OF.finditer(norm):
        try:
            if m.group("iso"):
                dates.append(datetime.date.fromisoformat(m.group("iso")))
            else:
                year = int(m.group("ry")) + 2018 if m.group("ry") else int(m.group("y"))
                dates.append(datetime.date(year, int(m.group("m")), int(m.group("d"))))
        except ValueError:
            continue  # e.g. 2026-02-30: counted as a marker, not as a date
    return dates, len(_MARKER.findall(norm))


def event_end(evidence: dict[str, Any], registry: Registry | None = None) -> datetime.date | None:
    """When the cited event is over. If the registry names the fact_key's `event_end_field`
    (fee_refund.deadline, maintenance_notice.outage_end) that field alone decides — null means
    "no end known", never "use some other date". Otherwise: its `end`, its `date`, or the latest of its `dates`."""
    value = evidence.get("value")
    if not isinstance(value, dict):
        return None
    field = (registry or get_registry()).event_end_field(evidence.get("fact_key"))
    if field:
        return _to_date(value.get(field))
    candidates = [value.get("end"), value.get("date"), *(value.get("dates") or [])]
    found = [d for d in (_to_date(c) for c in candidates) if d]
    return max(found) if found else None


def check_as_of(
    text: str,
    evidence_by_id: dict[str, dict[str, Any]],
    *,
    reference_date: datetime.date | str | None = None,
    require_as_of: bool = False,
    registry: Registry | None = None,
) -> list[ConsistencyIssue]:
    registry = registry or get_registry()
    issues: list[ConsistencyIssue] = []
    cited = sorted(e for e in extract_citation_ids(text) if e in evidence_by_id)
    dates, markers = extract_as_of(text)

    if markers and not dates:
        issues.append(ConsistencyIssue("as_of_unparsable", "「作業基準日」はあるが、日付として読めない（例：作業基準日：2026-11-01）"))
    if not markers:
        if require_as_of and cited:
            issues.append(ConsistencyIssue("as_of_missing", "作業基準日が無い：時間に依存する記述（締切・実施日）の基準が分からない"))
        return issues
    if not dates:
        return issues
    distinct = sorted(set(dates))
    if len(distinct) > 1:
        issues.append(ConsistencyIssue("as_of_conflict", f"異なる作業基準日が複数ある: {[d.isoformat() for d in distinct]}"))
    as_of = dates[0]

    ref = _to_date(reference_date)
    if ref and as_of > ref:
        issues.append(ConsistencyIssue("as_of_in_future", f"作業基準日 {as_of} が基準となる現在日 {ref} より未来"))
    retrieved = {e: d for e in cited if (d := _to_date(evidence_by_id[e].get("retrieved_at")))}
    late = sorted(e for e, d in retrieved.items() if as_of < d)
    if late:
        issues.append(ConsistencyIssue(
            "as_of_before_retrieval",
            f"作業基準日 {as_of} が、根拠の取得日（{max(retrieved[e] for e in late)}）より前: {late[:3]}"))

    cues = registry.temporal_cues
    seen: set[tuple[str, str, str]] = set()
    for sentence, ids in sentences_with_citations(text):
        elapsed = next((c for c in cues["elapsed"] if c in sentence), None)
        upcoming = next((c for c in cues["upcoming"] if c in sentence), None)
        if not (elapsed or upcoming):
            continue
        resolved = [e for e in sorted(ids) if e in evidence_by_id]
        if resolved:
            candidates = [e for e in resolved
                          if len(resolved) == 1 or not registry.temporal_keywords(evidence_by_id[e].get("fact_key"))
                          or any(k in sentence for k in registry.temporal_keywords(evidence_by_id[e].get("fact_key")))]
        else:
            candidates = [e for e in cited if any(k in sentence for k in registry.temporal_keywords(evidence_by_id[e].get("fact_key")))]
        for eid in candidates:
            end = event_end(evidence_by_id[eid], registry)
            if end is None:
                continue
            fact = evidence_by_id[eid].get("fact_key")
            if elapsed and end > as_of and (eid, "elapsed", elapsed) not in seen:
                seen.add((eid, "elapsed", elapsed))
                issues.append(ConsistencyIssue(
                    "elapsed_claim_mismatch",
                    f"「{elapsed}」と書くが、{eid}（{fact}）の終了日 {end} は作業基準日 {as_of} より後（まだ終わっていない）"))
            if upcoming and end < as_of and (eid, "upcoming", upcoming) not in seen:
                seen.add((eid, "upcoming", upcoming))
                issues.append(ConsistencyIssue(
                    "upcoming_claim_mismatch",
                    f"「{upcoming}」と書くが、{eid}（{fact}）の終了日 {end} は作業基準日 {as_of} より前（既に終わっている）"))
    return issues
