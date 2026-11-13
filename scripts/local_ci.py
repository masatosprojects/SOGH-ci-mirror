"""Run the repository's CI steps on this computer, in a clean checkout, at no cost.

Why: GitHub Actions can be unavailable (the free minutes of a private repository are used up and no spending is wanted). A pull request is then checked here, with the SAME commands as
.github/workflows/tests.yml, so that merging does not depend on the paid minutes. This is NOT a green CI: it covers only the operating system and the Python version it runs on, and the
summary says so. Use it again with another interpreter (`--python <path to 3.11>`) or on another system (a Linux machine, WSL, a container) to cover that environment.

What it does: (1) makes a throw-away checkout of a git ref in a temporary directory (nothing is read from your working tree: no untracked file can help a test pass), optionally merging more
branches into it; (2) hides the optional dependencies (pymupdf / fitz) the way a clean CI machine does; (3) runs `pytest tests/ -q -rs` with a junit file, the regression report with
`--fail-on-skip` (a skip is not a pass), the whole-view check and Work's whole-view CLI, as the workflow does; (4) prints a summary and exits non-zero on any failure.

    python scripts/local_ci.py                       # the current HEAD
    python scripts/local_ci.py --ref origin/master --merge origin/claude/topic-a --merge origin/claude/topic-b
    python scripts/local_ci.py --python C:\\Python311\\python.exe
Standard library only; it never touches the network, the real databases or the working tree.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BLOCK = textwrap.dedent('''\
    import sys
    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("fitz", "pymupdf"):
                raise ImportError("hidden to mimic a CI machine without optional dependencies: " + name)
    sys.meta_path.insert(0, _Block())
''')


# A checkout on a removable exFAT drive (the O: drive) is "owned by someone else" for git. The setting is given to THIS process's git calls only (environment variables), never written to a git config file.
GIT_ENV = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0="*")


def run(cmd, cwd, env, label):
    done = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-6:])
    return {"step": label, "exit": done.returncode, "tail": tail}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ref", default="HEAD", help="git ref to check out (default HEAD)")
    p.add_argument("--merge", action="append", default=[], help="a branch to merge into the checkout before testing (repeatable)")
    p.add_argument("--python", default=sys.executable, help="interpreter to run the steps with (default: this one)")
    p.add_argument("--keep", action="store_true", help="keep the temporary checkout")
    p.add_argument("--json", type=Path, help="also write the summary as JSON here")
    a = p.parse_args()
    root = Path(tempfile.mkdtemp(prefix="sogh-local-ci-"))
    checkout = root / "checkout"
    results: list[dict] = []
    try:
        subprocess.run(["git", "worktree", "add", "--detach", str(checkout), a.ref], cwd=REPO, check=True, capture_output=True, text=True, env=GIT_ENV)
        for branch in a.merge:
            merged = subprocess.run(["git", "-c", "user.name=local-ci", "-c", "user.email=local-ci@invalid", "merge", "--no-edit", branch], cwd=checkout, capture_output=True, text=True, env=GIT_ENV)
            results.append({"step": f"merge {branch}", "exit": merged.returncode, "tail": (merged.stdout + merged.stderr).strip().splitlines()[-1] if merged.stdout + merged.stderr else ""})
            if merged.returncode:
                break
        if all(r["exit"] == 0 for r in results):
            hide = root / "hide"
            hide.mkdir()
            (hide / "sitecustomize.py").write_text(BLOCK, encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(hide), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            py = a.python
            junit = checkout / "junit.xml"
            results.append(run([py, "-m", "pytest", "tests/", "-q", "-rs", "-p", "no:cacheprovider", f"--junitxml={junit}"], checkout, env, "pytest tests/ (jobs: pytest / pytest-py311 / pytest-windows)"))
            if junit.exists():
                results.append(run([py, "-m", "src.regression.report", "--junit", str(junit), "--fail-on-skip", "--out-dir", "regression-report"], checkout, env, "regression report --fail-on-skip"))
            results.append(run([py, "-m", "src.regression.fullview", "--inbox", "research/inbox", "--scope", "export", "--execution-origin", "github-ci", "--out-dir", "regression-report"], checkout, env, "whole view (scope=export)"))
            work_cli = checkout / "research/inbox/work-updates-v2/pipeline/scripts/verify_full_view.py"
            if work_cli.exists():
                results.append(run([py, str(work_cli), "--view", "research/inbox/work-updates-v2/samples/current/active-state.json", "--qa-root", ".", "--reference-date", "2026-11-01", "--scope", "export",
                                    "--execution-origin", "github-ci", "--prior-inbox", "research/inbox", "--output", "work-full-view-ci"], checkout, env, "Work whole-view CLI"))
    finally:
        if not a.keep:
            subprocess.run(["git", "worktree", "remove", "--force", str(checkout)], cwd=REPO, capture_output=True, text=True, env=GIT_ENV)
            shutil.rmtree(root, ignore_errors=True)
    version = subprocess.run([a.python, "-c", "import platform;print(platform.python_version())"], capture_output=True, text=True).stdout.strip()
    ok = bool(results) and all(r["exit"] == 0 for r in results)
    system = platform.system()
    covered = {"Windows": "pytest-windows (Windows)", "Linux": "pytest (Linux)", "Darwin": "none of the three CI jobs (macOS)"}.get(system, system)
    py_job = {"3.11": "pytest-py311", "3.12": "pytest / pytest-windows"}.get(".".join(version.split(".")[:2]), "no CI job (another Python version)")
    summary = {"ok": ok, "system": system, "python": version, "covers_ci_jobs": f"{covered}; Python job: {py_job}",
               "not_covered": "every other operating system / Python version of the three CI jobs", "this_is_not_a_green_ci": True, "steps": results}
    if a.json:  # written first: a console that cannot show a character must not lose the result
        a.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
