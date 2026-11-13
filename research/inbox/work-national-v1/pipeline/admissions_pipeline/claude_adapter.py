"""Use the independently maintained Claude QA CLIs without changing that repo."""
import json
import os
import subprocess
import sys
from pathlib import Path


def run_qa(collab_root, export_path, snapshot_path, output_dir):
    root = Path(collab_root).resolve()
    if not (root / "src/run_qa_suite.py").is_file():
        raise FileNotFoundError("Claude QA repository not found")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    outputs = []
    for module, args, name in (
        ("src.integration.validate_export", [str(export_path)], "claude-export-validation.json"),
        ("src.run_qa_suite", ["--sqlite", str(snapshot_path), "--articles-json", str(export_path)], "claude-quality-report.json"),
    ):
        path = Path(output_dir) / name
        command = [sys.executable, "-X", "utf8", "-m", module, *args, "--json-out", str(path)]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        if not path.is_file():
            raise RuntimeError("Claude QA did not produce report: " + module)
        report = json.loads(path.read_text(encoding="utf-8"))
        outputs.append({"module": module, "exit_code": result.returncode, "report_path": str(path), "report": report})
    export_gate = outputs[0]["report"]
    quality = outputs[1]["report"]
    articles = quality.get("article_qa", {}).get("per_article", [])
    ok = (all(r["exit_code"] == 0 for r in outputs) and export_gate.get("total", 0) > 0 and
          export_gate.get("invalid_count") == 0 and bool(articles) and all(a["ok"] for a in articles) and
          not quality["article_qa"]["batch_findings"] and
          not any(i["severity"] == "error" for i in quality["db_qa"]["issues"]))
    return {"success": ok, "claude_repo": str(root), "claude_commit": commit, "calls": outputs,
            "note": "QA pass is not publication approval or full semantic verification."}
