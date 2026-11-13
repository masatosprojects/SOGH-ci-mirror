"""Export the HASH-ONLY inputs for an independent re-run of the g2 full original-source check (no DB, no original text leaves the machine).

Reads the pinned real v06 file READ-ONLY and writes JSON with, per source: sha256, official URL, page count, SHA-256 of each page's NORMALIZED text;
per proof: evidence_id, source sha256, page, length of the normalized quote and its SHA-256. A checker who obtains the same PDF from the official URL
(and verifies its SHA-256 equals the source id) can recompute the page hashes and find each quote by a sliding-window hash over the page text,
without ever receiving the database or the quote text.

normalize(t) = remove all whitespace after Unicode NFKC.   Usage: python scripts/g2_source_check_inputs.py <pinned-v06-readonly.sqlite> > inputs.json
"""
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata


def norm(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or ""))


def h(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def main(db: str) -> dict:
    c = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    out = {"schema": "g2-source-check-inputs/1", "normalize": "NFKC then remove all whitespace; SHA-256 of the UTF-8 bytes", "sources": {}, "proofs": []}
    for sha, url in c.execute("select sha256,url from source_documents order by sha256"):
        pages = [(pg, h(norm(t))) for pg, t in c.execute("select page,text from source_pages where source_sha256=? order by page", (sha,))]
        out["sources"][sha] = {"url": url, "pages": len(pages), "page_norm_sha256": {str(pg): ph for pg, ph in pages}}
    for ev, sha, rec in c.execute("select evidence_id,source_sha256,record_json from facts order by evidence_id"):
        for i, p in enumerate(json.loads(rec).get("proofs", [])):
            q = norm(p.get("quote", ""))
            out["proofs"].append({"evidence_id": ev, "proof_index": i, "source_sha256": sha, "page": p.get("page"), "quote_norm_len": len(q), "quote_norm_sha256": h(q)})
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(main(sys.argv[1]), ensure_ascii=False, indent=1))
