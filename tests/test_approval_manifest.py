"""Independent tests of the restore approval manifest verifier (src/db_contract/approval_manifest.py).

Every key, repository and manifest here is THROWAWAY and SYNTHETIC (an unprotected ed25519 key made in a temporary directory for the test, invented ids and digests).
Nothing here is, or stands for, the user's real approval key.  A pass shows the verifier's behaviour; it approves nothing and restores nothing.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from src.db_contract import approval_manifest as am

ARCHIVE, SOURCE = "a" * 64, "b" * 64
PRINCIPAL = "the-user"
REL = "approvals/restore/R-1.json"
GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false"]


def run(args, cwd, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{args} failed: {r.stderr}")
    return r


def make_key(tmp: Path, name: str):
    key = tmp / name
    run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], tmp)
    pub = (key.with_suffix(".pub") if key.suffix else Path(str(key) + ".pub"))
    fp = re.search(r"(SHA256:\S+)", run(["ssh-keygen", "-lf", str(pub)], tmp).stdout).group(1)
    return key, pub, fp


def items():
    return [{"kind": "article_version", "id": "art-old", "digest": "1" * 64}, {"kind": "evidence_version", "id": "EV-1", "digest": "2" * 64},
            {"kind": "citation", "id": "art-old|EV-1", "digest": "3" * 64}]


def manifest(**over):
    m = {"schema": am.SCHEMA, "restore_id": "R-1", "kind": "f2_recovery", "decision": "approve", "archive_sha256": ARCHIVE, "source_db_sha256": SOURCE,
         "items": items(), "approved_by": PRINCIPAL, "approved_at": "2026-11-07T20:00:00+09:00", "note": "synthetic test approval"}
    m["items_digest"] = am.digest_of(m["items"])
    m.update(over)
    return m


class World:
    def __init__(self, tmp: Path):
        self.tmp, self.repo = tmp, tmp / "repo"
        self.repo.mkdir()
        run(GIT + ["init", "-q", "-b", "master"], self.repo)
        (self.repo / "README.md").write_text("x", encoding="utf-8")
        run(GIT + ["add", "-A"], self.repo)
        run(GIT + ["commit", "-q", "-m", "base"], self.repo)
        self.user_key, self.user_pub, self.user_fp = make_key(tmp, "userkey")
        self.agent_key, self.agent_pub, self.agent_fp = make_key(tmp, "agentkey")
        self.signers = tmp / "allowed_signers"
        lines = [f'{PRINCIPAL} namespaces="git" {self.user_pub.read_text().strip()}', f'agent namespaces="git" {self.agent_pub.read_text().strip()}']
        self.signers.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def commit(self, files: dict[str, bytes], key: Path | None, msg="approval") -> str:
        for rel, data in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        run(GIT + ["add", "-A"], self.repo)
        base = ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "gpg.format=ssh"]
        if key is not None:
            run(base + ["-c", f"user.signingkey={key}.pub", "commit", "-q", "-S", "-m", msg], self.repo)
        else:
            run(base + ["commit", "-q", "--no-gpg-sign", "-m", msg], self.repo)
        return run(["git", "rev-parse", "HEAD"], self.repo).stdout.strip()

    def verify(self, ref, **over):
        kw = dict(manifest_path=REL, allowed_signers=self.signers, trusted_fingerprint=self.user_fp, expect={"restore_id": "R-1", "archive_sha256": ARCHIVE, "source_db_sha256": SOURCE})
        kw.update(over)
        return am.verify_approval(self.repo, ref, **kw)


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def good_commit(w: World, m=None, key=None):
    raw = json.dumps(m or manifest(), ensure_ascii=False, indent=2).encode("utf-8")
    c = w.commit({REL: raw}, key or w.user_key)
    return raw, c, am.approval_ref(raw, c)


def refused(w, ref, code, **over):
    with pytest.raises(am.ApprovalError) as e:
        w.verify(ref, **over)
    assert e.value.code == code, str(e.value)


def test_a_manifest_in_a_commit_signed_by_the_pinned_key_verifies_and_returns_the_reference(w):
    raw, c, ref = good_commit(w)
    a = w.verify(ref)
    assert (a.restore_id, a.approved_by, a.commit, a.signer_fingerprint, a.approval_ref) == ("R-1", PRINCIPAL, c, w.user_fp, ref)
    assert a.manifest_sha256 == hashlib.sha256(raw).hexdigest() and a.items_digest == am.digest_of(items())


def test_the_check_writes_nothing_to_the_repository(w):
    raw, c, ref = good_commit(w)
    before = run(["git", "status", "--porcelain"], w.repo).stdout, run(["git", "rev-parse", "HEAD"], w.repo).stdout
    w.verify(ref)
    assert (run(["git", "status", "--porcelain"], w.repo).stdout, run(["git", "rev-parse", "HEAD"], w.repo).stdout) == before


def test_an_unsigned_commit_is_not_an_approval(w):
    raw = json.dumps(manifest()).encode()
    c = w.commit({REL: raw}, None)
    refused(w, am.approval_ref(raw, c), "not_signed")


def test_a_commit_signed_by_another_key_that_is_in_the_allowed_file_is_still_refused_because_only_the_pinned_fingerprint_counts(w):
    raw, c, ref = good_commit(w, key=w.agent_key)
    refused(w, ref, "wrong_signer")


def test_a_commit_signed_by_a_key_missing_from_the_allowed_file_is_refused(w):
    stranger, _, _ = make_key(w.tmp, "stranger")
    raw, c, ref = good_commit(w, key=stranger)
    refused(w, ref, "not_signed")


def test_a_manifest_edited_after_signing_is_refused_even_if_the_edit_is_committed_unsigned_on_top(w):
    raw, c, ref = good_commit(w)
    w.commit({REL: json.dumps(manifest(note="edited later")).encode()}, None, "edit")
    # the old reference still verifies against the SIGNED commit's bytes ...
    assert w.verify(ref).commit == c
    # ... and a reference that names the unsigned edit is refused
    edited = (w.repo / REL).read_bytes()
    head = run(["git", "rev-parse", "HEAD"], w.repo).stdout.strip()
    refused(w, am.approval_ref(edited, head), "not_signed")
    # a reference that pairs the signed commit with the edited bytes is refused
    refused(w, am.approval_ref(edited, c), "manifest_changed")


def test_a_signed_commit_that_also_changes_other_files_is_refused(w):
    raw = json.dumps(manifest()).encode()
    c = w.commit({REL: raw, "src/evil.py": b"print(1)"}, w.user_key)
    refused(w, am.approval_ref(raw, c), "commit_not_only_the_approval")


def test_a_signed_commit_that_does_not_contain_the_manifest_path_is_refused(w):
    c = w.commit({"other.json": b"{}"}, w.user_key)
    refused(w, am.approval_ref(b"{}", c), "manifest_missing")


@pytest.mark.parametrize("field,value", [("archive_sha256", "c" * 64), ("source_db_sha256", "c" * 64)])
def test_an_approval_for_a_different_archive_or_source_is_refused(w, field, value):
    raw, c, ref = good_commit(w)
    refused(w, ref, "approval_mismatch", expect={"restore_id": "R-1", "archive_sha256": ARCHIVE, "source_db_sha256": SOURCE, field: value})


def test_an_approval_for_a_different_restore_id_is_refused(w):
    raw, c, ref = good_commit(w)
    refused(w, ref, "approval_mismatch", expect={"restore_id": "R-2", "archive_sha256": ARCHIVE, "source_db_sha256": SOURCE})


def test_the_signer_principal_must_be_the_named_approver(w):
    raw, c, ref = good_commit(w, m=manifest(approved_by="someone-else"))
    refused(w, ref, "signer_not_approver")


def test_the_approval_commit_must_be_reviewed_when_an_ancestor_ref_is_required(w):
    raw, c, ref = good_commit(w)
    run(GIT + ["branch", "side", "master~1"], w.repo)
    refused(w, ref, "not_reviewed", must_be_ancestor_of="side")
    assert w.verify(ref, must_be_ancestor_of="master").commit == c


@pytest.mark.parametrize("bad", ["", "sha256:abc@def", "md5:" + "a" * 64 + "@" + "b" * 40, "sha256:" + "a" * 64 + "@" + "b" * 39, "sha256:" + "A" * 64 + "@" + "b" * 40])
def test_a_malformed_reference_is_refused(w, bad):
    refused(w, bad, "bad_ref")


def test_a_trust_root_that_is_not_a_fingerprint_is_refused(w):
    raw, c, ref = good_commit(w)
    for bad in ("", "userkey", "SHA256:short", w.user_fp.lower()):
        refused(w, ref, "bad_trust_root", trusted_fingerprint=bad)


def test_bad_inputs_are_refused_before_anything_is_read(w):
    raw, c, ref = good_commit(w)
    refused(w, ref, "bad_input", expect={"restore_id": "R-1"})
    refused(w, ref, "bad_input", manifest_path="../x.json")
    refused(w, ref, "bad_input", manifest_path="approvals/restore/R-1.txt")


CASES = [
    ("decision-reject", lambda m: m.update(decision="reject"), "not_approved", True),
    ("decision-approved-typo", lambda m: m.update(decision="approved"), "not_approved", True),
    ("old-schema", lambda m: m.update(schema="sogh.restore_approval.v0"), "manifest_invalid", True),
    ("unknown-kind", lambda m: m.update(kind="other"), "manifest_invalid", True),
    ("restore-id-not-file-name", lambda m: m.update(restore_id="R-9"), "manifest_invalid", True),
    ("extra-key", lambda m: m.update(extra="x"), "manifest_invalid", True),
    ("missing-note", lambda m: m.pop("note"), "manifest_invalid", True),
    ("uppercase-sha", lambda m: m.update(archive_sha256="A" * 64), "manifest_invalid", True),
    ("items-digest-wrong", lambda m: m.update(items_digest="0" * 64), "manifest_invalid", False),
    ("items-empty", lambda m: m.update(items=[]), "manifest_invalid", True),
    ("items-duplicate", lambda m: m["items"].append(dict(m["items"][0])), "manifest_invalid", True),
    ("item-kind-unknown", lambda m: m["items"][0].update(kind="mystery"), "manifest_invalid", True),
    ("item-extra-key", lambda m: m["items"][0].update(extra=1), "manifest_invalid", True),
    ("time-without-zone", lambda m: m.update(approved_at="yesterday"), "manifest_invalid", True),
    ("approver-blank", lambda m: m.update(approved_by=" "), "manifest_invalid", True),
]


@pytest.mark.parametrize("mut,code,recompute", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_an_invalid_or_non_approving_manifest_is_refused_even_when_signed(w, mut, code, recompute):
    m = manifest()
    mut(m)
    if recompute and isinstance(m.get("items"), list):
        m["items_digest"] = am.digest_of(m["items"])  # keep the digest consistent so that only the intended defect remains
    raw = json.dumps(m).encode()
    c = w.commit({REL: raw}, w.user_key)
    refused(w, am.approval_ref(raw, c), code)


def test_a_manifest_that_is_not_json_is_refused_even_when_signed(w):
    raw = b"\xff\xfe not json"
    c = w.commit({REL: raw}, w.user_key)
    refused(w, am.approval_ref(raw, c), "manifest_invalid")


def test_the_manifest_may_not_be_a_different_file_than_its_restore_id(w):
    raw = json.dumps(manifest()).encode()
    c = w.commit({"approvals/restore/R-7.json": raw}, w.user_key)
    refused(w, am.approval_ref(raw, c), "manifest_invalid", manifest_path="approvals/restore/R-7.json")
