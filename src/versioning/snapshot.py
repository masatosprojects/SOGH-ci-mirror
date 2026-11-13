"""A SourceSnapshot is one edition of one official document: where it came
from, when, its sha256, and the text of each page.

Page text is a full extraction of the original and may be copyrighted: keep
snapshot files OUT of git (they are ignored by .gitignore) and only commit
URLs, hashes and the short quotes that evidence records already carry.

CLI (needs pymupdf; everything else in this package does not):
    python -m src.versioning.snapshot <file.pdf> --source-id <id> --url <url> \
        --retrieved-at 2026-11-01 --out snapshots/<id>-<sha8>.snapshot.json
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def normalize(text: str) -> str:
    """NFKC with all whitespace removed: PDF extraction scatters spaces and
    line breaks, so comparisons must not depend on them."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def source_hash(record: dict[str, Any]) -> str | None:
    """The edition a piece of evidence was taken from: the PDF's sha256, or — for an HTML
    notice, which has no PDF — the sha256 of the page body (`source_sha256`)."""
    return record.get("source_pdf_sha256") or record.get("source_sha256") or None


@dataclasses.dataclass
class SourceSnapshot:
    source_id: str  # stable id of the document across editions, e.g. "tsukuba-klis-ac-2027"
    url: str
    sha256: str  # of the original file
    retrieved_at: str  # ISO date
    pages: list[str]  # page 1 is pages[0]
    supersedes: list[str] = dataclasses.field(default_factory=list)  # sha256 values of earlier editions this replaces
    edition_note: str | None = None  # e.g. "訂正版", free text
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def normalized_pages(self) -> list[str]:
        return [normalize(p) for p in self.pages]


class SnapshotError(ValueError):
    pass


def snapshot_from_dict(data: dict[str, Any]) -> SourceSnapshot:
    missing = [k for k in ("source_id", "url", "sha256", "retrieved_at", "pages") if k not in data]
    if missing:
        raise SnapshotError(f"snapshot is missing {missing}")
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise SnapshotError(f"unsupported schema_version {data.get('schema_version')!r} (expected {SCHEMA_VERSION})")
    if not isinstance(data["pages"], list) or not all(isinstance(p, str) for p in data["pages"]):
        raise SnapshotError("pages must be a list of strings")
    if not (isinstance(data["sha256"], str) and len(data["sha256"]) == 64):
        raise SnapshotError("sha256 must be a 64-hex string")
    try:
        datetime.date.fromisoformat(data["retrieved_at"])
    except ValueError as exc:
        raise SnapshotError(f"retrieved_at is not an ISO date: {data['retrieved_at']!r}") from exc
    return SourceSnapshot(
        source_id=data["source_id"], url=data["url"], sha256=data["sha256"], retrieved_at=data["retrieved_at"],
        pages=list(data["pages"]), supersedes=list(data.get("supersedes", [])), edition_note=data.get("edition_note"),
    )


def load_snapshot(path: Path) -> SourceSnapshot:
    return snapshot_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_snapshot(snapshot: SourceSnapshot, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def snapshot_from_pdf(pdf_path: Path, source_id: str, url: str, retrieved_at: str,
                      supersedes: list[str] | None = None, edition_note: str | None = None) -> SourceSnapshot:
    try:
        import pymupdf  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without the optional dependency
        raise SnapshotError("reading a PDF needs pymupdf (pip install pymupdf)") from exc
    data = Path(pdf_path).read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = [p.get_text() for p in doc]
    return SourceSnapshot(source_id=source_id, url=url, sha256=hashlib.sha256(data).hexdigest(),
                          retrieved_at=retrieved_at, pages=pages, supersedes=supersedes or [], edition_note=edition_note)


def snapshot_from_evidence(evidence: dict[str, dict[str, Any]], sha256: str, source_id: str,
                           retrieved_at: str, url: str | None = None) -> SourceSnapshot:
    """A *minimal* snapshot rebuilt from the quotes that evidence records carry:
    page N holds the quotes cited on page N. It is what the repository can know
    without the original PDF — enough to ask "does every saved quote still hold
    at its page?", not to diff whole documents."""
    by_page: dict[int, list[str]] = {}
    source_url = url
    for record in evidence.values():
        if source_hash(record) != sha256:
            continue
        source_url = source_url or record.get("source_url")
        for proof in record.get("proofs", []):
            by_page.setdefault(int(proof["page"]), []).append(proof["quote"])
    if not by_page:
        raise SnapshotError(f"no evidence cites sha256 {sha256[:12]}")
    pages = ["\n".join(by_page.get(n, [])) for n in range(1, max(by_page) + 1)]
    return SourceSnapshot(source_id=source_id, url=source_url or "", sha256=sha256, retrieved_at=retrieved_at, pages=pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--retrieved-at", default=datetime.date.today().isoformat())
    parser.add_argument("--supersedes", action="append", default=[], help="sha256 of an earlier edition (repeatable)")
    parser.add_argument("--edition-note", default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    snap = snapshot_from_pdf(args.pdf, args.source_id, args.url, args.retrieved_at, args.supersedes, args.edition_note)
    save_snapshot(snap, args.out)
    print(json.dumps({"source_id": snap.source_id, "sha256": snap.sha256, "pages": len(snap.pages), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
