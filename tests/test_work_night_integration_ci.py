"""CI connection for Work's PR #93 deliverables (`research/inbox/work-night-integration/`), which the standard `pytest` run does not collect.

What it does, in one place and without touching Work's files:
1. builds the code-only isolation with Work's own `prepare_isolation.py` from the DELIVERED pipeline in the repository (`research/inbox/work-faq-v3/pipeline`; its four checked files match Work's
   preconditions), and requires the completion marker;
2. runs Work's own tests (`review_tests/`, SYNTHETIC) against that isolation in a separate pytest process and counts passed / failed / errors / skipped SEPARATELY from the junit file;
3. runs Claude's `finalize` abnormal-path tests (tests/test_finalize_abnormal_paths.py) against the same isolation, which also enables the `--reason-json` command-line tests.

What it does NOT do: it never touches a real database, an audit copy, a saved official document or the network. Work's local real-copy runs (g4 22/22, additive 20/20, the existing 247 tests, the F-2 / G-2 / G-6
runs) need inputs that are not in the repository and stay LOCAL; their results are NOT counted here and a pass of this file is not evidence for them. A skipped test is not a pass: the run fails on any skip.
Defined only when the directory exists (absent, not skipped, before PR #93 is merged). SYNTHETIC_ONLY; not an independent audit of Work's code.
"""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_NIGHT_DIR") or REPO / "research" / "inbox" / "work-night-integration")
DELIVERED = REPO / "research" / "inbox" / "work-faq-v3" / "pipeline"

if (WORK / "prepare_isolation.py").exists() and (WORK / "review_tests").is_dir() and DELIVERED.exists():
    ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

    def summary_of(junit: Path) -> dict:
        root = ET.parse(junit).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for s in suites:
            for k in total:
                total[k] += int(s.get(k, 0))
        total["passed"] = total["tests"] - total["failures"] - total["errors"] - total["skipped"]
        return total

    def report(title: str, counts: dict) -> None:
        line = f"{title}: passed={counts['passed']} failed={counts['failures']} errors={counts['errors']} skipped={counts['skipped']} (of {counts['tests']})"
        print(line)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"- {line}\n")

    @pytest.fixture(scope="module")
    def isolation(tmp_path_factory):
        base = tmp_path_factory.mktemp("work-night")
        source = base / "source"
        shutil.copytree(DELIVERED, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for sub in ("admissions_pipeline", "admission_ai", "scripts", "tests", "config"):  # the delivered folder has no admission_ai / config / tests
            (source / sub).mkdir(exist_ok=True)
        out = base / "isolation"
        done = subprocess.run([sys.executable, "-B", "-X", "utf8", str(WORK / "prepare_isolation.py"), "--source-root", str(source), "--output", str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV, timeout=300)
        assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
        status = (out / ".work-isolation-status.json").read_text(encoding="utf-8")
        assert '"state": "completed"' in status  # a failed or in-progress marker means the isolation must not be used
        return out

    def run_pytest(targets, isolation_path, junit, cwd=REPO):
        env = dict(ENV, SOGH_PIPELINE_ROOT=str(isolation_path), SOGH_REVIEW_QA_ROOT=str(REPO))
        done = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", *map(str, targets), "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd, timeout=900)
        return done, summary_of(junit)

    def test_works_own_synthetic_tests_pass_on_the_isolation_with_no_failure_error_or_skip(isolation, tmp_path):
        done, counts = run_pytest([WORK / "review_tests"], isolation, tmp_path / "work.xml")
        report("Work review_tests (synthetic, on the isolation)", counts)
        assert (counts["failures"], counts["errors"], counts["skipped"]) == (0, 0, 0), done.stdout[-1500:]
        assert counts["passed"] >= 31, counts  # 20 from the first submission + 11 for the review follow-up; a lower count means tests were lost

    def test_claudes_finalize_abnormal_path_tests_also_pass_on_works_isolation_including_the_cli_tests(isolation, tmp_path):
        done, counts = run_pytest([REPO / "tests" / "test_finalize_abnormal_paths.py"], isolation, tmp_path / "claude.xml")
        report("Claude finalize abnormal paths (on Work's isolation)", counts)
        assert (counts["failures"], counts["errors"], counts["skipped"]) == (0, 0, 0), done.stdout[-1500:]
        assert counts["passed"] >= 56, counts  # 42 common + the 14 --reason-json CLI tests that only exist when the flag is present

    def test_the_isolation_keeps_the_delivered_source_untouched(isolation):
        shas = {}
        for name in ("admissions_pipeline/store.py", "admissions_pipeline/revisions.py"):
            shas[name] = (DELIVERED / name).read_bytes()
        assert shas["admissions_pipeline/store.py"].count(b"configure_connection") == 0  # the delivered code is not patched; only the copy is
        assert b"configure_connection" in (isolation / "admissions_pipeline" / "store.py").read_bytes()
