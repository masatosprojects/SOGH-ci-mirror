"""One command that answers: "after this delivery, is everything still right?"

    python -m src.regression.report [--junit junit.xml | --run-tests] [--out-dir reports/regression]
                                    [--fail-on-skip] [--update-baseline]

It reports, for the whole repository:
  * test counts: total / passed / failed / errors / SKIPPED (with the names and reasons)
  * for every export Work delivered: gate, fact_key registry, article QA, mutation
    detection and the version-impact round trip
  * isolation: a new delivery must not change an old article's result
  * baseline: the committed golden results of the OLD exports must be unchanged;
    a new export without a baseline is flagged (not failed) until one is committed
  * the independent handoff audit for every handoff directory

Exit status 1 on any failure, any change to an old export's golden results, and —
with --fail-on-skip (CI uses it) — any skipped test. A skip is never a pass.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.integration import audit_handoff
from src.regression.checks import Thresholds, compare_to_baseline, evaluate_export, evaluate_isolation, golden_view
from src.regression.handoffs import INBOX, REPO_ROOT, find_exports, find_handoffs
from src.verify.fact_registry import get_registry

BASELINE_PATH = REPO_ROOT / "tests" / "golden" / "qa_baseline.json"
BASELINE_SCHEMA = 1


# ------------------------------------------------------------------- tests

def parse_junit(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = errors = skipped = 0
    skipped_tests, failed_tests = [], []
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        for case in suite.iter("testcase"):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            sk = case.find("skipped")
            if sk is not None:
                skipped_tests.append({"test": name, "reason": sk.get("message", "")})
            if case.find("failure") is not None or case.find("error") is not None:
                failed_tests.append(name)
    return {"total": total, "passed": total - failed - errors - skipped, "failed": failed, "errors": errors,
            "skipped": skipped, "skipped_tests": skipped_tests, "failed_tests": failed_tests}


def run_tests(junit_path: Path) -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", f"--junitxml={junit_path}"],
                          cwd=REPO_ROOT, env=env, capture_output=True).returncode


# ---------------------------------------------------------------- baseline

def load_baseline(path: Path = BASELINE_PATH) -> dict[str, Any]:
    if not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != BASELINE_SCHEMA:
        raise ValueError(f"unsupported baseline schema_version {data.get('schema_version')!r}")
    return data.get("exports", {})


def write_baseline(exports: dict[str, dict[str, Any]], path: Path = BASELINE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({
        "schema_version": BASELINE_SCHEMA,
        "note": "Golden QA results per delivered export. Regenerate ONLY on purpose: "
                "python -m src.regression.report --update-baseline, then review the git diff (docs/REGRESSION.md).",
        "exports": {k: exports[k] for k in sorted(exports)},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ report

def build_report(inbox: Path = INBOX, junit: Path | None = None, baseline_path: Path = BASELINE_PATH,
                 thresholds: Thresholds = Thresholds(), fail_on_skip: bool = False,
                 generated_at: str | None = None, run_audit: bool = True) -> dict[str, Any]:
    refs = find_exports(inbox)
    loaded = {ref.key: ref.load() for ref in refs}
    results = {key: evaluate_export(key, data, thresholds) for key, data in loaded.items()}
    isolation = evaluate_isolation(loaded)
    baseline = load_baseline(baseline_path)

    changed, unchanged, new = [], [], []
    for key, result in results.items():
        if key not in baseline:
            new.append(key)
            continue
        diffs = compare_to_baseline(key, golden_view(result), baseline[key])
        (changed if diffs else unchanged).append(diffs if diffs else key)
    missing = sorted(set(baseline) - set(results))

    audits = {}
    if run_audit:
        for handoff in find_handoffs(inbox):
            summary = audit_handoff.audit(handoff)["summary"]
            audits[handoff.name] = {"statuses": summary["statuses"], "failed": summary["failed"], "skipped": summary["skipped"],
                                    "needs_review": summary["needs_review"]}

    tests = parse_junit(junit) if junit else None
    reasons = []
    if not refs:
        reasons.append("no claude-compatible-export.json found under research/inbox")
    if tests:
        if tests["failed"] or tests["errors"]:
            reasons.append(f"{tests['failed']} failed / {tests['errors']} error test(s)")
        if fail_on_skip and tests["skipped"]:
            reasons.append(f"{tests['skipped']} skipped test(s) (a skip is not a pass)")
    reasons += [f"{k}: {'; '.join(r['failures'])}" for k, r in results.items() if not r["ok"]]
    reasons += [f"isolation: {f}" for f in isolation["failures"]]
    reasons += [d for diffs in changed for d in diffs]
    reasons += [f"baseline lists {k} but it is no longer delivered" for k in missing]
    reasons += [f"audit {h}: failed {a['failed']}" for h, a in audits.items() if a["failed"]]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    return {
        "generated_at": generated_at or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "commit": commit or None, "registry_version": get_registry().version,
        "tests": tests, "exports": results, "isolation": isolation, "audits": audits,
        "baseline": {"unchanged": unchanged, "changed": [d for diffs in changed for d in diffs], "new_without_baseline": new,
                     "baseline_not_delivered": missing},
        "verdict": {"ok": not reasons, "reasons": reasons},
    }


def render_markdown(report: dict[str, Any]) -> str:
    v = report["verdict"]
    lines = ["# 回帰テストの報告", "",
             f"- 判定: **{'成功' if v['ok'] else '失敗'}**", f"- 生成: {report['generated_at']}（commit {report['commit']}）",
             f"- fact_key 登録簿: {report['registry_version']}", ""]
    if not v["ok"]:
        lines += ["## 失敗の理由", ""] + [f"- {r}" for r in v["reasons"]] + [""]
    t = report["tests"]
    lines += ["## テスト件数", ""]
    if t:
        lines += ["| 合計 | 成功 | 失敗 | エラー | **skip** |", "|---|---|---|---|---|",
                  f"| {t['total']} | {t['passed']} | {t['failed']} | {t['errors']} | **{t['skipped']}** |", ""]
        if t["skipped_tests"]:
            lines += ["skip されたテスト（成功には数えない）:", ""] + [f"- `{s['test']}` — {s['reason']}" for s in t["skipped_tests"]] + [""]
        if t["failed_tests"]:
            lines += ["失敗したテスト:", ""] + [f"- `{n}`" for n in t["failed_tests"]] + [""]
    else:
        lines += ["（テスト結果が渡されていません：`--junit` か `--run-tests`）", ""]
    lines += ["## 受け渡しごとの検査", "",
              "| export | 事実 | 記事 | ゲート | 登録簿エラー/警告 | 変異検出（本文／引用ID／作業基準日／全体）・引用の総当たり差し替え・意味の反転（調整済み／独立C）・表記ゆれ（日付の別表記で誤検出なし／1日ずらして検出） | 意味の未検証 | 版管理 | 結果 |", "|---|---|---|---|---|---|---|---|---|"]
    for key, r in report["exports"].items():
        m = r["mutation"]
        lines.append(f"| `{key}` | {r['records']} | {r['articles']} | {r['gate']['ok']}/{r['records']} | "
                     f"{r['registry']['by_severity']['error']}/{r['registry']['by_severity']['warning']} | "
                     f"{m['body'][0]}/{m['body'][1]}・{m['citation_id'][0]}/{m['citation_id'][1]}・"
                     f"{m['as_of'][0]}/{m['as_of'][1]}・{m['overall'][0]}/{m['overall'][1]}・{m['swap'][0]}/{m['swap'][1]}・"
                     f"{m['flip'][0]}/{m['flip'][1]}／{m['flip_held_out'][0]}/{m['flip_held_out'][1]}・"
                     f"{m['notation_invariance'][0]}/{m['notation_invariance'][1]}／{m['notation_detection'][0]}/{m['notation_detection'][1]} | "
                     f"{r['semantic_coverage']['unverified']}件 | "
                     f"{r['versioning']['facts_checked']}事実 | {'✅' if r['ok'] else '❌'} |")
    warns = [f"- `{k}`: {w}" for k, r in report["exports"].items() for w in r["warnings"]]
    if warns:
        lines += ["", "警告（失敗ではない）:", ""] + warns
    iso = report["isolation"]
    lines += ["", "## 受け渡しをまたいだ検査", "",
              f"- 全体: {iso['exports']} export・{iso['evidence']} 事実・{iso['articles']} 記事。結果: **{'成功' if iso['ok'] else '失敗'}**"
              "（事実IDの衝突なし、他の受け渡しを混ぜても各記事の結果は不変）"]
    lines += [f"- 警告: {w}" for w in iso["warnings"]]
    b = report["baseline"]
    lines += ["", "## ベースライン（過去の結果が変わっていないか）", "",
              f"- 変更なし: {len(b['unchanged'])} 件　／　変更あり: **{len(b['changed'])}** 件　／　ベースライン未登録の新しい export: {len(b['new_without_baseline'])} 件"]
    lines += [f"  - 新しい export（要・ベースライン登録）: `{k}`" for k in b["new_without_baseline"]]
    lines += [f"  - ❌ {d}" for d in b["changed"]]
    lines += ["", "## 独立監査（`audit_handoff`、公式PDFなし）", "", "| 受け渡し | 失敗 | 要確認 | skip（検査できていない） |", "|---|---|---|---|"]
    for h, a in report["audits"].items():
        lines.append(f"| `{h}` | {', '.join(a['failed']) or '-'} | {', '.join(a['needs_review']) or '-'} | {', '.join(a['skipped']) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inbox", type=Path, default=INBOX, help="where the deliveries are (default research/inbox)")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH, help="golden results file")
    parser.add_argument("--junit", type=Path, default=None, help="junit xml of a pytest run")
    parser.add_argument("--run-tests", action="store_true", help="run the test suite now and use its result")
    parser.add_argument("--out-dir", type=Path, default=None, help="write report.json and report.md here")
    parser.add_argument("--fail-on-skip", action="store_true")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite tests/golden/qa_baseline.json from the current results")
    parser.add_argument("--github-summary", action="store_true", help="append the markdown to $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    junit = args.junit
    tmp = None
    if args.run_tests:
        tmp = tempfile.TemporaryDirectory()
        junit = Path(tmp.name) / "junit.xml"
        run_tests(junit)
    if args.update_baseline:
        results = {ref.key: golden_view(evaluate_export(ref.key, ref.load())) for ref in find_exports(args.inbox)}
        write_baseline(results, args.baseline)
        print(f"baseline written: {len(results)} export(s) -> {args.baseline.name}")
    report = build_report(inbox=args.inbox, junit=junit, baseline_path=args.baseline, fail_on_skip=args.fail_on_skip)
    markdown = render_markdown(report)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out_dir / "report.md").write_text(markdown, encoding="utf-8")
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(markdown)
    print(markdown)
    if tmp:
        tmp.cleanup()
    return 0 if report["verdict"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
