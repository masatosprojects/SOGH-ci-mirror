"""Use the independently maintained Claude QA CLIs without changing that repo."""
import json
import os
import subprocess
import sys
from pathlib import Path


def qa_provenance(collab_root):
    root = Path(collab_root).resolve()
    if not (root / "src/run_qa_suite.py").is_file():
        raise FileNotFoundError("Claude QA repository not found")
    provenance = root / "QA_PROVENANCE.json"
    if provenance.exists():
        import hashlib
        metadata = json.loads(provenance.read_text(encoding="utf-8"))
        if {p.relative_to(root).as_posix() for p in root.rglob("*.py")} != {p for p in metadata["files"] if p.endswith(".py")}:
            raise ValueError("unlisted Python module in pinned QA archive")
        for relative, sha in metadata["files"].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError("pinned QA archive was modified")
        commit = metadata["commit"]
    else:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return root, commit


def run_qa(collab_root, export_path, snapshot_path, output_dir, reference_date=None):
    root, commit = qa_provenance(collab_root)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    outputs = []
    for module, args, name in (
        ("src.integration.validate_export", [str(export_path)], "claude-export-validation.json"),
        ("src.run_qa_suite", ["--sqlite", str(snapshot_path), "--articles-json", str(export_path)], "claude-quality-report.json"),
    ):
        path = Path(output_dir) / name
        command = [sys.executable, "-X", "utf8", "-m", module, *args, "--json-out", str(path)]
        if reference_date is not None and module == "src.run_qa_suite":
            command += ["--reference-date", reference_date.isoformat(), "--require-as-of"]
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


def run_quote_gate(collab_root,export_path,report_path):
    root,commit=qa_provenance(collab_root)
    code='import json,sys; from pathlib import Path; from src.integration.audit_handoff import check_values_in_quotes; r=check_values_in_quotes(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))); Path(sys.argv[2]).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); raise SystemExit(0 if r["status"]=="pass" else 1)'
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(Path(export_path).resolve()),str(Path(report_path).resolve())],cwd=root,capture_output=True,timeout=120)
    path=Path(report_path)
    return {'success':result.returncode==0 and path.is_file(),'qa_commit':commit,'report':json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None}
