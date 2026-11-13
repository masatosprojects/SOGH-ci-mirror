"""M1 stage 1 (docs/architecture/M1_SAFE_MIGRATION_PLAN.md): the patch that adapts Work's update path to the approved guard design is a PROPOSAL.
SELF_VALIDATED / WORK_REVIEW_PENDING. It lives in patches/m1-stage1/ and is applied here only to a COPY of the delivered pipeline in a temporary directory:
research/inbox/ (Work's delivered, manifest-checked files) is never written.

What is proven: the patch applies cleanly; Work's own 93 tests pass on the patched copy exactly as on the delivered copy; the repository's database tests pass against the
patched pipeline; the update path works under the final guard rules when patched and is refused by them when not (tests/behaviour_work_stage1.py).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DELIVERED = REPO / "research" / "inbox" / "work-faq-v3" / "pipeline"
PATCH = REPO / "patches" / "m1-stage1" / "work-pipeline-stage1.patch"
CHANGED = {"admissions_pipeline/generic.py", "admissions_pipeline/revisions.py", "admissions_pipeline/store.py"}


def tree_hash(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def copy_pipeline(dest: Path) -> Path:
    shutil.copytree(DELIVERED, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


def git_apply(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.autocrlf=false", "apply", *flags, str(PATCH)], cwd=root, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    base = tmp_path_factory.mktemp("stage1")
    before = tree_hash(DELIVERED)
    delivered = copy_pipeline(base / "delivered")
    patched = copy_pipeline(base / "patched")
    done = git_apply(patched)
    assert done.returncode == 0, done.stderr
    yield delivered, patched, before
    assert tree_hash(DELIVERED) == before  # Work's directory is byte-for-byte what it was


def run_pytest(args, cwd, env_extra=None):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", **(env_extra or {})}
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900)


def test_the_patch_touches_exactly_the_three_declared_files_and_nothing_else(copies):
    delivered, patched, _ = copies
    a, b = tree_hash(delivered), tree_hash(patched)
    assert {k for k in a if a[k] != b.get(k)} == CHANGED and set(a) == set(b)


def test_the_patch_does_not_apply_twice_and_a_reverse_check_works(copies):
    delivered, patched, _ = copies
    assert git_apply(patched, "--check").returncode != 0  # already applied
    assert git_apply(patched, "--check", "-R").returncode == 0  # and it is exactly reversible
    assert git_apply(delivered, "--check").returncode == 0


def test_the_patch_adds_the_four_declared_changes_and_no_other_behaviour(copies):
    text = PATCH.read_text(encoding="utf-8")
    added = [ln[1:] for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in text.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    assert any("create_function(\"sogh_write_ok\"" in ln for ln in added) and any("recursive_triggers=ON" in ln for ln in added)
    assert any("def _record_reason" in ln for ln in added) and any("reason=None" in ln for ln in added)
    # the approval statement moves; it is not rewritten
    assert [ln.strip() for ln in removed if "UPDATE update_batches SET state='approved'" in ln] == [ln.strip() for ln in added if "UPDATE update_batches SET state='approved'" in ln]
    assert len(added) <= 40 and len(removed) <= 6


def test_work_s_own_tests_pass_on_the_delivered_and_on_the_patched_copy(copies):
    delivered, patched, _ = copies
    for root in (delivered, patched):
        # Work's pipeline now imports src.db_contract.historical_read (PR #207): the copies live outside the repository, so the repository root must be importable.
        r = run_pytest(["tests"], root, {"PYTHONPATH": str(REPO)})
        assert r.returncode == 0, root.name + "\n" + r.stdout[-1500:] + r.stderr[-500:]
        assert "93 passed" in r.stdout, r.stdout[-300:]


def test_the_repository_database_tests_pass_against_the_patched_pipeline(copies):
    _, patched, _ = copies
    files = ["tests/test_additive_schema.py", "tests/test_g09_and_runner.py", "tests/test_unified_design_falsification.py", "tests/test_db_acceptance_g1_g2.py"]
    files = [f for f in files if (REPO / f).exists()] + sorted(p.relative_to(REPO).as_posix() for p in (REPO / "tests").glob("test_db_acceptance*.py"))
    r = run_pytest(sorted(set(files)), REPO, {"SOGH_PIPELINE_ROOT": str(patched)})
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-500:]


@pytest.mark.parametrize("mode", ["patched", "unpatched"])
def test_the_update_path_under_the_final_guard_rules(copies, mode):
    delivered, patched, _ = copies
    root = patched if mode == "patched" else delivered
    r = run_pytest(["tests/behaviour_work_stage1.py"], REPO, {"SOGH_PIPELINE_ROOT": str(root), "SOGH_STAGE1_MODE": mode})
    assert r.returncode == 0, r.stdout[-3500:] + r.stderr[-500:]
    passed = int(re.search(r"(\d+) passed", r.stdout).group(1))
    assert "failed" not in r.stdout and passed >= (10 if mode == "patched" else 4), r.stdout[-800:]  # a skipped or silently empty run is not a pass
