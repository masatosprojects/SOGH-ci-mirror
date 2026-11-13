"""Verify that every cited test path::name in SYNTHETIC_Q35_PIPELINE_COMPONENT_TEST_PLAN_20261112.md exists on master.

Run:
    python scripts/verify_scenario_mapping.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "local-ai" / "SYNTHETIC_Q35_PIPELINE_COMPONENT_TEST_PLAN_20261112.md"


def main():
    if not DOC_PATH.is_file():
        print(f"ERROR: Document not found: {DOC_PATH}")
        sys.exit(1)

    text = DOC_PATH.read_text(encoding="utf-8")
    
    # Extract backtick patterns of the form `path/to/file.py::test_name`
    citations = re.findall(r"`([a-zA-Z0-9_\/.-]+\.py)::(test_[a-zA-Z0-9_]+)`", text)
    if not citations:
        print("ERROR: No path::test_name citations found in document.")
        sys.exit(1)

    print(f"Verifying {len(citations)} test citations from {DOC_PATH.name}:\n")

    failures = 0
    checked = set()

    for file_rel, test_name in citations:
        key = f"{file_rel}::{test_name}"
        if key in checked:
            continue
        checked.add(key)

        file_path = REPO_ROOT / file_rel
        if not file_path.is_file():
            print(f"[FAIL: FILE MISSING] {file_rel}")
            failures += 1
            continue

        file_content = file_path.read_text(encoding="utf-8")
        # Check if def test_name exists in file
        pattern = rf"\bdef\s+{re.escape(test_name)}\b"
        if not re.search(pattern, file_content):
            print(f"[FAIL: TEST MISSING] {file_rel}::{test_name}")
            failures += 1
            continue

        print(f"[PASS] {file_rel}::{test_name}")

    print(f"\nSummary: {len(checked)} unique test citations checked. Failures: {failures}")
    if failures > 0:
        sys.exit(1)
    else:
        print("ALL CITED TESTS EXIST ON MASTER.")


if __name__ == "__main__":
    main()
