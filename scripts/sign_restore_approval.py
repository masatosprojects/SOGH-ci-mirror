"""Helper for the USER to sign a restore approval (docs/RESTORE_APPROVAL_MANIFEST_2026-11-07.md section 4).

Run it yourself, in your own terminal, on the approval branch.  It never reads your private key: it only tells git where your PUBLIC key
is, and git/ssh-keygen asks YOU for the passphrase.  It signs only after you have seen a summary and typed the confirmation words.

    python scripts/sign_restore_approval.py --restore-id R-F2-001 --archive-sha <hex from Work's report> --source-db-sha <hex from Work's report>
    python scripts/sign_restore_approval.py ... --check        # read-only: show the summary and the checks, sign nothing

What it checks before it asks you anything: the branch is not master, the work tree is clean, the HEAD commit changes exactly one file (the manifest) and is not
signed yet, the manifest is valid and its items_digest is right, the approver named in it is you (the pinned principal), and the archive / source-DB hashes in the
manifest equal the ones YOU passed (copy them from the report, not from the manifest, so you do not just trust the file you are about to sign).
After signing it verifies the result with the same verifier the restore tool uses and prints the approval reference.  It does not push.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.db_contract import approval_manifest as am  # noqa: E402
from src.db_contract import approval_trust as trust  # noqa: E402


class Stop(Exception):
    pass


def git(repo, *args, check=True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def prepare(repo, restore_id, archive_sha, source_db_sha, principal):
    """All the read-only checks.  Returns (manifest, manifest_bytes, rel_path)."""
    rel = f"approvals/restore/{restore_id}.json"
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("master", "main", "HEAD"):
        raise Stop(f"you are on '{branch}'. Switch to the approval branch first (git switch <branch>).")
    if git(repo, "status", "--porcelain"):
        raise Stop("the work tree is not clean. Commit or stash other changes first, so only the manifest is signed.")
    changed = [x for x in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() if x]
    if changed != [rel]:
        raise Stop(f"the HEAD commit must change exactly {rel}; it changes {changed}. Anything else makes the verifier refuse.")
    header = git(repo, "cat-file", "commit", "HEAD").split("\n\n", 1)[0]
    if any(line.startswith("gpgsig ") for line in header.splitlines()):
        raise Stop("the HEAD commit already carries a signature. Nothing to sign (or it was signed by someone else).")
    raw = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo, capture_output=True).stdout
    try:
        m = am.parse_manifest(raw, file_stem=restore_id)
    except am.ApprovalError as exc:
        raise Stop(f"the manifest is not valid: {exc}") from exc
    if m["approved_by"] != principal:
        raise Stop(f"the manifest names '{m['approved_by']}' as approver; the pinned approver is '{principal}'.")
    if m["archive_sha256"] != archive_sha or m["source_db_sha256"] != source_db_sha:
        raise Stop("the archive / source-DB hash in the manifest differs from the one you passed. Do NOT sign: ask who produced the manifest.")
    return m, raw, rel


def summary(m, rel):
    kinds = Counter(i["kind"] for i in m["items"])
    return "\n".join([
        f"  file         : {rel}",
        f"  restore_id   : {m['restore_id']}   (kind: {m['kind']}, decision: {m['decision']})",
        f"  archive      : {m['archive_sha256']}",
        f"  source DB    : {m['source_db_sha256']}",
        f"  items        : {len(m['items'])}  " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())),
        f"  items_digest : {m['items_digest']}  (recomputed: OK)",
        f"  approved_by  : {m['approved_by']}   approved_at: {m['approved_at']}",
        f"  note         : {m['note']}",
    ])


def main(argv=None, *, repo=REPO, principal=trust.APPROVER_PRINCIPAL, fingerprint=trust.APPROVER_FINGERPRINT, signers=None, ask=input):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--restore-id", required=True)
    p.add_argument("--archive-sha", required=True, help="64 hex, from Work's report (not copied from the manifest)")
    p.add_argument("--source-db-sha", required=True, help="64 hex, from Work's report")
    p.add_argument("--key", default=str(Path.home() / ".ssh" / "sogh_approver.pub"), help="path of your PUBLIC key (.pub)")
    p.add_argument("--check", action="store_true", help="read-only: show the summary and checks, sign nothing")
    a = p.parse_args(argv)
    repo = Path(repo)
    signers = Path(signers) if signers else repo / trust.ALLOWED_SIGNERS_FILE
    try:
        m, raw, rel = prepare(repo, a.restore_id, a.archive_sha, a.source_db_sha, principal)
        print("\nYou are about to approve this restore, with your signature:\n" + summary(m, rel))
        print("\nAll pre-checks passed.  A signature says WHO approved, not that the content is right: read the items before you sign.")
        if a.check:
            print("(--check: nothing was signed.)")
            return 0
        key = Path(a.key)
        if not key.is_file() or key.suffix != ".pub":
            raise Stop(f"--key must be the path of your PUBLIC key file (.pub); '{key}' is not.")
        words = f"SIGN {m['restore_id']}"
        if ask(f"\nTo sign, type exactly: {words}\n> ").strip() != words:
            raise Stop("not confirmed. Nothing was signed.")
        print("Signing... (git/ssh will ask for YOUR passphrase.)")
        r = subprocess.run(["git", "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "commit", "--amend", "--no-edit", "-S"], cwd=repo)
        if r.returncode != 0:
            raise Stop("signing failed (wrong passphrase or no ssh-keygen?). The commit is unchanged.")
        head = git(repo, "rev-parse", "HEAD")
        ref = am.approval_ref(raw, head)
        am.verify_approval(repo, ref, manifest_path=rel, allowed_signers=signers, trusted_fingerprint=fingerprint,
                           expect={"restore_id": m["restore_id"], "archive_sha256": a.archive_sha, "source_db_sha256": a.source_db_sha})
        print(f"\nSigned and verified.\n  approval_ref: {ref}\nNext (you do this): git push --force-with-lease origin <this branch>")
        return 0
    except Stop as exc:
        print(f"\nSTOP: {exc}")
        return 2
    except am.ApprovalError as exc:
        print(f"\nThe signed commit does NOT verify: {exc.code}: {exc}\nDo not push it. Tell Claude.")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
