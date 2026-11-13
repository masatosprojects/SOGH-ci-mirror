"""The pinned approver (src/db_contract/approval_trust.py) is internally consistent: the allowed-signers file holds exactly one key, for the pinned principal, and that key's fingerprint IS the pinned one.
Only PUBLIC material is used.  Nothing here signs or approves anything."""
import re
import subprocess
from pathlib import Path

from src.db_contract import approval_manifest as am
from src.db_contract import approval_trust as trust

REPO = Path(__file__).resolve().parents[1]


def entries():
    lines = [l for l in (REPO / trust.ALLOWED_SIGNERS_FILE).read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return lines


def test_the_pinned_fingerprint_and_principal_are_well_formed():
    assert am.FINGERPRINT.match(trust.APPROVER_FINGERPRINT)
    assert re.match(r"^[A-Za-z0-9._-]+$", trust.APPROVER_PRINCIPAL)


def test_the_allowed_signers_file_has_exactly_one_key_for_the_pinned_principal_limited_to_git_signatures():
    lines = entries()
    assert len(lines) == 1
    m = re.match(r'^(\S+) namespaces="git" (ssh-ed25519) (AAAA[A-Za-z0-9+/=]+)(?: \S+)?$', lines[0])
    assert m, lines[0]
    assert m.group(1) == trust.APPROVER_PRINCIPAL


def test_the_key_in_the_allowed_signers_file_has_the_pinned_fingerprint(tmp_path):
    line = entries()[0]
    key = line.split(' namespaces="git" ', 1)[1]
    pub = tmp_path / "k.pub"
    pub.write_text(key + "\n", encoding="utf-8")
    out = subprocess.run(["ssh-keygen", "-lf", str(pub)], capture_output=True, text=True, check=True).stdout
    assert re.search(r"(SHA256:\S+)", out).group(1) == trust.APPROVER_FINGERPRINT
