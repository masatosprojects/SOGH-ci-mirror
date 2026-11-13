#!/usr/bin/env python3
"""
SOGH Antigravity - Real Model Physical Grounding Evaluation (Phase 3 Integration)

Executes physical local LLM inference (Qwen3-1.7B) under active Antigravity session
against Tsukuba Admission FAQ benchmark cases, then verifies grounding attribution
and fail-close safety.
"""

import os
import sys
import re
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List

# Setup sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import supervised_inference_runner as runner
from thermal_sensor_reader import ThermalSensorManager
from standalone_production_runner import AsyncCachedThermalManager
from tests.test_faq_grounding_eval import verify_faq_grounding_case
from scripts.grounding_response_parser import parse_grounding_verdict

LLAMA_EXE = Path(r"C:\Users\USER\llm_bench\cpu\llama-cli.exe")
MODEL_PATH = Path(r"C:\Users\USER\llm_bench\models\Qwen3-1.7B-Q4_K_M.gguf")
DEFAULT_DATASET = BASE_DIR / "fixtures" / "eval" / "tsukuba_admission_faq_comprehensive_cases.json"
HANDOFF_DIR = BASE_DIR / "handoff"


def clean_llama_output(stdout_text: str, prompt: str) -> str:
    """Extracts pure model response from llama-cli stdout stream."""
    if not stdout_text:
        return ""

    # Remove prompt echo if present
    lines = stdout_text.splitlines()
    clean_lines = []
    capture = False

    for line in lines:
        if "available commands:" in line or "build      :" in line or "Loading model" in line:
            continue
        if prompt.strip().splitlines()[-1] in line or line.startswith("> "):
            capture = True
            continue
        if capture:
            if line.strip() == "Exiting..." or line.startswith("[ Prompt:"):
                continue
            clean_lines.append(line)

    text = "\n".join(clean_lines).strip()
    # Strip thinking markers if present
    text = re.sub(r"\[Start thinking\].*?\[End thinking\]", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def run_real_model_grounding_evaluation(case_limit: int = 3) -> Dict[str, Any]:
    """Runs physical inference for benchmark cases and verifies grounding safety."""
    if not DEFAULT_DATASET.is_file():
        raise FileNotFoundError(f"Dataset not found: {DEFAULT_DATASET}")
    if not LLAMA_EXE.is_file():
        raise FileNotFoundError(f"Llama executable not found: {LLAMA_EXE}")
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

    with open(DEFAULT_DATASET, "r", encoding="utf-8") as f:
        benchmark = json.load(f)

    all_cases = benchmark.get("cases", [])
    cases_to_run = all_cases[:case_limit]

    # Preflight check
    ram = runner.get_ram_metrics()
    if ram["avail_mb"] < 1800.0:
        raise RuntimeError(f"Available RAM ({ram['avail_mb']:.1f} MB) < 1800 MB threshold.")

    # Initialize thermal manager
    raw_sensor = ThermalSensorManager()
    async_thermal = AsyncCachedThermalManager(raw_sensor)
    async_thermal.start()

    runner_instance = runner.SupervisedInferenceRunner()
    runner_instance.thermal_manager = async_thermal
    runner_instance.allow_user_authorized_acpi = True

    eval_results: List[Dict[str, Any]] = []

    print(f"Starting Physical Grounding Verification on Host CPU (Ryzen 5 3550H)...")
    print(f"Target cases: {len(cases_to_run)} / {len(all_cases)}")
    print(f"Available RAM: {ram['avail_mb']:.1f} MB")

    try:
        for idx, case in enumerate(cases_to_run, 1):
            case_id = case.get("case_id", f"CASE_{idx}")
            topic = case.get("topic", "")
            heading = case.get("faq_heading", "")
            verified_text = case.get("official_grounding_source", {}).get("verified_text", "")

            prompt = (
                f"あなたは筑波大学入試案内AIです。以下の公式FAQ情報のみに厳格に基づいて質問に簡潔に回答してください。\n"
                f"【公式情報】\n{verified_text if verified_text else '（公式情報なし）'}\n\n"
                f"【質問】\n{heading}\n\n"
                f"【回答】\n"
            )

            config = runner.SafeInferenceConfig(
                model_path=str(MODEL_PATH),
                llama_cli_path=str(LLAMA_EXE),
                prompt=prompt,
                threads=2,
                threads_batch=2,
                ctx_size=512,
                predict_tokens=64,
                temp=0.1,
                gpu_layers=0
            )

            start_t = time.time()
            res = runner_instance.execute_production_inference(config)
            dur = time.time() - start_t

            raw_stdout = res.get("stdout", "")
            generated_answer = clean_llama_output(raw_stdout, prompt)

            # Evaluate generated answer using grounding verification logic
            test_case_payload = dict(case)
            if generated_answer:
                test_case_payload["quoted_text"] = generated_answer

            grounding_verdict = verify_faq_grounding_case(test_case_payload)

            eval_results.append({
                "case_id": case_id,
                "topic": topic,
                "heading": heading,
                "success": res.get("success", False),
                "returncode": res.get("returncode"),
                "inference_time_sec": round(dur, 2),
                "generated_answer": generated_answer[:200] if generated_answer else "(empty)",
                "expected_verdict": case.get("expected_verdict"),
                "grounding_verdict": grounding_verdict.get("verdict"),
                "quarantined": grounding_verdict.get("quarantined"),
                "grounding_reason": grounding_verdict.get("reason")
            })

            print(f"[{idx}/{len(cases_to_run)}] {case_id}: inference {dur:.2f}s | verdict: {grounding_verdict.get('verdict')}")

    finally:
        async_thermal.stop()

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hardware": "AMD Ryzen 5 3550H / ASUS TUF Gaming FX505DY",
        "model": str(MODEL_PATH.name),
        "total_cases_evaluated": len(eval_results),
        "ram_avail_mb": ram["avail_mb"],
        "cases": eval_results
    }

    # Save reports
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    json_path = HANDOFF_DIR / "REAL_MODEL_GROUNDING_EVALUATION.json"
    md_path = HANDOFF_DIR / "REAL_MODEL_GROUNDING_EVALUATION.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    md_lines = [
        "# SOGH Antigravity: Real Model Physical Grounding Evaluation Report",
        "",
        f"- **Timestamp**: `{summary['timestamp']}`",
        f"- **Hardware**: `{summary['hardware']}`",
        f"- **Model**: `{summary['model']}`",
        f"- **Available RAM**: `{summary['ram_avail_mb']:.1f} MB`",
        f"- **Cases Evaluated**: `{summary['total_cases_evaluated']}`",
        "",
        "## Evaluated Cases",
        "",
        "| Case ID | Topic | Inference Time | Grounding Verdict | Quarantined | Safety Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for c in eval_results:
        safety_status = "SAFE_PASSED" if not c["quarantined"] else "QUARANTINED_BLOCKED"
        md_lines.append(f"| `{c['case_id']}` | {c['topic']} | {c['inference_time_sec']}s | `{c['grounding_verdict']}` | `{c['quarantined']}` | **{safety_status}** |")

    md_lines.append("\n## Detailed Responses and Citations\n")
    for c in eval_results:
        md_lines.append(f"### {c['case_id']}: {c['topic']}")
        md_lines.append(f"- **Heading**: {c['heading']}")
        md_lines.append(f"- **Generated Answer**: `{c['generated_answer']}`")
        md_lines.append(f"- **Verdict Reason**: {c['grounding_reason']}")
        md_lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"\nEvaluation complete. Reports saved to:")
    print(f"- JSON: {json_path}")
    print(f"- MD: {md_path}")
    return summary


def _hold_real_model_run():
    """USER HOLD (2026-11-07): real-model runs on this PC are stopped until the thermal findings F-S1/F-S2/F-S3 are fixed and the user lifts the hold by deleting the file."""
    hold = Path(__file__).resolve().parent.parent / "HOLD_REAL_MODEL_RUN.txt"
    if hold.exists():
        print("REAL-MODEL RUN IS ON HOLD by the user (see " + str(hold) + "). Nothing was started.")
        sys.exit(3)


def main():
    _hold_real_model_run()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate real model grounding on physical hardware.")
    parser.add_argument("--limit", type=int, default=3, help="Number of benchmark cases to evaluate (default: 3)")
    args = parser.parse_args()

    run_real_model_grounding_evaluation(case_limit=args.limit)


if __name__ == "__main__":
    main()
