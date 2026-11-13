"""M1.g2 second patch (patches/g2-faq/work-faq-g2-unconfirmed-section.patch): the article section for an official FAQ whose applicability is UNCONFIRMED. A PROPOSAL, SELF_TEST; wording adopted by the owner
(2026-11-08). Like test_g2_faq_patch.py it works only on COPIES of Work's delivered pipeline; research/inbox/ is never written.

Proven: the patch applies after work-faq-g2.patch (and after the stage-1 patch), is reversible and touches exactly one existing file and adds one; Work's own 93 tests pass with both patches; the behaviour file
(tests/behaviour_g2_unconfirmed.py) passes on the patched copy and cannot import on one without the second patch.
NOT proven (and said so in docs/G2_UNCONFIRMED_SECTION_2026-11-08.md): that the pipeline's STORE accepts evidence with no cycle - it does not today."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DELIVERED = REPO / "research" / "inbox" / "work-faq-v3" / "pipeline"
P1 = REPO / "patches" / "g2-faq" / "work-faq-g2.patch"
P2 = REPO / "patches" / "g2-faq" / "work-faq-g2-unconfirmed-section.patch"
STAGE1 = REPO / "patches" / "m1-stage1" / "work-pipeline-stage1.patch"
B1 = REPO / "tests" / "behaviour_g2_faq.py"
B2 = REPO / "tests" / "behaviour_g2_unconfirmed.py"
B3 = REPO / "tests" / "behaviour_g2_scope_evidence.py"


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def apply(root, patch, *flags):
    return subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", *flags, str(patch)], cwd=root, capture_output=True, text=True, encoding="utf-8")


def copy_pipeline(dest):
    shutil.copytree(DELIVERED, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    return dest


def run_pytest(args, cwd):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900)


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    base = tmp_path_factory.mktemp("g2p2")
    before = tree_hash(DELIVERED)
    one = copy_pipeline(base / "one")
    two = copy_pipeline(base / "two")
    assert apply(one, P1).returncode == 0
    assert apply(two, P1).returncode == 0
    done = apply(two, P2)
    assert done.returncode == 0, done.stderr
    yield one, two, before
    assert tree_hash(DELIVERED) == before


def test_the_second_patch_changes_exactly_these_files_and_adds_two(copies):
    """notice_articles.py (the section), faq_policy.py (extract_conditions needs the independent scope evidence: STR-101) and Work's fixture in tests/test_faq_policy.py (it now carries a controlled independent
    evidence: Work's 93 tests still pass); it adds unconfirmed_faq.py and scope_evidence.py."""
    one, two, _ = copies
    a, b = tree_hash(one), tree_hash(two)
    assert {k for k in a if a[k] != b.get(k)} == {"admissions_pipeline/notice_articles.py", "admissions_pipeline/faq_policy.py", "tests/test_faq_policy.py"}
    assert set(b) - set(a) == {"admissions_pipeline/unconfirmed_faq.py", "admissions_pipeline/scope_evidence.py"} and not set(a) - set(b)


def test_it_needs_the_first_patch_does_not_apply_twice_and_is_reversible(copies, tmp_path):
    one, two, _ = copies
    assert apply(two, P2, "--check").returncode != 0 and apply(two, P2, "--check", "-R").returncode == 0
    bare = copy_pipeline(tmp_path / "bare")  # only the second patch: it does NOT even apply, because it edits extract_conditions on top of the first patch (STR-101 scope evidence) as well as notice_articles
    assert apply(bare, P2).returncode != 0
    assert tree_hash(bare) == tree_hash(DELIVERED)


def test_it_composes_with_the_stage1_patch(tmp_path):
    root = copy_pipeline(tmp_path / "all")
    for p in (STAGE1, P1, P2):
        assert apply(root, p).returncode == 0, p.name
    r = run_pytest(["tests"], root)
    assert r.returncode == 0 and "93 passed" in r.stdout, r.stdout[-600:]


def test_work_s_own_tests_pass_with_both_patches(copies):
    _, two, _ = copies
    r = run_pytest(["tests"], two)
    assert r.returncode == 0 and "93 passed" in r.stdout, r.stdout[-800:]


def test_the_behaviour_tests_pass_with_both_patches_and_cannot_run_with_only_the_first(copies):
    one, two, _ = copies
    for root, ok in ((two, True), (one, False)):
        shutil.copy(B1, root / "tests" / "test_behaviour_g2_faq.py")
        shutil.copy(B2, root / "tests" / "test_behaviour_g2_unconfirmed.py")
        shutil.copy(B3, root / "tests" / "test_behaviour_g2_scope_evidence.py")
        try:
            r = run_pytest(["tests/test_behaviour_g2_unconfirmed.py", "tests/test_behaviour_g2_scope_evidence.py"], root)
        finally:
            (root / "tests" / "test_behaviour_g2_faq.py").unlink()
            (root / "tests" / "test_behaviour_g2_unconfirmed.py").unlink()
            (root / "tests" / "test_behaviour_g2_scope_evidence.py").unlink()
        if ok:
            assert r.returncode == 0 and "passed" in r.stdout and "failed" not in r.stdout, r.stdout[-1500:]
        else:
            assert r.returncode != 0 and "unconfirmed_faq" in (r.stdout + r.stderr)


def test_the_patch_adds_no_network_database_or_process_calls():
    added = [ln[1:] for ln in P2.read_bytes().decode("utf-8").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    import re
    assert [ln for ln in added if re.search(r"urlopen|requests\.|socket|subprocess|os\.system|sqlite3|\.execute\(|\bopen\(|write_text|write_bytes\(|unlink|rmtree", ln)] == []
