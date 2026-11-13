"""Restore approval manifest: the record that the USER (and no AI) approved a restore, checkable by signature.

Status: CONTRACT_PROPOSAL + SELF_VALIDATED reference verifier (Claude).  It applies no schema and writes nothing.  The user approved this form on 2026-11-07:
"approver = the user; evidence = a manifest file in a commit signed with the user's SSH key".

Why a signature: every AI and the user post to GitHub as the same account, so an Issue comment cannot show who approved.  An SSH-signed commit can be made only by whoever holds the private key.

What `verify_approval` proves, all of it, or it raises ApprovalError (nothing is trusted on a partial pass):
  1. the approval reference ``sha256:<manifest digest>@<commit>`` is well formed;
  2. the manifest bytes in that commit hash to the digest in the reference (no later edit);
  3. the commit carries a good SSH signature whose key fingerprint is exactly the pinned TRUSTED fingerprint (not merely "some key in the allowed-signers file");
  4. the commit changes that one manifest file and nothing else (a signed commit cannot smuggle other changes under the approval);
  5. the manifest is valid for the schema, says ``approve``, and its restore id is its file name;
  6. what the manifest approves (archive SHA, source DB SHA, restore id) equals what the caller is about to restore;
  7. the signer's principal equals the manifest's ``approved_by``;
  8. (optional) the commit is an ancestor of a given ref, e.g. master, so that it went through review.
The trust root is the pinned fingerprint.  Whoever can change it can approve; it is therefore recorded in a reviewed document and confirmed by the user, never read from the file being checked.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "sogh.restore_approval.v1"
KINDS = ("f2_recovery",)
MANIFEST_KEYS = frozenset({"schema", "restore_id", "kind", "decision", "archive_sha256", "source_db_sha256", "items", "items_digest", "approved_by", "approved_at", "note"})
ITEM_KEYS = frozenset({"kind", "id", "digest"})
ITEM_KINDS = ("article_version", "evidence_version", "citation")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REF = re.compile(r"^sha256:([0-9a-f]{64})@([0-9a-f]{40})$")
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")
RESTORE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ApprovalError(ValueError):
    """The approval cannot be shown.  ``code`` names the first failed check."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_of(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def approval_ref(manifest_bytes: bytes, commit: str) -> str:
    """The value a restore event stores as ``approval_ref``."""
    if not COMMIT.match(commit):
        raise ApprovalError("bad_ref", "commit must be a full 40-hex id")
    return f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}@{commit}"


def parse_manifest(raw: bytes, *, file_stem: str | None = None) -> dict[str, Any]:
    try:
        m = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ApprovalError("manifest_invalid", f"not UTF-8 JSON: {exc}") from exc
    if not isinstance(m, dict) or set(m) != MANIFEST_KEYS:
        raise ApprovalError("manifest_invalid", f"the manifest must have exactly the keys {sorted(MANIFEST_KEYS)}")
    if m["schema"] != SCHEMA:
        raise ApprovalError("manifest_invalid", f"schema must be {SCHEMA!r}")
    if m["kind"] not in KINDS:
        raise ApprovalError("manifest_invalid", f"kind must be one of {KINDS}")
    if m["decision"] != "approve":
        raise ApprovalError("not_approved", f"decision is {m['decision']!r}, not 'approve'")
    if not isinstance(m["restore_id"], str) or not RESTORE_ID.match(m["restore_id"]):
        raise ApprovalError("manifest_invalid", "restore_id is not a safe identifier")
    if file_stem is not None and m["restore_id"] != file_stem:
        raise ApprovalError("manifest_invalid", "restore_id must equal the manifest file name")
    for k in ("archive_sha256", "source_db_sha256", "items_digest"):
        if not isinstance(m[k], str) or not SHA256.match(m[k]):
            raise ApprovalError("manifest_invalid", f"{k} must be 64 lowercase hex")
    for k in ("approved_by", "note"):
        if not isinstance(m[k], str) or not m[k].strip():
            raise ApprovalError("manifest_invalid", f"{k} must be non-empty text")
    if not isinstance(m["approved_at"], str) or not ISO.match(m["approved_at"]):
        raise ApprovalError("manifest_invalid", "approved_at must be an ISO 8601 time with a zone")
    items = m["items"]
    if not isinstance(items, list) or not items:
        raise ApprovalError("manifest_invalid", "items must be a non-empty list")
    seen = set()
    for it in items:
        if not isinstance(it, dict) or set(it) != ITEM_KEYS or it["kind"] not in ITEM_KINDS or not isinstance(it["id"], str) or not it["id"].strip() \
                or not isinstance(it["digest"], str) or not SHA256.match(it["digest"]):
            raise ApprovalError("manifest_invalid", f"every item needs exactly {sorted(ITEM_KEYS)} with a known kind and a 64-hex digest")
        key = (it["kind"], it["id"])
        if key in seen:
            raise ApprovalError("manifest_invalid", f"duplicate item {key}")
        seen.add(key)
    if digest_of(items) != m["items_digest"]:
        raise ApprovalError("manifest_invalid", "items_digest is not the digest of items")
    return m


def _git(repo: Path, *args: str, env_cfg: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(repo)]
    for c in env_cfg:
        cmd += ["-c", c]
    return subprocess.run(cmd + list(args), capture_output=True, text=False, timeout=60)


@dataclass(frozen=True)
class Approval:
    restore_id: str
    approved_by: str
    approved_at: str
    commit: str
    manifest_sha256: str
    signer_fingerprint: str
    items_digest: str
    approval_ref: str


def verify_approval(repo: str | Path, ref: str, *, manifest_path: str, allowed_signers: str | Path, trusted_fingerprint: str, expect: Mapping[str, str],
                    must_be_ancestor_of: str | None = None) -> Approval:
    """Show that the user approved exactly the restore described by ``expect`` (keys: restore_id, archive_sha256, source_db_sha256).  Raises ApprovalError otherwise."""
    repo = Path(repo)
    m = REF.match(ref) if isinstance(ref, str) else None
    if not m:
        raise ApprovalError("bad_ref", "approval_ref must be 'sha256:<64 hex>@<40 hex commit>'")
    want_digest, commit = m.group(1), m.group(2)
    if not isinstance(trusted_fingerprint, str) or not FINGERPRINT.match(trusted_fingerprint):
        raise ApprovalError("bad_trust_root", "the pinned fingerprint must look like 'SHA256:<43 base64 characters>'")
    if set(expect) != {"restore_id", "archive_sha256", "source_db_sha256"}:
        raise ApprovalError("bad_input", "expect must have restore_id, archive_sha256 and source_db_sha256")
    if not re.match(r"^[A-Za-z0-9._/-]+\.json$", manifest_path) or ".." in manifest_path:
        raise ApprovalError("bad_input", "manifest_path must be a plain relative .json path")

    shown = _git(repo, "show", f"{commit}:{manifest_path}")
    if shown.returncode != 0:
        raise ApprovalError("manifest_missing", f"{manifest_path} does not exist in commit {commit}")
    if hashlib.sha256(shown.stdout).hexdigest() != want_digest:
        raise ApprovalError("manifest_changed", "the manifest in the signed commit does not match the digest in the approval reference")

    # the signature: a good SSH signature whose key is exactly the pinned one
    ver = _git(repo, "verify-commit", "--raw", commit, env_cfg=("gpg.format=ssh", f"gpg.ssh.allowedSignersFile={Path(allowed_signers).as_posix()}"))
    status = ver.stderr.decode("utf-8", errors="replace")
    good = re.search(r'Good "git" signature for (\S+) with (?:ED25519|RSA|ECDSA)\S* key (SHA256:[A-Za-z0-9+/]{43})', status)
    if ver.returncode != 0 or not good:
        raise ApprovalError("not_signed", "the commit has no good SSH signature from a key in the allowed-signers file")
    principal, fingerprint = good.group(1), good.group(2)
    if fingerprint != trusted_fingerprint:
        raise ApprovalError("wrong_signer", f"signed by {fingerprint}, not by the pinned approver key")

    # the commit is only the approval
    changed = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit)
    files = [f for f in changed.stdout.decode("utf-8", errors="replace").splitlines() if f]
    if files != [manifest_path]:
        raise ApprovalError("commit_not_only_the_approval", f"the signed commit changes {files}, not just {manifest_path}")

    manifest = parse_manifest(shown.stdout, file_stem=Path(manifest_path).stem)
    for k in ("restore_id", "archive_sha256", "source_db_sha256"):
        if manifest[k] != expect[k]:
            raise ApprovalError("approval_mismatch", f"the approval is for a different {k}")
    if principal != manifest["approved_by"]:
        raise ApprovalError("signer_not_approver", f"signed by principal {principal!r}, the manifest names {manifest['approved_by']!r}")
    if must_be_ancestor_of is not None:
        anc = _git(repo, "merge-base", "--is-ancestor", commit, must_be_ancestor_of)
        if anc.returncode != 0:
            raise ApprovalError("not_reviewed", f"the approval commit is not an ancestor of {must_be_ancestor_of}")
    return Approval(restore_id=manifest["restore_id"], approved_by=manifest["approved_by"], approved_at=manifest["approved_at"], commit=commit, manifest_sha256=want_digest,
                    signer_fingerprint=fingerprint, items_digest=manifest["items_digest"], approval_ref=ref)
