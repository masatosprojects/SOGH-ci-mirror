"""The pinned trust root for restore approvals (see docs/RESTORE_APPROVAL_MANIFEST_2026-11-07.md).

The USER made the key pair on their own computer on 2026-11-07 (ed25519, protected by a passphrase: the user saw the passphrase prompt on `ssh-keygen -y`) and gave Claude only the PUBLIC key and
its fingerprint in the chat.  Claude recomputed the fingerprint from the public key and it matched.  Claude never held the private key and has signed nothing.

Whoever can change these constants can approve a restore.  They change only by a pull request that the user merges; `verify_approval` receives the fingerprint as an argument and never reads
it from the file it is checking.  This module is a PROPOSAL until the user merges it: it starts no signing practice, writes to no database and approves no restore.
"""
APPROVER_PRINCIPAL = "approver-1"  # the signer is the approver; the identifier has no space because ssh reads the allowed-signers file field by field
APPROVER_FINGERPRINT = "SHA256:ACP/j/RQUvjKDtXzMhZx85wegj42Tf6Ds1OpVgcOyDY"
ALLOWED_SIGNERS_FILE = "approvals/allowed_signers"
