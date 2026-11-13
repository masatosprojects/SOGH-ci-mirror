"""Notation sweep: do the same dates, written another way, still get the same verdict? (Issue #13)

For every full date ("2026年11月3日", optionally with a weekday and a time) in an article:

* INVARIANCE — rewrite it in each other notation (令和8年11月3日, R8.11.3, 2026/11/3, 二〇二六年十一月三日 ...).
  The article must still pass. A finding here is a FALSE POSITIVE caused by the notation.
* DETECTION — in the same notation, move the date by one day. The QA must report it.
  A mutation without a finding is a notation the QA cannot read.

Both numbers are reported with their denominators, and every survivor is listed.

    python -m src.article_qa.notation_sweep <export.json> [--json-out path]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path
from typing import Any, Callable

from src.article_qa.evaluate import evaluate_article

_DATE_RE = re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日")
_KANJI = "〇一二三四五六七八九"


def _kanji_number(n: int) -> str:
    """11 -> 十一, 3 -> 三, 30 -> 三十."""
    if n < 10:
        return _KANJI[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else _KANJI[tens]) + "十" + (_KANJI[ones] if ones else "")


def _reiwa(y: int) -> int:
    return y - 2018


NOTATIONS: dict[str, Callable[[datetime.date], str]] = {
    "gregorian": lambda d: f"{d.year}年{d.month}月{d.day}日",
    "reiwa": lambda d: f"令和{_reiwa(d.year)}年{d.month}月{d.day}日",
    "reiwa_kanji": lambda d: f"令和{_kanji_number(_reiwa(d.year))}年{_kanji_number(d.month)}月{_kanji_number(d.day)}日",
    "reiwa_abbr_dots": lambda d: f"R{_reiwa(d.year)}.{d.month}.{d.day}",
    "reiwa_abbr_slashes": lambda d: f"R{_reiwa(d.year)}/{d.month}/{d.day}",
    "slashes": lambda d: f"{d.year}/{d.month}/{d.day}",
    "dots": lambda d: f"{d.year}.{d.month}.{d.day}",
    "hyphens": lambda d: f"{d.year}-{d.month}-{d.day}",
    "kanji": lambda d: f"{''.join(_KANJI[int(c)] for c in str(d.year))}年{_kanji_number(d.month)}月{_kanji_number(d.day)}日",
    "fullwidth": lambda d: f"{d.year}年{d.month}月{d.day}日".translate(str.maketrans("0123456789", "０１２３４５６７８９")),
}


def _full_dates(text: str) -> list[tuple[int, int, datetime.date]]:
    body_end = text.find("## 根拠資料")
    body_end = len(text) if body_end == -1 else body_end
    out = []
    for m in _DATE_RE.finditer(text[:body_end]):
        try:
            out.append((m.start(), m.end(), datetime.date(int(m.group("y")), int(m.group("m")), int(m.group("d")))))
        except ValueError:
            continue
    return out


def _clean(text: str, evidence: dict[str, Any], article: dict[str, Any], **qa: Any) -> bool:
    return evaluate_article(article["article_id"], text, article["claim"], evidence, **qa).ok


def notation_sweep_article(article: dict[str, Any], evidence: dict[str, Any], **qa: Any) -> dict[str, Any]:
    text = article["text"]
    baseline_ok = _clean(text, evidence, article, **qa)
    stats = {n: {"invariance": [0, 0], "detection": [0, 0]} for n in NOTATIONS}
    false_positives: list[dict[str, str]] = []
    survivors: list[dict[str, str]] = []
    for start, end, day in _full_dates(text):
        for name, write in NOTATIONS.items():
            same = text[:start] + write(day) + text[end:]
            stats[name]["invariance"][1] += 1
            if _clean(same, evidence, article, **qa):
                stats[name]["invariance"][0] += 1
            else:
                false_positives.append({"notation": name, "written": write(day), "was": text[start:end]})
            moved = text[:start] + write(day + datetime.timedelta(days=1)) + text[end:]
            stats[name]["detection"][1] += 1
            if not _clean(moved, evidence, article, **qa):
                stats[name]["detection"][0] += 1
            else:
                survivors.append({"notation": name, "written": write(day + datetime.timedelta(days=1)), "was": text[start:end]})
    return {"baseline_ok": baseline_ok, "by_notation": stats, "false_positives": false_positives, "survivors": survivors}


def notation_sweep(export: dict[str, Any], **qa: Any) -> dict[str, Any]:
    total = {n: {"invariance": [0, 0], "detection": [0, 0]} for n in NOTATIONS}
    fps: list[dict[str, str]] = []
    surv: list[dict[str, str]] = []
    baselines = True
    for article in export["articles"]:
        r = notation_sweep_article(article, export["evidence"], **qa)
        baselines &= r["baseline_ok"]
        for name, s in r["by_notation"].items():
            for k in ("invariance", "detection"):
                total[name][k][0] += s[k][0]
                total[name][k][1] += s[k][1]
        fps += [dict(f, article=article["article_id"]) for f in r["false_positives"]]
        surv += [dict(s, article=article["article_id"]) for s in r["survivors"]]
    inv = [sum(t["invariance"][i] for t in total.values()) for i in (0, 1)]
    det = [sum(t["detection"][i] for t in total.values()) for i in (0, 1)]
    return {"all_baselines_ok": baselines, "by_notation": total, "invariance": inv, "detection": det,
            "false_positives": fps, "survivors": surv}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export")
    ap.add_argument("--json-out")
    ap.add_argument("--reference-date")
    args = ap.parse_args()
    data = json.loads(Path(args.export).read_text(encoding="utf-8"))
    r = notation_sweep(data, reference_date=args.reference_date, require_as_of=bool(args.reference_date))
    print(f"invariance (no false positive): {r['invariance'][0]}/{r['invariance'][1]}  detection (date +1): {r['detection'][0]}/{r['detection'][1]}")
    for name, s in r["by_notation"].items():
        print(f"  {name:20s} invariance {s['invariance'][0]}/{s['invariance'][1]}  detection {s['detection'][0]}/{s['detection'][1]}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
