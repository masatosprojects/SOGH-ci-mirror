"""Meaning-flip sweep (Issue #9): put a known qualitative error into a real article, one place at a time,
and count how many the QA catches.

The mutation sweep edits numbers; this one edits *meaning* that has no number: a yes/no turned over,
"any of" turned into "all of", a "not allowed" turned into "allowed", a "場合がある" hedge dropped, a
limit ("〜に限り") dropped, an item of a list left out. The catalog below is the set of KNOWN
rewordings — it is not a claim that every possible wording is covered, and the survivors are printed.

    python -m src.article_qa.flip_sweep <articles.json> [--json-out out.json] [--reference-date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.article_qa.evaluate import evaluate_article

# (id, family, regex, replacement, what it simulates)
FLIPS: list[tuple[str, str, str, str, str]] = [
    ("need_none_to_need", "polarity", "必要としない", "必要とする", "「必要としない」→「必要とする」"),
    ("need_none_to_needed", "polarity", "必要ありません", "必要です", "「必要ありません」→「必要です」"),
    ("unneeded_to_required", "polarity", "不要", "必須", "「不要」→「必須」"),
    ("exempt_to_required", "polarity", "免除", "必須", "「免除」→「必須」"),
    ("test_required_to_unneeded", "polarity", "受験が必要", "受験は不要", "「受験が必要」→「受験は不要」"),
    ("needed_to_unneeded", "polarity", "必要です", "不要です", "「必要です」→「不要です」"),
    ("allowed_to_not_allowed", "polarity", "認められています", "認められていません", "「認められています」→「認められていません」"),
    ("allowed_to_prohibited", "polarity", "認められています", "禁止されています", "「認められています」→「禁止されています」"),
    ("any_to_all", "logic", "いずれか", "すべて", "「いずれか」→「すべて」（OR→AND）"),
    ("any_to_both", "logic", "いずれか", "両方", "「いずれか」→「両方」"),
    ("applicable_to_all_met", "logic", "のいずれかに該当する", "をすべて満たす", "「のいずれかに該当」→「をすべて満たす」"),
    ("all_met_to_any", "logic", "全て満たす", "いずれか満たせば足りる", "「全て満たす」→「いずれか満たせば足りる」"),
    ("visit_no_to_yes", "exception", "持参はできません", "持参できます", "「持参はできません」→「持参できます」"),
    ("visit_not_accepted_to_accepted", "exception", "持参は受け付けません", "持参も受け付けます", "「持参は受け付けません」→「持参も受け付けます」"),
    ("extension_may_to_never", "exception", "延長する場合があるため", "延長しないため", "「延長する場合がある」→「延長しない」"),
    ("hedge_dropped_a", "hedge", "場合があります", "です", "「場合があります」の脱落"),
    ("hedge_dropped_b", "hedge", "場合もあります", "です", "「場合もあります」の脱落"),
    ("hedge_dropped_c", "hedge", "場合があるため", "ため", "「場合があるため」の脱落"),
    ("hedge_dropped_d", "hedge", "場合があると要項に記されています", "と要項に記されています", "「場合がある」の脱落（要項に記されています）"),
    ("limit_dropped_a", "limit", "に限り、", "、", "「〜に限り」の脱落"),
    ("exception_sentence_dropped", "limit", "ただし、[^。\n]*に限り[^。\n]*。(\\[EV-[A-Za-z0-9_-]+\\])?", "", "例外条件の文そのものの脱落"),
    ("caveat_needed_to_unneeded", "caveat", "別途必要です", "不要です", "注意書き「別途必要です」→「不要です」"),
    ("caveat_confirm_to_unneeded", "caveat", "別途確認が必要です", "確認は不要です", "注意書き「別途確認が必要です」→「確認は不要です」"),
    ("hedge_to_unconditional", "unconditional", "場合があります", "ことは例外なくありません", "「場合があります」→「例外なくありません」"),
    ("language_dropped_en", "omission", "日本語または英語", "日本語", "列挙の脱落：「日本語または英語」→「日本語」"),
    ("language_dropped_fr", "omission", "ドイツ語またはフランス語", "ドイツ語", "列挙の脱落：「ドイツ語またはフランス語」→「ドイツ語」"),
]
# Held-out wordings: NOT used while the registry rules were written or tuned. They measure whether the rules
# generalise to other ways of saying the same wrong thing — expect this number to be lower than FLIPS.
FLIPS_HELD_OUT: list[tuple[str, str, str, str, str]] = [
    ("h_need_none_to_demanded", "polarity", "必要としない", "求められる", "「必要としない」→「求められる」"),
    ("h_unneeded_to_demanded", "polarity", "不要", "求められます", "「不要」→「求められます」"),
    ("h_exempt_to_imposed", "polarity", "免除", "課されます", "「免除」→「課されます」"),
    ("h_allowed_to_not_permitted", "polarity", "認められています", "許されていません", "「認められています」→「許されていません」"),
    ("h_needed_to_not_demanded", "polarity", "必要です", "求められません", "「必要です」→「求められません」"),
    ("h_visit_no_to_possible", "exception", "持参はできません", "持参が可能です", "「持参はできません」→「持参が可能です」"),
    ("h_visit_not_accepted_to_possible", "exception", "持参は受け付けません", "持参も可能です", "「持参は受け付けません」→「持参も可能です」"),
    ("h_extension_to_none", "exception", "延長する場合があるため", "延長はないため", "「延長する場合がある」→「延長はない」"),
    ("h_hedge_to_fact", "hedge", "場合があります", "ことになっています", "「場合があります」→「ことになっています」"),
    ("h_hedge_to_fact_b", "hedge", "場合もあります", "ことになっています", "「場合もあります」→「ことになっています」"),
    ("h_any_to_both", "logic", "いずれか", "ともに", "「いずれか」→「ともに」"),
    ("h_applicable_to_both", "logic", "のいずれかに該当する", "の両方に該当する", "「のいずれかに該当」→「の両方に該当」"),
    ("h_limit_to_general", "limit", "に限り、", "の場合には、", "「〜に限り」→「〜の場合には」（限定が一般化）"),
    ("h_caveat_flipped", "caveat", "別途必要です", "必要ありません", "注意書き「別途必要です」→「必要ありません」"),
]
# Held-out B: written BEFORE the rules were generalised with lexicons and never used to tune them. This is the
# figure to quote for "does it generalise": other ways of saying the same wrong thing.
FLIPS_HELD_OUT_B: list[tuple[str, str, str, str, str]] = [
    ("b_need_none_to_required", "polarity", "必要としない", "必須とされる", "「必要としない」→「必須とされる」"),
    ("b_unneeded_to_indispensable", "polarity", "不要", "欠かせません", "「不要」→「欠かせません」"),
    ("b_exempt_to_obligatory", "polarity", "免除", "義務づけ", "「免除」→「義務づけ」"),
    ("b_allowed_to_not_possible", "polarity", "認められています", "不可とされています", "「認められています」→「不可とされています」"),
    ("b_needed_to_not_needed", "polarity", "必要です", "いりません", "「必要です」→「いりません」"),
    ("b_visit_no_to_fine", "exception", "持参はできません", "持参でも構いません", "「持参はできません」→「持参でも構いません」"),
    ("b_visit_not_accepted_to_accepted", "exception", "持参は受け付けません", "持参もお受けします", "「持参は受け付けません」→「持参もお受けします」"),
    ("b_extension_to_not_extended", "exception", "延長する場合があるため", "延長されないため", "「延長する場合がある」→「延長されない」"),
    ("b_hedge_to_decided", "hedge", "場合があります", "ことが決まっています", "「場合があります」→「ことが決まっています」"),
    ("b_hedge_to_planned", "hedge", "場合もあります", "予定です", "「場合もあります」→「予定です」"),
    ("b_any_to_whole", "logic", "いずれか", "全部", "「いずれか」→「全部」"),
    ("b_applicable_to_possessing_all", "logic", "のいずれかに該当する", "のすべてを備える", "「のいずれかに該当」→「のすべてを備える」"),
    ("b_all_met_to_one", "logic", "全て満たす", "どれか一つ満たす", "「全て満たす」→「どれか一つ満たす」"),
    ("b_limit_to_even", "limit", "に限り、", "でも、", "「〜に限り」→「〜でも」"),
    ("b_caveat_to_not_demanded", "caveat", "別途必要です", "必要とされていません", "注意書き「別途必要です」→「必要とされていません」"),
]
# Held-out C: written AFTER the final rules, with wordings none of the rules or lexicons were written from.
# Measured ONCE and not used to tune anything: the only clean estimate of how the checks generalise.
# (A was looked at while tuning; B was written by the same author as the lexicons and shares their vocabulary.)
FLIPS_HELD_OUT_C: list[tuple[str, str, str, str, str]] = [
    ("c_need_none_to_demanded", "polarity", "必要としない", "要求される", "「必要としない」→「要求される」"),
    ("c_unneeded_to_requisite", "polarity", "不要", "要件です", "「不要」→「要件です」"),
    ("c_exempt_to_applies", "polarity", "免除", "対象となります", "「免除」→「対象となります」"),
    ("c_allowed_to_withheld", "polarity", "認められています", "見送られています", "「認められています」→「見送られています」"),
    ("c_needed_to_optional", "polarity", "必要です", "任意です", "「必要です」→「任意です」"),
    ("c_visit_no_to_welcome", "exception", "持参はできません", "持参も歓迎します", "「持参はできません」→「持参も歓迎します」"),
    ("c_visit_not_accepted_to_counter", "exception", "持参は受け付けません", "窓口でも受け付けます", "「持参は受け付けません」→「窓口でも受け付けます」"),
    ("c_extension_to_fixed", "exception", "延長する場合があるため", "終了時刻は固定のため", "「延長する場合がある」→「終了時刻は固定」"),
    ("c_hedge_to_rule", "hedge", "場合があります", "と定められています", "「場合があります」→「と定められています」"),
    ("c_hedge_to_certain", "hedge", "場合もあります", "ものとします", "「場合もあります」→「ものとします」"),
    ("c_any_to_each", "logic", "いずれか", "それぞれ", "「いずれか」→「それぞれ」"),
    ("c_applicable_to_complete", "logic", "のいずれかに該当する", "を完全に満たす", "「のいずれかに該当」→「を完全に満たす」"),
    ("c_limit_to_any", "limit", "に限り、", "であれば、", "「〜に限り」→「〜であれば」"),
    ("c_caveat_to_done", "caveat", "別途必要です", "済んでいます", "注意書き「別途必要です」→「済んでいます」"),
]
_SKIP = "## 根拠資料"


def flip_sweep_article(article: dict[str, Any], evidence: dict[str, Any], catalog=None, **qa: Any) -> dict[str, Any]:
    text = article["text"]
    end = text.find(_SKIP)
    end = len(text) if end == -1 else end
    baseline = evaluate_article(article["article_id"], text, article["claim"], evidence, **qa)
    rows = []
    for flip_id, family, pattern, replacement, what in (FLIPS if catalog is None else catalog):
        for m in re.finditer(pattern, text[:end]):
            mutated = text[:m.start()] + replacement + text[m.end():]
            report = evaluate_article(article["article_id"], mutated, article["claim"], evidence, **qa)
            # An undetected flip is not a SILENT miss when the report lists that very sentence as unverified
            # ("this wording is not machine-checked"): a person is told to look. Both numbers are reported.
            window = text[max(0, m.start() - 80): m.end() + 80]
            declared = (not report.findings) and any(u.get("snippet") and u["snippet"] in window
                                                     for u in baseline.coverage.get("unverified", []))
            rows.append({"flip": flip_id, "family": family, "what": what, "detected": bool(report.findings),
                         "declared_unverified": declared,
                         "categories": sorted({f["category"] for f in report.findings}),
                         "context": text[max(0, m.start() - 16): m.end() + 12].replace("\n", " ")})
    return {"article_id": article["article_id"], "baseline_ok": baseline.ok, "rows": rows}


def flip_sweep(data: dict[str, Any], catalog=None, **qa: Any) -> dict[str, Any]:
    """`catalog` defaults to FLIPS; pass FLIPS_HELD_OUT for the generalisation measurement."""
    per_article = [flip_sweep_article(a, data["evidence"], catalog=catalog, **qa) for a in data["articles"]]
    rows = [dict(r, article=a["article_id"][-24:]) for a in per_article for r in a["rows"]]
    by_family: dict[str, dict[str, int]] = {}
    by_flip: dict[str, dict[str, int]] = {}
    for r in rows:
        for table, key in ((by_family, r["family"]), (by_flip, r["flip"])):
            cell = table.setdefault(key, {"instances": 0, "detected": 0})
            cell["instances"] += 1
            cell["detected"] += r["detected"]
    detected = sum(r["detected"] for r in rows)
    declared = sum(r["declared_unverified"] for r in rows)
    return {"instances": len(rows), "detected": detected, "survived": len(rows) - detected,
            "declared_unverified": declared, "silent_misses": len(rows) - detected - declared,
            "accounted_rate": round((detected + declared) / len(rows), 4) if rows else None,
            "detection_rate": round(detected / len(rows), 4) if rows else None,
            "all_baselines_ok": all(a["baseline_ok"] for a in per_article),
            "by_family": by_family, "by_flip": by_flip,
            "survivors": [{k: r[k] for k in ("article", "flip", "context", "declared_unverified")} for r in rows if not r["detected"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("articles_json", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--reference-date", default=None)
    parser.add_argument("--require-as-of", action="store_true")
    args = parser.parse_args(argv)
    result = flip_sweep(json.loads(args.articles_json.read_text(encoding="utf-8")),
                        reference_date=args.reference_date, require_as_of=args.require_as_of)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
