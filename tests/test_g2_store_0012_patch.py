"""SELF_TEST (Claude, contract owner) for the third g2 patch (patches/g2-faq/work-store-0012-wiring.patch): the Work store gets record_unconfirmed_faq_evidence, which files UNKNOWN-scope FAQ
evidence into the append-only table of migration 0012. Like the other patch tests it works only on COPIES of Work's delivered pipeline; research/inbox/ is never written.

Proven: the patch applies after the stage-1, g2 and g2-unconfirmed patches (and not without them), is reversible, touches exactly one file (admissions_pipeline/store.py) and adds none; Work's own 93 tests
still pass with all four; the behaviour file (tests/behaviour_g2_store_0012.py) passes on the patched copy against disposable databases and cannot run on a copy without the patch.
NOT proven (docs/G2_STORE_0012_WIRING_2026-11-12.md): that Work applies it, that its driver calls the method, or any independent QA (requested from Antigravity)."""
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
STAGE1 = REPO / "patches" / "m1-stage1" / "work-pipeline-stage1.patch"
P1 = REPO / "patches" / "g2-faq" / "work-faq-g2.patch"
P2 = REPO / "patches" / "g2-faq" / "work-faq-g2-unconfirmed-section.patch"
P3 = REPO / "patches" / "g2-faq" / "work-store-0012-wiring.patch"
BEHAVIOUR = REPO / "tests" / "behaviour_g2_store_0012.py"
ORDER = (STAGE1, P1, P2, P3)


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def apply(root, patch, *flags):
    return subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", *flags, str(patch)], cwd=root, capture_output=True, text=True, encoding="utf-8")


def copy_pipeline(dest, upto=0):
    shutil.copytree(DELIVERED, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    for p in ORDER[:upto]:
        r = apply(dest, p)
        assert r.returncode == 0, (p.name, r.stderr)
    return dest


def run_pytest(args, cwd, extra_env=None):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONPATH": str(REPO), **(extra_env or {})}
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=1200)


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    base = tmp_path_factory.mktemp("g2p3")
    before = tree_hash(DELIVERED)
    three = copy_pipeline(base / "three", 3)
    four = copy_pipeline(base / "four", 4)
    yield three, four, before
    assert tree_hash(DELIVERED) == before


def test_the_third_patch_changes_exactly_store_py_and_adds_nothing(copies):
    three, four, _ = copies
    a, b = tree_hash(three), tree_hash(four)
    assert {k for k in a if a[k] != b.get(k)} == {"admissions_pipeline/store.py"} and set(a) == set(b)


def test_it_keeps_the_line_endings_of_the_source_file(copies):
    three, four, _ = copies
    for root in (three, four):
        raw = (root / "admissions_pipeline" / "store.py").read_bytes()
        assert raw.count(b"\r\n") == raw.count(b"\n")  # the delivered file is CRLF throughout: no mixed endings


def test_it_does_not_apply_twice_and_is_reversible(copies):
    _, four, _ = copies
    assert apply(four, P3, "--check").returncode != 0 and apply(four, P3, "--check", "-R").returncode == 0


def test_without_its_predecessors_the_method_cannot_be_used(tmp_path):
    """The hunk only appends to the end of store.py, so it applies textually to any copy; the ORDER is therefore enforced at run time: the method imports the g2 modules and needs the registered
    functions of the stage-1 connection, and fails closed (ImportError / RuntimeError) without them."""
    bare = copy_pipeline(tmp_path / "bare", 0)
    assert apply(bare, P3).returncode == 0
    code = "import sys;sys.path.insert(0,'.');from admissions_pipeline.store import EvidenceStore as E;E('x.sqlite').record_unconfirmed_faq_evidence({},'c','a')"
    r = subprocess.run([sys.executable, "-B", "-c", code], cwd=bare, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode != 0 and "ModuleNotFoundError" in r.stderr


def test_work_s_own_tests_pass_with_all_four_patches(copies):
    _, four, _ = copies
    r = run_pytest(["tests"], four)
    assert r.returncode == 0 and "93 passed" in r.stdout, r.stdout[-800:]


def test_the_behaviour_tests_pass_on_the_patched_copy_and_cannot_run_without_the_patch(copies):
    three, four, _ = copies
    r = run_pytest(["tests/behaviour_g2_store_0012.py"], REPO, {"SOGH_PIPELINE_ROOT": str(four)})
    assert r.returncode == 0 and "failed" not in r.stdout, r.stdout[-3000:] + r.stderr[-500:]
    assert int(re.search(r"(\d+) passed", r.stdout).group(1)) >= 20, r.stdout[-500:]  # a silently empty run is not a pass
    r = run_pytest(["tests/behaviour_g2_store_0012.py"], REPO, {"SOGH_PIPELINE_ROOT": str(three)})
    assert r.returncode != 0 and "record_unconfirmed_faq_evidence" in (r.stdout + r.stderr)


def test_the_patch_only_adds_a_method_that_writes_the_one_table_and_never_facts():
    added = [ln[1:] for ln in P3.read_bytes().decode("utf-8").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    text = "\n".join(added)
    assert not re.search(r"urlopen|requests\.|socket|subprocess|os\.system|\bopen\(|write_text|write_bytes\(|unlink|rmtree", text)
    writes = re.findall(r"(INSERT|UPDATE|DELETE|REPLACE)[^\"']*?(?:INTO|FROM)?\s*\"?\s*(\w*)", text)
    assert "INSERT INTO \" + table" in text and not re.search(r"(UPDATE|DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+(OR\s+\w+\s+)?INTO)\s+(facts|admission_cycles|source_documents|article)", text, re.I)
    assert not re.search(r"INSERT\s+OR\s+(IGNORE|REPLACE)|ON\s+CONFLICT", text, re.I), writes  # a duplicate is refused, never ignored or replaced
