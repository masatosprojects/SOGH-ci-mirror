"""g2 full original-source check on the pinned real v06 file (read-only): every stored page and every proof quote against the ORIGINAL PDFs.
SELF_TEST (author Claude). Output JSON on stdout. Nothing is written to the database or the PDFs."""
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF
import pypdf

sys.stdout.reconfigure(encoding="utf-8")
if len(sys.argv) != 3:
    sys.exit("usage: g2_full_source_check.py <pinned-v06-readonly.sqlite> <folder holding the original PDFs named <sha256>.pdf>")
DB = sys.argv[1]
ROOT = Path(sys.argv[2])
FILES = {}
c0 = sqlite3.connect("file:" + DB.replace("\\", "/") + "?mode=ro", uri=True)
for (h,) in c0.execute("select sha256 from source_documents"):
    FILES[h] = ROOT / (h + ".pdf")
c0.close()


def norm(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or ""))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


db_hash_before = sha(Path(DB))
c = sqlite3.connect("file:" + DB.replace("\\", "/") + "?mode=ro", uri=True)
out = {"db_sha256": db_hash_before, "sources": {}, "facts": {}}
ext = {}
for h, f in FILES.items():
    ok_hash = f.exists() and sha(f) == h
    r = {"file_exists": f.exists(), "file_sha256_matches_id": ok_hash}
    if ok_hash:
        fz = [norm(p.get_text()) for p in fitz.open(f)]
        pr = [norm(p.extract_text() or "") for p in pypdf.PdfReader(str(f)).pages]
        ext[h] = (fz, pr)
        stored = {pg: txt for pg, txt in c.execute("select page,text from source_pages where source_sha256=?", (h,))}
        stored_hash_ok = all(hashlib.sha256(t.encode("utf-8")).hexdigest() == th for (pg, t, th) in c.execute("select page,text,text_sha256 from source_pages where source_sha256=?", (h,)))
        r.update({"pages_in_pdf": len(fz), "pages_in_db": len(stored),
                  "db_pages_text_sha_ok": stored_hash_ok,
                  "db_page_equals_pymupdf": sum(1 for p, t in stored.items() if p - 1 < len(fz) and norm(t) == fz[p - 1]),
                  "db_page_equals_pypdf": sum(1 for p, t in stored.items() if p - 1 < len(pr) and norm(t) == pr[p - 1]),
                  "db_page_equals_either": sum(1 for p, t in stored.items() if p - 1 < len(fz) and (norm(t) == fz[p - 1] or norm(t) == pr[p - 1]))})
    out["sources"][h[:8]] = r

tot = {"facts": 0, "proofs": 0, "proof_in_pymupdf_page": 0, "proof_in_pypdf_page": 0, "proof_in_either": 0, "proof_in_stored_page": 0}
bad = []
for ev, sha_, rec in c.execute("select evidence_id,source_sha256,record_json from facts"):
    tot["facts"] += 1
    for p in json.loads(rec).get("proofs", []):
        tot["proofs"] += 1
        q, pg = norm(p.get("quote", "")), p.get("page")
        stored = c.execute("select text from source_pages where source_sha256=? and page=?", (sha_, pg)).fetchone()
        in_stored = bool(stored and q and q in norm(stored[0]))
        tot["proof_in_stored_page"] += in_stored
        a = b = False
        if sha_ in ext and isinstance(pg, int) and 1 <= pg <= len(ext[sha_][0]):
            a = q in ext[sha_][0][pg - 1]
            b = q in ext[sha_][1][pg - 1]
        tot["proof_in_pymupdf_page"] += a
        tot["proof_in_pypdf_page"] += b
        tot["proof_in_either"] += (a or b)
        if not (a or b):
            bad.append({"evidence_id": ev, "page": pg, "quote_head": q[:30], "in_stored": in_stored})
out["facts"] = tot
out["proofs_not_found_in_the_original_pdf"] = bad
out["db_sha256_after"] = sha(Path(DB))
out["db_unchanged"] = out["db_sha256_after"] == db_hash_before
print(json.dumps(out, ensure_ascii=False, indent=1))
