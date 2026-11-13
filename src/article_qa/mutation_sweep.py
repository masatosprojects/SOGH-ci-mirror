"""Mutation sweep: how many single-digit edits to an article does the QA catch?

For every number in an article body, replace it with (number + 1) and re-run
evaluate_article. A mutation that produces no finding "survived" — a gap the
QA could not see. Survivors are reported, not hidden: some are structural
references that are *meant* to be ignored (page numbers, 第2次選考), the rest
are real blind spots.

    python -m src.article_qa.mutation_sweep <articles.json> [--json-out path]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.article_qa.evaluate import evaluate_article

_NUMBER_RE = re.compile(r"\d+")
_SKIP_SECTION = "## 根拠資料"


_MARKER_RE = re.compile(r"\[EV-[A-Za-z0-9_\-]+\]")
_AS_OF_RE = re.compile(r"作業基準日：\d{4}-\d{2}-\d{2}")


def _mutable_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, class) for every number in the body (the 根拠資料 list is
    checked separately). class: citation_id | as_of_date | body."""
    body_end = text.find(_SKIP_SECTION)
    body_end = len(text) if body_end == -1 else body_end
    marker_spans = [m.span() for m in _MARKER_RE.finditer(text[:body_end])]
    as_of_spans = [m.span() for m in _AS_OF_RE.finditer(text[:body_end])]
    spans = []
    for m in _NUMBER_RE.finditer(text[:body_end]):
        if any(a <= m.start() < b for a, b in marker_spans):
            cls = "citation_id"
        elif any(a <= m.start() < b for a, b in as_of_spans):
            cls = "as_of_date"
        else:
            cls = "body"
        spans.append((m.start(), m.end(), cls))
    return spans


def sweep_article(article: dict[str, Any], evidence: dict[str, Any], **qa: Any) -> dict[str, Any]:
    """`qa` is passed to evaluate_article (e.g. reference_date, require_as_of)."""
    text = article["text"]
    baseline = evaluate_article(article["article_id"], text, article["claim"], evidence, **qa)
    spans = _mutable_spans(text)
    by_class: dict[str, dict[str, int]] = {}
    survivors = []
    for start, end, cls in spans:
        original = text[start:end]
        mutated_number = str(int(original) + 1).zfill(len(original))
        mutated = text[:start] + mutated_number + text[end:]
        report = evaluate_article(article["article_id"], mutated, article["claim"], evidence, **qa)
        stats = by_class.setdefault(cls, {"mutations": 0, "detected": 0})
        stats["mutations"] += 1
        if report.findings:
            stats["detected"] += 1
        else:
            survivors.append({"class": cls, "offset": start, "from": original, "to": mutated_number,
                              "context": text[max(0, start - 14): end + 14].replace("\n", " ")})
    return {"article_id": article["article_id"], "baseline_ok": baseline.ok, "mutations": len(spans),
            "detected": len(spans) - len(survivors), "survived": len(survivors),
            "by_class": by_class, "survivors": survivors}


def sweep(data: dict[str, Any], **qa: Any) -> dict[str, Any]:
    per_article = [sweep_article(a, data["evidence"], **qa) for a in data["articles"]]
    total = sum(a["mutations"] for a in per_article)
    detected = sum(a["detected"] for a in per_article)
    by_class: dict[str, dict[str, int]] = {}
    for a in per_article:
        for cls, s in a["by_class"].items():
            agg = by_class.setdefault(cls, {"mutations": 0, "detected": 0})
            agg["mutations"] += s["mutations"]
            agg["detected"] += s["detected"]
    return {"mutations": total, "detected": detected, "survived": total - detected,
            "detection_rate": round(detected / total, 4) if total else None,
            "by_class": by_class, "per_article": per_article}


def swap_sweep(data: dict[str, Any], **qa: Any) -> dict[str, Any]:
    """Citation swap sweep (Issue #10): replace each citation in the body, one at a time, by EVERY other
    evidence id of the same delivery. Each result is a *real* but wrong citation, so no "unknown id"
    check can help; only the meaning of the sentence can. A swap that still passes is reported.

    Some pairs cannot be told apart by wording at all (two facts a sentence could equally be about);
    those show up as survivors and are the honest measure of what this check cannot see."""
    evidence_ids = list(data["evidence"])
    total = detected = 0
    survivors = []
    for article in data["articles"]:
        text = article["text"]
        body_end = text.find(_SKIP_SECTION)
        body_end = len(text) if body_end == -1 else body_end
        for m in _MARKER_RE.finditer(text[:body_end]):
            original = m.group(0)[1:-1]
            for other in evidence_ids:
                if other == original:
                    continue
                mutated = text[:m.start()] + f"[{other}]" + text[m.end():]
                report = evaluate_article(article["article_id"], mutated, article["claim"], data["evidence"], **qa)
                total += 1
                if report.findings:
                    detected += 1
                else:
                    survivors.append({
                        "article": article["article_id"][-24:], "from": data["evidence"][original]["fact_key"],
                        "to": data["evidence"][other]["fact_key"], "context": text[max(0, m.start() - 24): m.start()].replace("\n", " ")})
    return {"swaps": total, "detected": detected, "survived": total - detected,
            "detection_rate": round(detected / total, 4) if total else None, "survivors": survivors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("articles_json", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--reference-date", default=None, help="YYYY-MM-DD: what \"now\" is for the as-of date checks")
    parser.add_argument("--require-as-of", action="store_true")
    args = parser.parse_args(argv)
    result = sweep(json.loads(args.articles_json.read_text(encoding="utf-8")), reference_date=args.reference_date,
                   require_as_of=args.require_as_of)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
