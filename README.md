# SOGH CI mirror (public, sanitized)

Read-only mirror of the code and tests of the private project repository, published only so that
GitHub Actions can run the full test suite on free public-repo minutes.
Not the source of truth: development happens in the private repo.

Excluded: strategy/business documents, agent instructions, runbooks, the approval signer file
(two tests that pin it, `tests/test_approval_trust.py`, are deselected here), local paths and usernames
(replaced by `USER`). No real applicant data, credentials or production databases are included.
