"""M1.g2 (FAQ extraction): a PROPOSAL for Work's pipeline, as a patch in patches/g2-faq/. SELF_TEST (author's own); independent QA is Antigravity's.

Two defects, both reported by Antigravity's independent QA (PR #272, STR-076):
  1 heading carry-over: every FAQ proof names the heading in front of the whole group of questions (``section_start``), not the question it quotes;
  2 STR-076: the FAQ record is bound to case ``tsukuba-klis-ac-2027`` / fiscal year 2027 / faculty 情報学群 although the FAQ page states none of them.

The patch is applied only to COPIES of the delivered pipeline in a temporary directory; research/inbox/ (Work's manifest-checked files) is never written.
What is proven here: it applies cleanly and is reversible; it touches exactly the declared files; Work's own 93 tests pass on the delivered and on the patched copy;
the behaviour file tests/behaviour_g2_faq.py (27 tests) passes on the patched copy and cannot even be imported on the delivered one; the patch composes with the
M1 stage-1 patch; and the saved candidate (faq-candidate.json) shows the defect, the declared headings are the very wording of the saved anchors, and every saved
condition proof falls inside exactly one saved anchor, so the corrected section of each proof is determined by the saved offsets alone.
NOT proven: a run on the real saved HTML body (dad557c5...), which is not in this repository.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "research" / "inbox" / "work-faq-v3"
DELIVERED = V3 / "pipeline"
PATCH = REPO / "patches" / "g2-faq" / "work-faq-g2.patch"
STAGE1 = REPO / "patches" / "m1-stage1" / "work-pipeline-stage1.patch"
BEHAVIOUR = REPO / "tests" / "behaviour_g2_faq.py"
CHANGED = {"admissions_pipeline/faq_policy.py", "admissions_pipeline/supplements.py", "config/faq-structured-v3.json", "scripts/revise_notices.py"}
ADDED = {"admissions_pipeline/headings.py"}
Q0 = "ＡＣ入試の選考で重視されるのはどのようなことですか？"
Q1 = "生成AIを使用した場合は、どこまで下線を引けばよいのでしょうか？"
Q2 = "生成AIで作成した画像（図や表等も含む）はどのようにすればよいでしょうか？"
SHA = "dad557c53e2e66f6f05807d90abb6cfc708a55b6200dec579d1bf2389cf9a770"


def tree_hash(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def copy_pipeline(dest: Path) -> Path:
    shutil.copytree(DELIVERED, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    return dest


def git_apply(root: Path, patch: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", *flags, str(patch)], cwd=root, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    base = tmp_path_factory.mktemp("g2faq")
    before = tree_hash(DELIVERED)
    delivered = copy_pipeline(base / "delivered")
    patched = copy_pipeline(base / "patched")
    done = git_apply(patched, PATCH)
    assert done.returncode == 0, done.stderr
    yield delivered, patched, before
    assert tree_hash(DELIVERED) == before  # Work's directory is byte-for-byte what it was


def run_pytest(args, cwd, env_extra=None):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", **(env_extra or {})}
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=900)


# ------------------------------------------------------------------ the patch itself
def test_the_patch_touches_exactly_the_declared_files(copies):
    delivered, patched, _ = copies
    a, b = tree_hash(delivered), tree_hash(patched)
    assert {k for k in a if a[k] != b.get(k)} == CHANGED and set(b) - set(a) == ADDED and not set(a) - set(b)


def test_the_patch_does_not_apply_twice_and_is_exactly_reversible(copies):
    delivered, patched, _ = copies
    assert git_apply(patched, PATCH, "--check").returncode != 0
    assert git_apply(patched, PATCH, "--check", "-R").returncode == 0
    assert git_apply(delivered, PATCH, "--check").returncode == 0


def test_the_patch_composes_with_the_m1_stage1_patch(tmp_path):
    both = copy_pipeline(tmp_path / "both")
    for patch in (STAGE1, PATCH):
        done = git_apply(both, patch)
        assert done.returncode == 0, patch.name + done.stderr
    r = run_pytest(["tests"], both, {"PYTHONPATH": str(REPO)})
    assert r.returncode == 0 and "93 passed" in r.stdout, r.stdout[-800:]


def test_the_patch_adds_no_network_database_or_process_calls():
    added = [ln[1:] for ln in PATCH.read_bytes().decode("utf-8").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    banned = re.compile(r"urlopen|requests\.|socket|subprocess|os\.system|sqlite3\.connect|\.execute\(|\bopen\(|write_text|write_bytes\(|unlink|rmtree")
    hits = [ln for ln in added if banned.search(ln) and "scope-unknown-held.json" not in ln]
    assert hits == [], hits
    assert len(added) < 140


# ------------------------------------------------------------------ Work's own tests and the behaviour file
def test_work_s_own_tests_pass_on_the_delivered_and_on_the_patched_copy(copies):
    delivered, patched, _ = copies
    for root in (delivered, patched):
        r = run_pytest(["tests"], root, {"PYTHONPATH": str(REPO)})
        assert r.returncode == 0, root.name + "\n" + r.stdout[-1500:] + r.stderr[-500:]
        assert "93 passed" in r.stdout, r.stdout[-300:]


def test_the_behaviour_tests_pass_on_the_patched_copy_and_cannot_run_on_the_delivered_one(copies, tmp_path):
    delivered, patched, _ = copies
    for root, ok in ((patched, True), (delivered, False)):
        shutil.copy(BEHAVIOUR, root / "tests" / "test_behaviour_g2_faq.py")
        try:
            r = run_pytest(["tests/test_behaviour_g2_faq.py"], root, {"PYTHONPATH": str(REPO)})
        finally:
            (root / "tests" / "test_behaviour_g2_faq.py").unlink()
        if ok:
            assert r.returncode == 0 and "27 passed" in r.stdout, r.stdout[-1500:]
        else:
            assert r.returncode != 0 and "headings" in (r.stdout + r.stderr), r.stdout[-600:]  # the delivered copy has no such module: the dependency is real


# ------------------------------------------------------------------ the saved candidate (Work's delivered data, read only)
@pytest.fixture(scope="module")
def candidate():
    return json.loads((V3 / "candidates" / "faq-candidate.json").read_text(encoding="utf-8"))


def norm(text):
    return "".join(c for ch in text for c in unicodedata.normalize("NFKC", ch) if not c.isspace())


def test_the_saved_candidate_shows_both_defects(candidate):
    base = candidate["base_record"]
    assert [p["section"] for p in candidate["proofs"]] == [Q0] * 6 and [p["section"] for p in base["proofs"]] == [Q0] * 2  # heading carry-over
    assert (base["case_id"], base["faculty"], base["fiscal_year"]) == ("tsukuba-klis-ac-2027", "情報学群", 2027)  # STR-076
    assert base["source_sha256"] == SHA and base["published_date"] is None


def test_the_declared_headings_are_the_saved_anchors_own_first_question(candidate, copies):
    _, patched, _ = copies
    spec = json.loads((patched / "config" / "faq-structured-v3.json").read_text(encoding="utf-8"))[0]
    anchors = candidate["base_record"]["proofs"]
    firsts = [a["quote"][: a["quote"].index("？") + 1] for a in anchors]
    assert firsts == [Q1, Q2] == spec["section_headings"]
    assert spec["section_start"] == Q0 and spec["expected_sha256"] == SHA


def test_every_saved_condition_proof_lies_in_exactly_one_saved_anchor(candidate):
    anchors = candidate["base_record"]["proofs"]
    expected = []
    for p in candidate["proofs"]:
        inside = [i for i, a in enumerate(anchors) if a["normalized_start"] <= p["normalized_start"] and p["normalized_end"] <= a["normalized_end"]]
        assert len(inside) == 1, p["normalized_start"]
        assert norm(p["quote"]) in norm(anchors[inside[0]]["quote"])  # and the text agrees with the offsets
        expected.append([Q1, Q2][inside[0]])
    assert expected == [Q1, Q1, Q1, Q1, Q1, Q2]  # what the patched extractor must (and, on the synthetic page, does) produce
    assert [(a["normalized_start"], a["normalized_end"]) for a in anchors] == [(7918, 8146), (8146, 8226)]  # offsets are not changed by the patch
