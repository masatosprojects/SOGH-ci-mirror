#!/usr/bin/env python3
"""
SOGH Antigravity - Local Grounding Verification Evaluation CLI (Phase 3 / STR-068)

Executes zero-hallucination grounding verification against comprehensive Tsukuba FAQ benchmarks,
calculates precision/recall metrics, and generates auditable markdown/JSON reports.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List

# Add parent directory to path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tests.test_faq_grounding_eval import verify_faq_grounding_case
from scripts.grounding_response_parser import parse_grounding_verdict

DEFAULT_DATASET = BASE_DIR / "fixtures" / "eval" / "tsukuba_admission_faq_comprehensive_cases.json"


def evaluate_dataset(dataset_path: Path) -> Dict[str, Any]:
    """Runs grounding evaluation over all cases in the specified dataset."""
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Evaluation dataset not found at: {dataset_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    benchmark_version = data.get("benchmark_version", "unknown")
    cases = data.get("cases", [])

    results: List[Dict[str, Any]] = []
    correct_count = 0
    hallucination_count = 0
    fail_close_violations = 0

    category_counts: Dict[str, Dict[str, int]] = {}

    for case in cases:
        case_id = case.get("case_id", "UNKNOWN")
        expected_verdict = case.get("expected_verdict", "")
        sec_class = case.get("security_class", "")

        actual_res = verify_faq_grounding_case(case)
        actual_verdict = actual_res.get("verdict", "")
        quarantined = actual_res.get("quarantined", False)

        is_match = (actual_verdict == expected_verdict)
        if is_match:
            correct_count += 1
        else:
            if expected_verdict != "MATCH" and actual_verdict == "MATCH":
                hallucination_count += 1

        if expected_verdict in ["CONTRADICTION", "PROHIBITED_SUBSTITUTION", "UNVERIFIED_CITATION"]:
            if not quarantined:
                fail_close_violations += 1

        if sec_class not in category_counts:
            category_counts[sec_class] = {"total": 0, "correct": 0}
        category_counts[sec_class]["total"] += 1
        if is_match:
            category_counts[sec_class]["correct"] += 1

        results.append({
            "case_id": case_id,
            "topic": case.get("topic", case.get("faq_heading", "")),
            "expected": expected_verdict,
            "actual": actual_verdict,
            "quarantined": quarantined,
            "passed": is_match,
            "reason": actual_res.get("reason", "")
        })

    total_cases = len(cases)
    accuracy = (correct_count / total_cases * 100.0) if total_cases > 0 else 0.0
    hallucination_rate = (hallucination_count / total_cases * 100.0) if total_cases > 0 else 0.0

    return {
        "benchmark_version": benchmark_version,
        "dataset_path": str(dataset_path),
        "total_cases": total_cases,
        "correct_cases": correct_count,
        "accuracy_pct": accuracy,
        "hallucination_count": hallucination_count,
        "hallucination_rate_pct": hallucination_rate,
        "fail_close_violations": fail_close_violations,
        "category_metrics": category_counts,
        "all_passed": (correct_count == total_cases and hallucination_count == 0 and fail_close_violations == 0),
        "details": results
    }


def format_markdown_report(summary: Dict[str, Any]) -> str:
    """Formats evaluation results as GitHub-flavored Markdown."""
    lines = [
        f"# SOGH Antigravity: Grounding Verification Evaluation Report",
        f"",
        f"- **Benchmark Version**: `{summary['benchmark_version']}`",
        f"- **Dataset Path**: `{summary['dataset_path']}`",
        f"- **Total Test Cases**: {summary['total_cases']}",
        f"- **Passed Cases**: {summary['correct_cases']} / {summary['total_cases']} ({summary['accuracy_pct']:.1f}%)",
        f"- **Hallucination / False-Approval Rate**: **{summary['hallucination_rate_pct']:.2f}%** (Target: 0.00%)",
        f"- **Fail-Close Violations**: {summary['fail_close_violations']} (Target: 0)",
        f"- **Overall Status**: **{'PASSED_ALL_CHECKS' if summary['all_passed'] else 'FAILED_VIOLATIONS_DETECTED'}**",
        f"",
        f"## Security Class Breakdown",
        f"",
        f"| Security Class | Passed / Total | Accuracy |",
        f"|---|---|---|",
    ]

    for sc, stats in summary["category_metrics"].items():
        pct = (stats["correct"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
        lines.append(f"| `{sc}` | {stats['correct']} / {stats['total']} | {pct:.1f}% |")

    lines.extend([
        f"",
        f"## Detailed Case Results",
        f"",
        f"| Case ID | Topic | Expected | Actual | Quarantined | Result |",
        f"|---|---|---|---|:---:|:---:|",
    ])

    for d in summary["details"]:
        icon = "PASS" if d["passed"] else "FAIL"
        q_icon = "Yes" if d["quarantined"] else "No"
        lines.append(f"| `{d['case_id']}` | {d['topic']} | `{d['expected']}` | `{d['actual']}` | {q_icon} | **{icon}** |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate local LLM grounding verification benchmark.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to evaluation dataset JSON.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output report format.")
    parser.add_argument("--output", type=Path, default=None, help="File to write report to (default: stdout).")

    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    summary = evaluate_dataset(args.dataset)

    if args.format == "json":
        report = json.dumps(summary, indent=2, ensure_ascii=False)
    else:
        report = format_markdown_report(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to: {args.output}")
    else:
        print(report)

    if not summary["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
