"""Checks every delivered export must pass, whichever university it is about.

evaluate_export     one export: Phase E gate, fact_key registry, strict article QA,
                    mutation detection (edit every number: is it caught?), and the
                    versioning round trip (change a quoted number: are exactly its
                    facts and articles flagged?)
evaluate_isolation  all exports together: ids do not collide, each article's result
                    is the same when the other exports' evidence is present, and the
                    cross-corpus duplicate/template report (information, not failure)
golden_view/compare a compact, deterministic snapshot of the results, committed in
                    tests/golden/qa_baseline.json, so a new delivery cannot silently
                    change the verdict for an old one
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

from src.article_qa.checks import find_near_duplicates, find_overused_phrases
from src.article_qa.evaluate import evaluate_article
from src.article_qa.flip_sweep import FLIPS_HELD_OUT_C, flip_sweep
from src.article_qa.mutation_sweep import swap_sweep, sweep
from src.article_qa.notation_sweep import notation_sweep
from src.integration.validate_export import validate_records
from src.verify.as_of import extract_as_of
from src.verify.fact_registry import get_registry
from src.versioning import impact
from src.versioning.snapshot import snapshot_from_evidence, source_hash


@dataclasses.dataclass(frozen=True)
class Thresholds:
    body_detection_min: float = 0.95  # numbers in the article body: edit +1, must be caught
    citation_id_detection_min: float = 0.90  # citation ids: edit one digit, must be caught
    citation_swap_detection_min: float = 0.98  # every citation replaced by every other real evidence id of the delivery
    notation_detection_min: float = 0.98  # a date moved by a day, written in another notation (R8.11.3, 十一月三日 ...)
    flip_detection_min: float = 0.95  # known meaning flips (yes/no, any/all, dropped limits ...) put into the real drafts
    as_of_detection_min: float = 1.0  # the as-of date, edited +1: always later than the delivery's own date (Issue #11)


# ------------------------------------------------------------- versioning

def _editions(export: dict[str, Any], mutate=None):
    snaps = []
    for sha in sorted({h for h in (source_hash(e) for e in export["evidence"].values()) if h}):
        s = snapshot_from_evidence(export["evidence"], sha, sha[:8], "2026-11-01")
        if mutate:
            s.pages = mutate(s, sha)
        snaps.append(s)
    return snaps


def check_versioning(export: dict[str, Any]) -> tuple[int, list[str]]:
    """The version-impact round trip on this export's own quotes. Returns (facts checked, failures)."""
    failures: list[str] = []
    evidence, articles = export["evidence"], export["articles"]
    base = impact.assess_export(export, _editions(export))
    if base["summary"]["evidence_intact"] != len(evidence) or any(a["status"] != "ok" for a in base["articles"].values()):
        failures.append("versioning: an unchanged edition is not 'all intact / all articles ok'")
    for eid, ev in evidence.items():
        proof = ev["proofs"][0]
        if re.search(r"\d", proof["quote"]):
            replacement, want = re.sub(r"\d+", lambda m: str(int(m.group()) + 1), proof["quote"], count=1), {"value_change"}
        else:
            replacement, want = "（この部分は改訂により削除されました）", {"missing", "reworded"}

        def mutate(snapshot, sha, ev=ev, proof=proof, replacement=replacement):
            pages = list(snapshot.pages)
            if sha == source_hash(ev):
                pages[proof["page"] - 1] = pages[proof["page"] - 1].replace(proof["quote"], replacement)
            return pages

        report = impact.assess_export(export, _editions(export, mutate))
        if report["evidence"][eid]["status"] not in want:
            failures.append(f"versioning: changing the quote of {eid} gave {report['evidence'][eid]['status']}, expected one of {sorted(want)}")
        changed = {k for k, v in report["evidence"].items() if v["status"] != "intact"}
        for article in articles:
            expect = "republish_required" if any(f"[{k}]" in article["text"] for k in changed) else "ok"
            got = report["articles"][article["article_id"]]["status"]
            if got != expect:
                failures.append(f"versioning: changing {eid}: article {article['article_id'][-24:]} is {got}, expected {expect}")
    return len(evidence), failures


# ----------------------------------------------------------------- one export

def delivery_reference_date(export: dict[str, Any]):
    """What "now" is for this delivery: the latest as-of date among its own drafts. Fixed by the data
    (no clock), so the result is the same on any day; a draft dated later than the delivery is wrong."""
    dates = [d for a in export["articles"] for d in extract_as_of(a["text"])[0]]
    return max(dates) if dates else None


def evaluate_export(key: str, export: dict[str, Any], thresholds: Thresholds = Thresholds()) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    evidence, articles = export["evidence"], export["articles"]
    if not evidence or not articles:
        failures.append("export has no evidence or no articles")

    gate = validate_records(evidence)
    if gate["invalid_count"]:
        bad = [k for k, r in gate["records"].items() if not r["ok"]]
        failures.append(f"gate: {gate['invalid_count']} invalid record(s): {bad[:5]}")

    registry = get_registry().check_evidence(evidence)
    if registry["unregistered_fact_keys"]:
        failures.append(f"registry: unregistered fact_key(s) {registry['unregistered_fact_keys']}")
    if registry["by_severity"]["error"]:
        failures.append(f"registry: {registry['by_severity']['error']} error(s)")
    if registry["by_severity"]["warning"]:
        warnings.append(f"registry: {registry['by_severity']['warning']} warning(s): "
                        f"{sorted({i['category'] for i in registry['issues'] if i['severity'] == 'warning'})}")

    reference = delivery_reference_date(export)
    per_article = {}
    coverage = {"evidence_with_checks": 0, "unverified": 0}
    for a in articles:
        r = evaluate_article(a["article_id"], a["text"], a["claim"], evidence, reference_date=reference, require_as_of=True)
        per_article[a["article_id"]] = {"ok": r.ok, "findings": sorted({f["category"] for f in r.findings}),
                                        "notices": sorted({n["category"] for n in r.notices})}
        for k in coverage:
            coverage[k] += r.coverage["counts"][k]
        if not r.ok:
            failures.append(f"article {a['article_id'][-28:]}: {sorted({f['category'] for f in r.findings})}")
        if r.notices:
            warnings.append(f"article {a['article_id'][-28:]}: notices {sorted({n['category'] for n in r.notices})}")

    result = sweep(export, reference_date=reference, require_as_of=True)
    body = result["by_class"].get("body", {"mutations": 0, "detected": 0})
    cid = result["by_class"].get("citation_id", {"mutations": 0, "detected": 0})
    rate = lambda s: (s["detected"] / s["mutations"]) if s["mutations"] else 1.0  # noqa: E731
    if rate(body) < thresholds.body_detection_min:
        failures.append(f"mutation: body numbers detected {body['detected']}/{body['mutations']} < {thresholds.body_detection_min:.0%}")
    if rate(cid) < thresholds.citation_id_detection_min:
        failures.append(f"mutation: citation ids detected {cid['detected']}/{cid['mutations']} < {thresholds.citation_id_detection_min:.0%}")
    asof = result["by_class"].get("as_of_date", {"mutations": 0, "detected": 0})
    if asof["mutations"] and rate(asof) < thresholds.as_of_detection_min:
        failures.append(f"mutation: as-of date edits detected {asof['detected']}/{asof['mutations']} < {thresholds.as_of_detection_min:.0%}")

    swaps = swap_sweep(export, reference_date=reference, require_as_of=True)
    if swaps["swaps"] and swaps["detection_rate"] < thresholds.citation_swap_detection_min:
        failures.append(f"mutation: citation swaps detected {swaps['detected']}/{swaps['swaps']} < {thresholds.citation_swap_detection_min:.0%}")
    elif swaps["survived"]:
        warnings.append(f"citation swaps not distinguishable by wording: {swaps['survived']} of {swaps['swaps']} "
                        f"({sorted({(s['from'] + '->' + s['to']) for s in swaps['survivors']})[:4]})")

    notation = notation_sweep(export, reference_date=reference, require_as_of=True)
    if notation["invariance"][0] != notation["invariance"][1]:
        failures.append(f"a right date written in another notation was rejected: {notation['invariance'][0]}/{notation['invariance'][1]} "
                        f"{[(f['notation'], f['written']) for f in notation['false_positives'][:3]]}")
    if notation["detection"][1] and notation["detection"][0] / notation["detection"][1] < thresholds.notation_detection_min:
        failures.append(f"moved dates in other notations detected {notation['detection'][0]}/{notation['detection'][1]} < {thresholds.notation_detection_min:.0%}")
    flips = flip_sweep(export, reference_date=reference, require_as_of=True)
    flips_c = flip_sweep(export, catalog=FLIPS_HELD_OUT_C, reference_date=reference, require_as_of=True)
    # The gate is on SILENT misses: a flip neither detected nor listed as "unverified" in the report. The raw
    # detection rate and the declared-unverified count are reported next to it, never hidden.
    if flips["instances"] and flips["accounted_rate"] < thresholds.flip_detection_min:
        failures.append(f"meaning flips neither detected nor reported unverified: {flips['silent_misses']} of {flips['instances']} "
                        f"(detected {flips['detected']}, declared unverified {flips['declared_unverified']}) < {thresholds.flip_detection_min:.0%}")
    if flips["declared_unverified"]:
        warnings.append(f"meaning flips not detected but reported unverified: {flips['declared_unverified']} of {flips['instances']} "
                        f"(detected {flips['detected']}/{flips['instances']})")
    if flips_c["survived"]:
        warnings.append(f"meaning flips in wordings the rules were never written from: {flips_c['survived']} of {flips_c['instances']} not detected (held-out C)")

    facts, version_failures = check_versioning(export)
    failures += version_failures

    return {
        "key": key, "records": len(evidence), "articles": len(articles), "fact_keys": registry["fact_keys_used"],
        "gate": {"ok": gate["ok_count"], "invalid": gate["invalid_count"]},
        "registry": {"version": registry["registry_version"], "by_severity": registry["by_severity"]},
        "per_article": per_article,
        "mutation": {"body": [body["detected"], body["mutations"]], "citation_id": [cid["detected"], cid["mutations"]],
                     "as_of": [asof["detected"], asof["mutations"]], "flip": [flips["detected"], flips["instances"]], "flip_declared_unverified": flips["declared_unverified"],
                     "notation_invariance": notation["invariance"], "notation_detection": notation["detection"],
                     "flip_held_out": [flips_c["detected"], flips_c["instances"]], "swap": [swaps["detected"], swaps["swaps"]], "overall": [result["detected"], result["mutations"]]},
        "versioning": {"facts_checked": facts}, "semantic_coverage": coverage,
        "failures": failures, "warnings": warnings, "ok": not failures,
    }


# --------------------------------------------------------- all exports together

def evaluate_isolation(exports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """`exports` maps key -> export. A new delivery must not change an old one's results."""
    failures: list[str] = []
    warnings: list[str] = []
    merged: dict[str, Any] = {}
    texts: dict[str, str] = {}
    for key, export in exports.items():
        clash = sorted(set(merged) & set(export["evidence"]))
        if clash:
            failures.append(f"{key}: evidence id(s) already used by another export: {clash[:5]}")
        merged.update(export["evidence"])
        for a in export["articles"]:
            if a["article_id"] in texts:
                failures.append(f"{key}: article id {a['article_id']} is already used by another export")
            texts[a["article_id"]] = a["text"]
    differing = []
    for key, export in exports.items():
        for a in export["articles"]:
            alone = evaluate_article(a["article_id"], a["text"], a["claim"], export["evidence"])
            together = evaluate_article(a["article_id"], a["text"], a["claim"], merged)
            if (alone.ok, alone.findings, alone.notices) != (together.ok, together.findings, together.notices):
                differing.append(a["article_id"])
    if differing:
        failures.append(f"an article's result changes when other exports' evidence is present: {differing[:5]}")
    near = find_near_duplicates(texts)
    template = find_overused_phrases(texts)
    if near:
        warnings.append(f"{len(near)} near-duplicate draft pair(s) across exports: " + "; ".join(f.detail for f in near[:3]))
    return {"exports": len(exports), "evidence": len(merged), "articles": len(texts),
            "near_duplicates": [f.detail for f in near], "template_phrases": len(template),
            "failures": failures, "warnings": warnings, "ok": not failures}


# ------------------------------------------------------------------- golden

def golden_view(result: dict[str, Any]) -> dict[str, Any]:
    """The part of a result that must not drift without a deliberate baseline update."""
    return {"records": result["records"], "articles": result["articles"], "fact_keys": result["fact_keys"],
            "gate": result["gate"], "registry_by_severity": result["registry"]["by_severity"],
            "per_article": result["per_article"], "mutation": result["mutation"],
            "versioning_facts": result["versioning"]["facts_checked"], "semantic_coverage": result["semantic_coverage"]}


def compare_to_baseline(key: str, current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Differences between a current golden view and the committed one ([] = unchanged)."""
    diffs = []
    for field in sorted(set(current) | set(baseline)):
        if current.get(field) != baseline.get(field):
            diffs.append(f"{key}: {field}: baseline {baseline.get(field)!r} -> now {current.get(field)!r}")
    return diffs
