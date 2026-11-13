"""Tests of scripts/sign_restore_approval.py (the user's signing helper).  THROWAWAY keys and SYNTHETIC data only; nothing here is the user's key or approval."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from src.db_contract import approval_manifest as am
from tests.test_approval_manifest import ARCHIVE, GIT, PRINCIPAL, REL, SOURCE, World, manifest, run

SPEC = importlib.util.spec_from_file_location("sign_helper", Path(__file__).resolve().parents[1] / "scripts" / "sign_restore_approval.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
import json  # noqa: E402


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def unsigned_branch(w, **over):
    run(GIT + ["switch", "-q", "-c", "approval"], w.repo)
    w.commit({REL: json.dumps(manifest(**over), ensure_ascii=False, indent=1).encode("utf-8")}, None)


def call(w, *extra, answer="SIGN R-1", archive=ARCHIVE, source=SOURCE):
    return helper.main(["--restore-id", "R-1", "--archive-sha", archive, "--source-db-sha", source, "--key", str(w.user_pub), *extra],
                       repo=w.repo, principal=PRINCIPAL, fingerprint=w.user_fp, signers=w.signers, ask=lambda _p: answer)


def head(w):
    return run(["git", "rev-parse", "HEAD"], w.repo).stdout.strip()


def test_happy_path_signs_and_verifies(w, capsys):
    unsigned_branch(w)
    before = head(w)
    assert call(w) == 0
    assert head(w) != before                                   # amended -> a new, signed commit
    out = capsys.readouterr().out
    assert "Signed and verified" in out and "approval_ref: sha256:" in out
    ref = [x for x in out.splitlines() if "approval_ref:" in x][0].split("approval_ref:")[1].strip()
    am.verify_approval(w.repo, ref, manifest_path=REL, allowed_signers=w.signers, trusted_fingerprint=w.user_fp,
                       expect={"restore_id": "R-1", "archive_sha256": ARCHIVE, "source_db_sha256": SOURCE})


def test_check_mode_signs_nothing(w, capsys):
    unsigned_branch(w)
    before = head(w)
    assert call(w, "--check") == 0
    assert head(w) == before and run(["git", "log", "-1", "--format=%G?"], w.repo).stdout.strip() == "N"
    assert "nothing was signed" in capsys.readouterr().out


def test_wrong_confirmation_signs_nothing(w):
    unsigned_branch(w)
    before = head(w)
    assert call(w, answer="yes") == 2 and head(w) == before


@pytest.mark.parametrize("bad", ["archive", "source"])
def test_hashes_differing_from_the_ones_you_pass_stop_before_any_question(w, bad, capsys):
    unsigned_branch(w)
    before = head(w)
    asked = []
    rc = helper.main(["--restore-id", "R-1", "--archive-sha", "c" * 64 if bad == "archive" else ARCHIVE, "--source-db-sha", "d" * 64 if bad == "source" else SOURCE,
                      "--key", str(w.user_pub)], repo=w.repo, principal=PRINCIPAL, fingerprint=w.user_fp, signers=w.signers, ask=lambda p: asked.append(p) or "SIGN R-1")
    assert rc == 2 and not asked and head(w) == before and "Do NOT sign" in capsys.readouterr().out


def test_refuses_on_master(w):
    w.commit({REL: json.dumps(manifest()).encode("utf-8")}, None)      # still on master
    assert call(w) == 2


def test_refuses_dirty_tree(w):
    unsigned_branch(w)
    (w.repo / "stray.txt").write_text("x", encoding="utf-8")
    assert call(w) == 2


def test_refuses_a_commit_with_another_file(w):
    run(GIT + ["switch", "-q", "-c", "approval"], w.repo)
    w.commit({REL: json.dumps(manifest()).encode("utf-8"), "extra.txt": b"x"}, None)
    assert call(w) == 2


def test_refuses_an_already_signed_commit(w):
    run(GIT + ["switch", "-q", "-c", "approval"], w.repo)
    w.commit({REL: json.dumps(manifest()).encode("utf-8")}, w.user_key)
    assert call(w) == 2


def test_refuses_another_approver_and_a_broken_items_digest(w):
    unsigned_branch(w, approved_by="someone-else")
    assert call(w) == 2
    run(GIT + ["switch", "-q", "master"], w.repo)
    run(GIT + ["branch", "-q", "-D", "approval"], w.repo)
    unsigned_branch(w, items_digest="e" * 64)
    assert call(w) == 2


def test_a_pinned_fingerprint_that_is_not_the_signing_key_is_reported_after_signing(w, capsys):
    unsigned_branch(w)
    rc = helper.main(["--restore-id", "R-1", "--archive-sha", ARCHIVE, "--source-db-sha", SOURCE, "--key", str(w.user_pub)],
                     repo=w.repo, principal=PRINCIPAL, fingerprint=w.agent_fp, signers=w.signers, ask=lambda _p: "SIGN R-1")
    assert rc == 3 and "does NOT verify" in capsys.readouterr().out


def test_key_must_be_a_public_key_file(w):
    unsigned_branch(w)
    rc = helper.main(["--restore-id", "R-1", "--archive-sha", ARCHIVE, "--source-db-sha", SOURCE, "--key", str(w.user_key)],
                     repo=w.repo, principal=PRINCIPAL, fingerprint=w.user_fp, signers=w.signers, ask=lambda _p: "SIGN R-1")
    assert rc == 2
