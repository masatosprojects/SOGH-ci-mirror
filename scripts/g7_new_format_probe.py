"""g7 new-format probe (SELF_TEST, author Claude; independent QA is Antigravity's).  READ-ONLY on every original; writes only inside --work-dir (a scratch directory).

Input (all LOCAL; no network):
  --pdf-dir   a scratch directory holding COPIES of the two originals (named by their SHA-256):
              58dd4540...pdf  the one-page official overview table (vertical Japanese text, merged pool cells: the "new format", the primary table of Work's PR #103)
              93b94cc8...pdf  the 100-page admission guide; physical page 8 holds a ruled table (horizontal text, merged cells) with the same faculty's rows (the secondary source)
  --bundle    the local `probe.json` of the g7-fixed folder: a table-cell bundle in the format of Work's PR #103 (rectangles, text SHA-256, values).  Read only.
  --v06       the pinned real v06 file.  It is only COPIED into --work-dir; the copy is migrated with additive_schema.apply(copy, confirm_disposable_copy=True).

What it does
  1. verifies the SHA-256 of the originals;
  2. extracts the table cells with THREE different extractors (PyMuPDF, pypdf, pdfplumber) and reports the per-table agreement (overview table 17 cells; guide table: every cell of the drawn grid);
  3. maps the cells through the bundle format (scripts/g7_bundle_adapter.py) into the quarantine staging tables of the disposable migrated copy: CANDIDATE rows only; the approval / seal path is NOT used;
  4. checks that the guards hold and that the schema (0013), the migration chain and the QA (audit) are unchanged by the run, and that the real v06 file's SHA-256 is unchanged.
Original text is held in memory only: the output has counts, hashes, positions and booleans, never a cell's text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import g7_bundle_adapter as A  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402
from src.db_contract import quarantine_staging as qs  # noqa: E402
from src.integration import db_audit as da  # noqa: E402
from src.integration.pdf_page_facts import page_facts  # noqa: E402

OVERVIEW = "58dd4540d8a3a932d5bf124f3e03fa3209361d2dae430b96d4fa5527a993105f"
GUIDE = "93b94cc803cc384f39c8776724f8a52bfc0a3b2bbd6dad928900677a246cb35a"
V06_SHA = "a8e48b5b16239368e9b5c05aad1dbeb692a657f28dab909bf3c99fff41539578"
GUIDE_PAGE = 8
# positions (not text) of the two total cells of the overview table, from the reviewed profile of PR #103 (read only)
TOTAL_RECTS = {"faculty_total": [355, 217, 383, 228], "general": [355, 740, 383, 753]}
TITLE_SCOPE = [24.0, 20.0, 562.0, 826.0]  # the scope used by the contract tests for this page
EXTRACTORS = ("pymupdf", "pypdf", "pdfplumber")


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---- three extractors: each returns items (cx, cy, w, h, text) in PDF points, top-left origin ---------------------------------------------------------------------------------------
def items_pymupdf(path: Path, page_no: int):
    import fitz

    out = []
    with fitz.open(path) as doc:
        raw = doc[page_no - 1].get_text("rawdict")
        for b in raw["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        x0, y0, x1, y1 = ch["bbox"]
                        if ch["c"].strip():
                            out.append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, ch["c"]))
    return out


def items_pymupdf_words(path: Path, page_no: int):
    """Work's own method (PR #103): word boxes; used only to compare with the bundle's hashes the way Work derived them."""
    import fitz

    with fitz.open(path) as doc:
        return [tuple(w[:5]) for w in doc[page_no - 1].get_text("words")]


def items_pdfplumber(path: Path, page_no: int):
    import pdfplumber

    out = []
    with pdfplumber.open(path) as pdf:
        for ch in pdf.pages[page_no - 1].chars:
            if ch["text"].strip():
                out.append(((ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2, ch["x1"] - ch["x0"], ch["bottom"] - ch["top"], ch["text"]))
    return out


def items_pypdf(path: Path, page_no: int):
    """pypdf gives text fragments with their text/CTM matrices, not boxes: the item is the fragment ORIGIN (x, y), and the font size stands for its width/height."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    page = reader.pages[page_no - 1]
    height = float(page.mediabox.height)
    out = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        out.append((x, height - y, font_size, font_size, text, True))

    page.extract_text(visitor_text=visitor)
    return out


def _cluster_axis(vals_items, key, tol):
    groups = []
    for it in sorted(vals_items, key=key):
        if groups and abs(key(it) - groups[-1][0]) <= tol:
            groups[-1][1].append(it)
        else:
            groups.append([key(it), [it]])
    return [g[1] for g in groups]


def cell_text(items, rect, order, tol_pt=1.0):
    """Items whose centre (pypdf: origin) lies in the rectangle; ordered as the profile says; NFKC + whitespace removed (the normalisation of the bundle's text_sha256)."""
    x0, y0, x1, y1 = rect
    sel = [it for it in items if x0 - tol_pt <= it[0] <= x1 + tol_pt and y0 - tol_pt <= it[1] <= y1 + tol_pt]
    if not sel:
        return ""
    size = statistics.median(max(it[2], it[3]) for it in sel)
    if order == "vertical-rtl":
        cols = _cluster_axis(sel, lambda it: -it[0], 0.5 * size)
        seq = [it for col in cols for it in sorted(col, key=lambda it: it[1])]
    else:
        lines = _cluster_axis(sel, lambda it: it[1], 0.5 * size)
        seq = [it for ln in lines for it in sorted(ln, key=lambda it: it[0])]
    return A.norm("".join(it[4] for it in seq))


def words_cell_text(words, rect, order):
    """The exact cell() of PR #103's layout_probe (word centre inside the rectangle; the box must lie inside, else the cell is clipped = refused)."""
    x0, y0, x1, y1 = rect
    sel = []
    for a, b, c, d, t in words:
        if x0 <= (a + c) / 2 < x1 and y0 <= (b + d) / 2 < y1:
            if not (x0 <= a and y0 <= b and c <= x1 and d <= y1):
                return None  # clipped
            sel.append((a, b, c, d, t))
    if not sel:
        return ""
    sel.sort(key=(lambda w: (-round(w[0], 1), w[1])) if order == "vertical-rtl" else (lambda w: (round(w[1], 1), w[0])))
    return A.norm("".join(w[4] for w in sel))


def _fragment_glyphs(items, rect, tol_pt=1.0):
    x0, y0, x1, y1 = rect
    return sum(len(it[4].replace(" ", "")) for it in items if x0 - tol_pt <= it[0] <= x1 + tol_pt and y0 - tol_pt <= it[1] <= y1 + tol_pt)


def sh(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# ---- table 1: the overview table ------------------------------------------------------------------------------------------------------------------------------------------------------
def overview_cells(bundle):
    """[(key, rect, order)] for the 15 bundle cells, the 2 totals and the title anchor."""
    cells = []
    for r in bundle["rows"]:
        for role in A.ROLES:
            cells.append(((r["row_id"], role), r[role]["rect"], "horizontal" if role == "count" else "vertical-rtl"))
    cells.append((("tot", "faculty_total"), TOTAL_RECTS["faculty_total"], "horizontal"))
    cells.append((("tot", "general"), TOTAL_RECTS["general"], "horizontal"))
    cells.append((("title", "anchor"), bundle["year_anchor"]["rect"], "horizontal"))
    return cells


def agree_stats(per_extractor: dict, keys):
    out = {}
    names = list(per_extractor)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            same = sum(1 for k in keys if per_extractor[a][k] == per_extractor[b][k])
            out[f"{a}~{b}"] = {"agree": same, "of": len(keys)}
    out["all_three_equal"] = {"agree": sum(1 for k in keys if len({per_extractor[n][k] for n in names}) == 1), "of": len(keys)}
    return out


# ---- table 2: the ruled table of the guide (page 8) -----------------------------------------------------------------------------------------------------------------------------------
def guide_table(path: Path):
    import fitz
    import pdfplumber

    with fitz.open(path) as doc:
        tabs = doc[GUIDE_PAGE - 1].find_tables().tables
        grid = {"tables": len(tabs), "bbox": [round(v, 1) for v in tabs[0].bbox], "rows": tabs[0].row_count, "cols": tabs[0].col_count, "cells": [list(c) for c in tabs[0].cells if c]}
    with pdfplumber.open(path) as pdf:
        ptabs = pdf.pages[GUIDE_PAGE - 1].find_tables()
        grid["pdfplumber_tables"] = len(ptabs)
        grid["pdfplumber_rows"] = len(ptabs[0].rows) if ptabs else None
        grid["pdfplumber_cells"] = len([c for c in ptabs[0].cells]) if ptabs else None
    return grid


# ---- disposable database --------------------------------------------------------------------------------------------------------------------------------------------------------------
def schema_fingerprint(db):
    rows = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    return sh(json.dumps(rows, ensure_ascii=False, sort_keys=True)), len(rows)


def table_counts(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")]
    return {n: db.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}


def audit_status(path: Path):
    r = da.audit(path, None, "copied_real_db")
    inv = r["invariants"]
    return {k: v["status"] for k, v in sorted(inv.items())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--v06", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rep: dict = {"labels": ["SELF_TEST", "author_claude", "not_independent_qa", "one_university_one_document_family"]}

    ov, gd = a.pdf_dir / f"{OVERVIEW}.pdf", a.pdf_dir / f"{GUIDE}.pdf"
    assert sha_file(ov) == OVERVIEW and sha_file(gd) == GUIDE, "originals are not the pinned bytes"
    rep["originals"] = {"overview_sha256": OVERVIEW, "overview_bytes": ov.stat().st_size, "guide_sha256": GUIDE, "guide_bytes": gd.stat().st_size, "bytes_match": True}
    bundle_doc = json.loads(a.bundle.read_text(encoding="utf-8"))
    bundle = bundle_doc["entry"]
    assert bundle["source_sha256"] == OVERVIEW

    # 1. extraction, table 1 (overview)
    cells = overview_cells(bundle)
    ext = {"pymupdf": items_pymupdf(ov, 1), "pypdf": items_pypdf(ov, 1), "pdfplumber": items_pdfplumber(ov, 1)}
    texts_by = {n: {k: cell_text(items, rect, order) for k, rect, order in cells} for n, items in ext.items()}
    keys = [k for k, _r, _o in cells]
    words = items_pymupdf_words(ov, 1)
    work_texts = {k: words_cell_text(words, rect, order) for k, rect, order in cells}
    bundle_hash = {(r["row_id"], role): r[role]["text_sha256"] for r in bundle["rows"] for role in A.ROLES}
    cell_keys = [k for k in keys if k[0] not in ("tot", "title")]
    t1 = {
        "page": 1,
        "cells_compared": len(keys),
        "bundle_cells": len(cell_keys),
        "items_seen": {n: len(v) for n, v in ext.items()},
        "agreement_text": agree_stats(texts_by, keys),
        "empty_cells": {n: sum(1 for k in keys if not texts_by[n][k]) for n in texts_by},
        "equals_bundle_text_sha256": {n: {"agree": sum(1 for k in cell_keys if sh(texts_by[n][k]) == bundle_hash[k]), "of": len(cell_keys)} for n in texts_by},
        "work_word_method_equals_bundle_text_sha256": {"agree": sum(1 for k in cell_keys if work_texts[k] is not None and sh(work_texts[k]) == bundle_hash[k]), "of": len(cell_keys)},
        "pypdf_glyph_count_vs_pymupdf_char_count": {"agree": sum(1 for k, rect, _o in cells if _fragment_glyphs(ext["pypdf"], rect) == len(texts_by["pymupdf"][k])), "of": len(cells),
                                                    "note": "pypdf cannot decode this document's fonts (Type0 Identity-H/V without ToUnicode): its text is glyph codes, so only the NUMBER of glyphs in each cell can be compared"},
        "totals_numeric": {n: [texts_by[n][("tot", "faculty_total")], texts_by[n][("tot", "general")]] for n in texts_by},
        "title_anchor_equals_bundle_anchor": {n: A.norm(texts_by[n][("title", "anchor")]) == A.norm(bundle["year_anchor"]["text"]) for n in texts_by},
        "disagreeing_cells": {f"{x}~{y}": [f"{k[0]}/{k[1]}" for k in keys if texts_by[x][k] != texts_by[y][k]] for i, x in enumerate(EXTRACTORS) for y in EXTRACTORS[i + 1:]},
    }
    rep["table_overview"] = t1

    # table 2 (guide page 8): the drawn grid is shared (PyMuPDF find_tables); the TEXT in each cell comes from each extractor independently
    grid = guide_table(gd)
    gitems = {"pymupdf": items_pymupdf(gd, GUIDE_PAGE), "pypdf": items_pypdf(gd, GUIDE_PAGE), "pdfplumber": items_pdfplumber(gd, GUIDE_PAGE)}
    gcells = grid.pop("cells")
    gtexts = {n: [cell_text(items, tuple(c), "horizontal", tol_pt=0.0) for c in gcells] for n, items in gitems.items()}
    idx = list(range(len(gcells)))
    nonempty = [i for i in idx if any(gtexts[n][i] for n in gtexts)]
    grid_stats = agree_stats({n: dict(enumerate(v)) for n, v in gtexts.items()}, idx)
    nonempty_stats = agree_stats({n: dict(enumerate(v)) for n, v in gtexts.items()}, nonempty)
    t2 = {"page": GUIDE_PAGE, "grid": grid, "grid_cells": len(gcells), "grid_cells_with_text_in_any_extractor": len(nonempty), "agreement_all_cells": grid_stats, "agreement_nonempty_cells": nonempty_stats,
          "grid_agreement_pymupdf_vs_pdfplumber": {"tables_equal": grid["tables"] == grid["pdfplumber_tables"], "cells": [len(gcells), grid["pdfplumber_cells"]]},
          "note": "the guide table's grid comes from PyMuPDF find_tables (shared); pypdf has no table detection. The count in a cell is the digit(s)+人; the guide uses 人, the overview 名."}
    # the faculty rows: the count the guide table gives next to each method label must equal the overview's count, per extractor (the guide writes the label in brackets and the unit as 人)
    import re

    cross = {}
    for n in gtexts:
        per_row = []
        for r_ in bundle["rows"]:
            label = texts_by["pymupdf"][(r_["row_id"], "label")]
            lab_idx = [i for i, t in enumerate(gtexts[n]) if A.norm(t).strip("()") == label]
            counts = []
            for i in lab_idx:
                ly0, ly1 = gcells[i][1], gcells[i][3]
                for j, c in enumerate(gcells):
                    m = re.fullmatch(r"(\d+)人", gtexts[n][j])
                    if m and min(c[3], ly1) - max(c[1], ly0) > 2:
                        counts.append(int(m.group(1)))
            per_row.append(counts == [int("".join(ch for ch in texts_by["pymupdf"][(r_["row_id"], "count")] if ch.isdigit()))])
        cross[n] = {"rows_equal": sum(per_row), "of": len(per_row)}
    t2["cross_format_counts_equal_to_overview"] = cross
    rep["table_guide_page8"] = t2

    # 2. the bundle -> product: per extractor, with the SAME bundle (Work's rectangles, hashes, values)
    entry = json.loads(json.dumps(bundle))
    entry["title_scope"], entry["expected_table_clusters"] = TITLE_SCOPE, 1
    facts = page_facts(ov.read_bytes(), 1, TITLE_SCOPE, entry["year_anchor"]["rect"])
    geometry = {"page_size": (595.22, 842.0), "rulings": bundle_doc["rulings_from_saved_pdf_vectors"], "page_facts": facts}
    title_pin = A.text_sha(bundle["year_anchor"]["text"])
    pins = A.Pins(page=1, title_sha256=title_pin, cell_sha256=dict(bundle_hash))
    results = {}
    for n in EXTRACTORS:
        e = json.loads(json.dumps(entry))
        e["year_anchor"]["text"] = texts_by[n][("title", "anchor")]
        tx = {k: texts_by[n][k] for k in bundle_hash}
        # the value of each row is what THIS extractor read in the count cell (digits), never Work's number
        for r in e["rows"]:
            ct = tx[(r["row_id"], "count")]
            r["value"] = int("".join(c for c in ct if c.isdigit()) or 0)
        out = A.evaluate_bundle(e, tx, pins, A.Claim(), geometry=geometry, approved=frozenset({bundle["fact_key"]}))
        results[n] = {"adapter": [(c, v) for c, v in out["adapter"]], "geometry_errors": [f["code"] for f in out["geometry"] if f["level"] == "error"],
                      "geometry_warnings": [f["code"] for f in out["geometry"] if f["level"] == "warning"], "geometry_info": [f["code"] for f in out["geometry"] if f["level"] == "info"],
                      "rows": {k: v.code for k, v in out["rows"].items()}, "decision": out["decision"], "_values": [r["value"] for r in e["rows"]]}
    rep["bundle_through_product"] = {n: {k: v for k, v in r.items() if k != "_values"} for n, r in results.items()}
    rep["values_read_per_extractor"] = {n: r["_values"] for n, r in results.items()}

    # 3. disposable migrated copy; candidate rows only
    work = a.work_dir
    work.mkdir(parents=True, exist_ok=True)
    before_sha = sha_file(a.v06)
    assert before_sha == V06_SHA, "the pinned v06 is not the pinned bytes"
    copy = work / "v06-disposable-copy.sqlite"
    if copy.exists():
        copy.unlink()
    shutil.copyfile(a.v06, copy)
    assert sha_file(copy) == V06_SHA
    pre_hist_len = 0
    r = ad.apply(copy, confirm_disposable_copy=True)
    rep["migration"] = {"applied": r["applied"], "rolled_back": r["rolled_back"], "blocked": r.get("blocked")}
    with closing(sqlite3.connect(copy)) as db:
        hist0 = ad.history(db)
        fp0, nobj0 = schema_fingerprint(db)
        counts0 = table_counts(db)
        problems0 = ad.verify_history(db) + ad.verify_schema_state(db)
    audit0 = audit_status(copy)
    copy_sha_migrated = sha_file(copy)
    rep["chain_before"] = {"migrations_in_code": len(ad.MIGRATIONS), "history_rows": len(hist0), "history_sha256": sh(json.dumps(hist0, sort_keys=True)), "schema_objects": nobj0, "schema_fingerprint": fp0,
                           "history_and_schema_problems": problems0, "audit_failures": [k for k, v in audit0.items() if v == "fail"]}
    assert not r["rolled_back"] and not problems0

    staged, refused = [], []
    candidate_rows = []
    with closing(sqlite3.connect(copy)) as db:
        qs.register_quarantine_connection_guards(db)
        n = "pymupdf"
        # candidates only from rows on which PyMuPDF and pdfplumber (the two that can decode the fonts) AND the bundle's hashes agree
        agreed = {k for k in cell_keys if texts_by["pymupdf"][k] == texts_by["pdfplumber"][k] and sh(texts_by["pymupdf"][k]) == bundle_hash[k]}  # pypdf cannot decode this document (see table_overview)
        e = json.loads(json.dumps(entry))
        tx = {k: texts_by[n][k] for k in bundle_hash}
        for r_ in e["rows"]:
            r_["value"] = int("".join(c for c in tx[(r_["row_id"], "count")] if c.isdigit()))
        e["year_anchor"]["text"] = texts_by[n][("title", "anchor")]
        out = A.evaluate_bundle(e, tx, pins, A.Claim(), geometry=geometry, approved=frozenset({bundle["fact_key"]}))
        for r_ in e["rows"]:
            rid = r_["row_id"]
            ok_cells = all((rid, role) in agreed for role in A.ROLES)
            res = out["rows"][rid]
            if ok_cells and res.decision == "ACCEPT" and not [f for f in out["geometry"] if f["level"] == "error"]:
                pl = A.candidate_payload(e, tx, rid, res)
                sid = qs.stage_candidate(db, f"g7probe-{rid}", f"src-{OVERVIEW[:12]}", "PDF_TABLE_CELL", pl["extracted_key"], pl["extracted_value"], staged_by="g7_new_format_probe")
                staged.append(sid)
            else:
                refused.append(rid)
        rows = db.execute("SELECT staging_id, quarantine_status, review_status, approved_by, approval_token, length(extracted_value) FROM quarantine_staging_candidates ORDER BY staging_id").fetchall()
        candidate_rows = [list(x) for x in rows]
        # 4. guards: every attempt must fail
        guards = {}

        def attempt(name, fn, exc):
            try:
                fn()
                guards[name] = "NOT_BLOCKED"
            except exc as ex:
                guards[name] = "blocked:" + type(ex).__name__
            except Exception as ex:  # a different error is not the guard
                guards[name] = "OTHER:" + type(ex).__name__

        sid0 = staged[0]
        attempt("promote_without_approval", lambda: qs.promote_candidate(db, sid0, fact_id="f-probe"), sqlite3.IntegrityError)
        attempt("approve_by_unregistered_reviewer", lambda: qs.review_candidate(db, sid0, decision="APPROVED", reviewer="someone"), PermissionError)
        attempt("approve_by_the_stager", lambda: qs.review_candidate(db, sid0, decision="APPROVED", reviewer="g7_new_format_probe"), PermissionError)
        attempt("direct_update_to_approved", lambda: db.execute("UPDATE quarantine_staging_candidates SET review_status='APPROVED', approved_by='x', approval_token='0123456789abcdef0123' WHERE staging_id=?", (sid0,)), sqlite3.DatabaseError)
        attempt("direct_update_to_promoted", lambda: db.execute("UPDATE quarantine_staging_candidates SET quarantine_status='PROMOTED' WHERE staging_id=?", (sid0,)), sqlite3.DatabaseError)
        attempt("pre_approved_insert", lambda: db.execute("INSERT INTO quarantine_staging_candidates(staging_id, source_id, format_type, extracted_key, extracted_value, quarantine_status, review_status, approved_by, approval_token, sha256_hash) VALUES('x','s','f','k','v','QUARANTINED','APPROVED','a','0123456789abcdef0123','h')"), sqlite3.DatabaseError)
        attempt("delete_a_candidate", lambda: db.execute("DELETE FROM quarantine_staging_candidates WHERE staging_id=?", (sid0,)), sqlite3.DatabaseError)
        attempt("payload_rewrite", lambda: db.execute("UPDATE quarantine_staging_candidates SET extracted_value='{}' WHERE staging_id=?", (sid0,)), sqlite3.DatabaseError)
        attempt("canonical_insert_around_quarantine", lambda: db.execute("INSERT INTO canonical_facts_staging_target(fact_id, staging_id, key, value, promoted_at) VALUES('f','%s','k','v','t')" % sid0), sqlite3.DatabaseError)
        attempt("conflicting_resubmission", lambda: qs.stage_candidate(db, sid0, f"src-{OVERVIEW[:12]}", "PDF_TABLE_CELL", "k", "different", staged_by="g7_new_format_probe"), sqlite3.IntegrityError)
        db.rollback()
        seals = db.execute("SELECT count(*) FROM _quarantine_approval_seals").fetchone()[0]
        canon = db.execute("SELECT count(*) FROM canonical_facts_staging_target").fetchone()[0]
        db.commit()
    rep["staging"] = {"candidate_rows": len(candidate_rows), "staged": len(staged), "not_staged": refused, "states": sorted({(x[1], x[2]) for x in candidate_rows}), "approved_by_or_token_set": sum(1 for x in candidate_rows if x[3] or x[4]),
                      "approval_seals": seals, "canonical_target_rows": canon, "approval_path_used": bool(qs._AUTHORIZED_SEAL_GRANTS), "authorized_reviewers_registered": sorted(qs._load_configured_reviewers()), "guards": guards,
                      "guards_all_blocked": all(v.startswith("blocked") for v in guards.values())}

    # 5. the chain / schema / QA are unchanged by the run
    with closing(sqlite3.connect(copy)) as db:
        hist1 = ad.history(db)
        fp1, nobj1 = schema_fingerprint(db)
        counts1 = table_counts(db)
        problems1 = ad.verify_history(db) + ad.verify_schema_state(db)
    audit1 = audit_status(copy)
    changed_tables = {t: [counts0.get(t), counts1[t]] for t in counts1 if counts0.get(t) != counts1[t]}
    git_src = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", "origin/master", "--", "src", "tests/db_support.py"], capture_output=True, text=True).stdout.strip()
    rep["unchanged"] = {"history_identical": hist0 == hist1, "history_rows": [len(hist0), len(hist1)], "schema_fingerprint_identical": fp0 == fp1, "schema_objects": [nobj0, nobj1],
                        "history_and_schema_problems_after": problems1, "audit_statuses_identical": audit0 == audit1, "audit_failures_after": [k for k, v in audit1.items() if v == "fail"],
                        "tables_with_changed_row_count": changed_tables, "git_diff_src_vs_origin_master_is_empty": git_src == "", "copy_sha256_after_migration": copy_sha_migrated}
    after_sha = sha_file(a.v06)
    rep["real_v06"] = {"sha256_before": before_sha, "sha256_after": after_sha, "unchanged": before_sha == after_sha == V06_SHA}
    a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
