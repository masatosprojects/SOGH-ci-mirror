"""Compare two editions of a source: which pages were added, removed, moved
or changed, and — what matters most for accuracy — which changed lines carry
a different number, date, amount or other quantity.

    python -m src.versioning.diff --old old.snapshot.json --new new.snapshot.json [--json-out out.json]

Exit status: 0 when the editions are identical, 1 when anything differs.
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from src.verify.strict_claims import extract_quantities
from src.versioning.snapshot import SourceSnapshot, load_snapshot, normalize

MATCH_THRESHOLD = 0.4  # shingle similarity below which two pages are treated as different pages


@dataclasses.dataclass
class PageMatch:
    old_page: int
    new_page: int
    similarity: float
    identical: bool

    @property
    def moved(self) -> bool:
        return self.old_page != self.new_page


@dataclasses.dataclass
class LineChange:
    old_page: int
    new_page: int
    kind: str  # modified | added | removed
    old: str
    new: str
    value_change: bool
    old_values: list[str]
    new_values: list[str]


@dataclasses.dataclass
class SnapshotDiff:
    same_edition: bool  # identical sha256
    identical_text: bool
    pages_added: list[int]
    pages_removed: list[int]
    page_map: list[PageMatch]
    changes: list[LineChange]

    @property
    def value_changes(self) -> list[LineChange]:
        return [c for c in self.changes if c.value_change]

    def to_dict(self) -> dict[str, Any]:
        return {
            "same_edition": self.same_edition,
            "identical_text": self.identical_text,
            "pages_added": self.pages_added,
            "pages_removed": self.pages_removed,
            "pages_moved": [{"from": m.old_page, "to": m.new_page} for m in self.page_map if m.moved],
            "changes": [dataclasses.asdict(c) for c in self.changes],
            "summary": {
                "pages_added": len(self.pages_added),
                "pages_removed": len(self.pages_removed),
                "pages_moved": sum(m.moved for m in self.page_map),
                "pages_changed": sum(not m.identical for m in self.page_map),
                "changed_lines": len(self.changes),
                "value_changes": len(self.value_changes),
            },
        }


def _shingles(text: str, k: int = 5) -> set[str]:
    return {text[i: i + k] for i in range(max(0, len(text) - k + 1))} or {text}


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    sa, sb = _shingles(a), _shingles(b)
    return len(sa & sb) / len(sa | sb)


def match_pages(old: list[str], new: list[str]) -> tuple[list[PageMatch], list[int], list[int]]:
    """Pair pages of two editions by content, not by number, so an inserted
    page does not make every later page look changed."""
    old_n, new_n = [normalize(p) for p in old], [normalize(p) for p in new]
    matches: list[PageMatch] = []
    free_old, free_new = set(range(len(old_n))), set(range(len(new_n)))

    # 1) identical text; prefer the same page number
    for j in sorted(free_new):
        candidates = [i for i in free_old if old_n[i] == new_n[j]]
        if candidates:
            i = j if j in candidates else min(candidates, key=lambda c: abs(c - j))
            matches.append(PageMatch(i + 1, j + 1, 1.0, True))
            free_old.discard(i)
            free_new.discard(j)

    # 2) most similar remaining pairs first
    scored = sorted(
        ((_similarity(old_n[i], new_n[j]), i, j) for i in free_old for j in free_new),
        key=lambda t: (-t[0], abs(t[1] - t[2])),
    )
    for score, i, j in scored:
        if score < MATCH_THRESHOLD:
            break
        if i in free_old and j in free_new:
            matches.append(PageMatch(i + 1, j + 1, round(score, 4), False))
            free_old.discard(i)
            free_new.discard(j)
    matches.sort(key=lambda m: m.new_page)
    return matches, sorted(j + 1 for j in free_new), sorted(i + 1 for i in free_old)


def _sentences(page_text: str) -> list[str]:
    flat = re.sub(r"\s*\n\s*", "", page_text)
    return [s for s in re.split(r"(?<=。)", flat) if s.strip()]


def _values(block: str) -> set[str]:
    """Quantities with a unit (persons:5, date:…) plus EVERY digit run: a table cell
    holds a bare "5" with no unit, and a changed bare number must not slip by.
    Over-reporting is deliberate here — a missed change is the costly error."""
    found = {f"{q.kind}:{q.value}" for _, q in extract_quantities(block)}
    found |= {f"number:{n}" for n in re.findall(r"\d+", unicodedata.normalize("NFKC", block))}
    return found


def _line_changes(old_page: int, new_page: int, old_text: str, new_text: str) -> list[LineChange]:
    old_s, new_s = _sentences(old_text), _sentences(new_text)
    matcher = difflib.SequenceMatcher(None, [normalize(s) for s in old_s], [normalize(s) for s in new_s], autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_block, new_block = "".join(old_s[i1:i2]), "".join(new_s[j1:j2])
        old_v, new_v = _values(old_block), _values(new_block)
        kind = {"replace": "modified", "delete": "removed", "insert": "added"}[tag]
        changes.append(LineChange(old_page, new_page, kind, old_block, new_block, old_v != new_v,
                                  sorted(old_v - new_v), sorted(new_v - old_v)))
    return changes


def diff_snapshots(old: SourceSnapshot, new: SourceSnapshot) -> SnapshotDiff:
    matches, added, removed = match_pages(old.pages, new.pages)
    changes: list[LineChange] = []
    for m in matches:
        if not m.identical:
            changes.extend(_line_changes(m.old_page, m.new_page, old.pages[m.old_page - 1], new.pages[m.new_page - 1]))
    identical_text = not added and not removed and all(m.identical and not m.moved for m in matches)
    return SnapshotDiff(old.sha256 == new.sha256, identical_text, added, removed, matches, changes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = diff_snapshots(load_snapshot(args.old), load_snapshot(args.new)).to_dict()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["identical_text"] and not result["changes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
