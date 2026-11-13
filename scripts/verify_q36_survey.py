"""Verify that every cited test, code file, and database table in Q36_CANDIDATE_STATE_MACHINE_EXISTING_SURVEY_20261112.md exists on master.

Run:
    python scripts/verify_q36_survey.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "local-ai" / "Q36_CANDIDATE_STATE_MACHINE_EXISTING_SURVEY_20261112.md"


def main():
    if not DOC_PATH.is_file():
        print(f"ERROR: Document not found: {DOC_PATH}")
        sys.exit(1)

    text = DOC_PATH.read_text(encoding="utf-8")

    print(f"Verifying citations in {DOC_PATH.name} against master...\n")
    failures = 0

    # 1. Verify test citations `path/to/file.py::test_name`
    test_citations = re.findall(r"`([a-zA-Z0-9_\/.-]+\.py)::(test_[a-zA-Z0-9_]+)`", text)
    checked_tests = set()
    for file_rel, test_name in test_citations:
        key = f"{file_rel}::{test_name}"
        if key in checked_tests:
            continue
        checked_tests.add(key)

        file_path = REPO_ROOT / file_rel
        if not file_path.is_file():
            print(f"[FAIL: FILE MISSING] {file_rel}")
            failures += 1
            continue

        file_content = file_path.read_text(encoding="utf-8")
        pattern = rf"\bdef\s+{re.escape(test_name)}\b"
        if not re.search(pattern, file_content):
            print(f"[FAIL: TEST MISSING] {file_rel}::{test_name}")
            failures += 1
            continue

        print(f"[PASS: TEST] {file_rel}::{test_name}")

    # 2. Verify code files cited as backticks
    code_citations = re.findall(r"`([a-zA-Z0-9_\/.-]+\.(?:py|sql|patch))`", text)
    checked_files = set()
    for file_rel in code_citations:
        if file_rel in checked_files or "::" in file_rel:
            continue
        checked_files.add(file_rel)

        target_path = REPO_ROOT / file_rel
        if not target_path.is_file():
            alt_path = REPO_ROOT / "src" / "db_contract" / "migrations" / file_rel
            if alt_path.is_file():
                target_path = alt_path
            else:
                print(f"[FAIL: CODE FILE MISSING] {file_rel}")
                failures += 1
                continue

        print(f"[PASS: CODE/MIGRATION FILE] {file_rel}")

    # 3. Verify tables mentioned in migration files
    tables = [
        "source_document_series_editions",
        "quarantine_staging_candidates",
        "faq_unconfirmed_evidence",
        "alias_provenance_bundles",
        "_quarantine_approval_seals",
        "canonical_facts_staging_target",
    ]
    mig_dir = REPO_ROOT / "src" / "db_contract" / "migrations"
    for tbl in tables:
        found = False
        for sql_file in mig_dir.glob("*.sql"):
            if re.search(rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(tbl)}\b", sql_file.read_text(encoding="utf-8"), re.I):
                found = True
                print(f"[PASS: TABLE] {tbl} (in {sql_file.name})")
                break
        if not found:
            print(f"[FAIL: TABLE MISSING] {tbl}")
            failures += 1

    print(f"\nSummary: {len(checked_tests)} tests, {len(checked_files)} files, {len(tables)} tables verified.")
    print(f"Total Failures: {failures}")
    if failures > 0:
        sys.exit(1)
    else:
        print("ALL CITATIONS VERIFIED ON MASTER.")


if __name__ == "__main__":
    main()
