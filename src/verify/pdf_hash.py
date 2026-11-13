"""PDF hash verification — detects a cited official PDF having changed
(or not matching what was actually retrieved) since an evidence record
was created.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path


@dataclasses.dataclass
class PdfHashResult:
    ok: bool
    actual_sha256: str
    expected_sha256: str | None
    reason: str | None = None


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pdf_hash(pdf_path: Path, expected_sha256: str | None) -> PdfHashResult:
    actual = sha256_of_file(pdf_path)
    if expected_sha256 is None:
        return PdfHashResult(False, actual, None, "no expected hash recorded for this evidence — cannot confirm it is unchanged")
    if actual.lower() != expected_sha256.lower():
        return PdfHashResult(False, actual, expected_sha256, "PDF content hash does not match the hash recorded at retrieval time")
    return PdfHashResult(True, actual, expected_sha256)
