"""Independent check of ONE table-cell evidence entry (contract: docs/G7_TABLE_CELL_CONTRACT_V1_CANDIDATE.md, version table-cell-evidence-v1.1-candidate; v1.1 replaces the fixed title-to-table distance by a reviewed TITLE SCOPE, see the document).

Read only: it receives the entry (as a dict), the facts of the page it was read from (page size, the ruling lines Claude derived independently, the registry of approved fact keys) and returns findings.
`error` blocks the entry, `warning` needs a human decision, `info` is context. It never opens a file, a database or the network and does not decide what a cell MEANS.

Codes: E-SHAPE fields and types / E-HASH hash fields / E-PAGE every rectangle inside the page / E-ORDER reading order named / E-ROW label, pool and count rectangles bound to one row /
E-INSIDE every cell inside the table rectangle / E-YEAR the year anchor is a rectangle inside the reviewed title scope, above the table, whose text is what the page has there and names the admission year / E-YEARCONFLICT another year inside the scope / E-VALUE the numbers and their sums /
E-RULING (K-5) every rectangle lies inside the cell the drawn ruling lines make; a word-box overhang whose INK lies inside the ruled cell is information (`ink_extents`, v1.2) / E-FACTKEY the fact key is approved / E-SCOPE the scope fields that must not be confused, and the table lies inside the title scope and inside the drawn table / E-FACTS the independent page facts are missing / E-PIN the profile or the source bytes are not the reviewed pair.
"""
from __future__ import annotations

import re
import unicodedata

READING_ORDERS = ("column_rtl", "column_ltr", "row")
ROLES = ("label", "pool", "count")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOLERANCE = 3.0       # points: a rectangle edge that is this close to a ruling line is ON it
OVERSHOOT_ERROR = 10.0  # beyond this a rectangle that leaves its ruled cell is an error; between TOLERANCE and this it is a warning (the K-5 finding of PR #103 was 6 points)


def _rect_ok(r) -> bool:
    return isinstance(r, (list, tuple)) and len(r) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r) and r[0] < r[2] and r[1] < r[3]


def _inside(inner, outer, tol=0.0) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def _overlap_v(a, b) -> bool:
    return min(a[3], b[3]) - max(a[1], b[1]) > 0


def _flat(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def _years(text: str) -> set[int]:
    flat = _flat(text)
    return {int(y) for y in re.findall(r"(?<!\d)(20\d\d)", flat)} | {2018 + int(n) for n in re.findall(r"令和(\d{1,2})", flat)}


def check_entry(entry: dict, *, page_size: tuple[float, float], rulings: dict | None = None, approved_fact_keys: set[str] | frozenset[str] = frozenset(), page_facts: dict | None = None,
                reviewed_profiles: dict | None = None, ink_extents: dict | None = None) -> list[dict]:
    out: list[dict] = []

    def add(code, level, detail):
        out.append({"code": code, "level": level, "detail": detail})

    need = {"fact_key", "source_sha256", "page", "extractor_id", "profile_id", "profile_sha256", "reading_order", "table_rect", "year_anchor", "title_scope", "expected_table_clusters", "rows", "values"}
    if not isinstance(entry, dict) or set(entry) != need:
        add("E-SHAPE", "error", f"an entry is exactly {sorted(need)}")
        return out
    for k in ("source_sha256", "profile_sha256"):
        if not (isinstance(entry[k], str) and HEX64.match(entry[k])):
            add("E-HASH", "error", f"{k} must be 64 lowercase hex characters")
    if not (isinstance(entry["extractor_id"], str) and "/" in entry["extractor_id"]) or not (isinstance(entry["profile_id"], str) and entry["profile_id"].strip()):
        add("E-SHAPE", "error", "extractor_id must carry its version (`name/version`) and profile_id must be set")
    if not (isinstance(entry["page"], int) and not isinstance(entry["page"], bool) and entry["page"] >= 1):
        add("E-SHAPE", "error", "page must be an integer >= 1")
    if entry["reading_order"] not in READING_ORDERS:
        add("E-ORDER", "error", f"reading_order must be one of {READING_ORDERS} (it is never inferred from the flat text order)")
    if entry["fact_key"] not in approved_fact_keys:
        add("E-FACTKEY", "error", f"fact_key {entry['fact_key']!r} is not in the approved registry: a new key needs the agreement before any registration")
    if reviewed_profiles is not None:
        prof = reviewed_profiles.get(entry["profile_sha256"])
        if prof is None:
            add("E-PIN", "error", "profile_sha256 is not one of the reviewed profiles: an edited profile is a different profile and needs a new review")
        else:
            if prof.get("source_sha256") != entry["source_sha256"]:
                add("E-PIN", "error", "this reviewed profile was reviewed for another source file (source_sha256 differs)")
            if prof.get("reading_order") != entry["reading_order"]:
                add("E-ORDER", "error", "the reading order differs from the one the reviewed profile pins")
    if page_facts is not None and page_facts.get("source_sha256") not in (None, entry["source_sha256"]):
        add("E-PIN", "error", "the bytes the page facts were read from do not hash to the entry's source_sha256")
    page = (0.0, 0.0, float(page_size[0]), float(page_size[1]))
    table = entry["table_rect"]
    if not _rect_ok(table):
        add("E-SHAPE", "error", "table_rect must be [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        return out
    if not _inside(table, page):
        add("E-PAGE", "error", "table_rect leaves the page")
    anchor = entry["year_anchor"]
    values = entry["values"]
    if not (isinstance(values, dict) and {"unit", "category", "selection", "admission_year", "total_special", "total_general", "faculty_total"} <= set(values)):
        add("E-SHAPE", "error", "values needs unit, category, selection, admission_year, total_special, total_general and faculty_total")
        return out
    scope = entry["title_scope"]
    scope_ok = _rect_ok(scope) and _inside(scope, page)
    if not scope_ok:
        add("E-YEAR", "error", "title_scope must be a rectangle inside the page: the part of the page that the year title governs, written into the reviewed profile (it is not inferred from a distance)")
    elif not _inside(table, scope):
        add("E-SCOPE", "error", "the table rectangle leaves the title scope: enlarging the table (or moving the scope) does not bind it to a title")
    if not (isinstance(entry["expected_table_clusters"], int) and not isinstance(entry["expected_table_clusters"], bool) and entry["expected_table_clusters"] >= 1):
        add("E-SHAPE", "error", "expected_table_clusters is the number of separate drawn tables the title scope is declared to hold (an integer >= 1)")
    if not (isinstance(anchor, dict) and set(anchor) == {"text", "rect"} and _rect_ok(anchor["rect"]) and isinstance(anchor["text"], str)):
        add("E-YEAR", "error", "year_anchor is {text, rect}: the year is bound to the title rectangle, not to any string on the page")
    else:
        r = anchor["rect"]
        if not _inside(r, page):
            add("E-PAGE", "error", "year_anchor leaves the page")
        if scope_ok and not _inside(r, scope):
            add("E-YEAR", "error", "the year anchor lies outside the title scope (a title elsewhere on the page governs something else)")
        if r[3] > table[1] + TOLERANCE:
            add("E-YEAR", "error", "the year anchor must lie above the table (a footnote or a title below the table does not count)")
        if values["admission_year"] not in _years(anchor["text"]):
            add("E-YEAR", "error", "the anchor text does not name the admission year of the value")
    if page_facts is None:
        add("E-FACTS", "warning", "no independent page facts: the anchor text, the years inside the scope and the number of drawn tables were not verified (a new layout needs them)")
    else:
        found = page_facts.get("anchor_text_found")
        if isinstance(anchor, dict) and isinstance(anchor.get("text"), str) and found is not None and _flat(found) != _flat(anchor["text"]):
            add("E-YEAR", "error", "the anchor text is not what the page has at the anchor rectangle (a moved or invented title)")
        other = sorted({y["year"] for y in page_facts.get("years_in_scope", []) if y["year"] != values["admission_year"]})
        if other:
            add("E-YEARCONFLICT", "error", f"the title scope also holds the year(s) {other}: another year inside the scope makes the title ambiguous")
        if not page_facts.get("years_in_scope"):
            add("E-YEARCONFLICT", "error", "no year string was found inside the title scope")
        if page_facts.get("table_clusters_in_scope") != entry["expected_table_clusters"]:
            add("E-SCOPE", "error", f"the scope holds {page_facts.get('table_clusters_in_scope')} drawn table(s), the profile declares {entry['expected_table_clusters']} (an adjacent table inside the scope)")
        bbox = page_facts.get("drawn_bbox")
        if bbox and not _inside(table, bbox, TOLERANCE):
            add("E-SCOPE", "error", "the table rectangle is larger than the table that is drawn (an enlarged rectangle reaches text outside the table)")
    rows = entry["rows"]
    if not isinstance(rows, list) or not rows:
        add("E-SHAPE", "error", "rows is a non-empty list")
        return out
    total_counts = 0
    seen_labels = set()
    for i, row in enumerate(rows):
        if not (isinstance(row, dict) and set(row) == {"row_id", "label", "pool", "count", "value"} and all(isinstance(row[k], dict) and _rect_ok(row[k].get("rect")) and HEX64.match(str(row[k].get("text_sha256"))) for k in ROLES)):
            add("E-SHAPE", "error", f"row {i}: {{row_id, label, pool, count, value}}; each of label/pool/count has a rectangle and a text_sha256")
            continue
        label, pool, count = row["label"]["rect"], row["pool"]["rect"], row["count"]["rect"]
        for role in ROLES:
            if not _inside(row[role]["rect"], page):
                add("E-PAGE", "error", f"row {i} {role}: the rectangle leaves the page")
            if not _inside(row[role]["rect"], table, TOLERANCE):
                add("E-INSIDE", "error", f"row {i} {role}: the rectangle is outside the table rectangle")
        if not _overlap_v(label, count):
            add("E-ROW", "error", f"row {i}: the label and the count are not on the same row (their vertical ranges do not overlap)")
        if not (pool[1] <= min(label[1], count[1]) + TOLERANCE and pool[3] >= max(label[3], count[3]) - TOLERANCE):
            add("E-ROW", "error", f"row {i}: the pool cell does not contain the row of its label and count (a pool is borrowed from another row)")
        if row["row_id"] in seen_labels:
            add("E-ROW", "error", f"row {i}: duplicate row_id")
        seen_labels.add(row["row_id"])
        v = row["value"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
            add("E-VALUE", "error", f"row {i}: the count is a positive integer (an empty or ambiguous cell is refused, never 0)")
        else:
            total_counts += v
        if rulings:
            for role in ROLES:
                rect = row[role]["rect"]
                for axis, edges, lo, hi in (("y", rulings.get("horizontal", []), 1, 3), ("x", rulings.get("vertical", []), 0, 2)):
                    if not edges or not any(rect[lo] + TOLERANCE < e < rect[hi] - TOLERANCE for e in edges):
                        continue  # no ruling line runs through the rectangle: it lies inside one ruled cell
                    for edge in (lo, hi):  # it crosses a ruling line: legal only for a merged cell whose both ends are ON ruling lines
                        nearest = min(edges, key=lambda e: abs(rect[edge] - e))
                        gap = abs(rect[edge] - nearest)
                        if gap > TOLERANCE:
                            ink = (ink_extents or {}).get((i, role))
                            # A word box is the font's box, not the drawn glyphs (PyMuPDF's box of a vertical Japanese character reaches ~8pt past its ink). When the INK lies inside the ruled cell the overhang is
                            # information, not a defect of the profile; tightening the rectangle would instead clip a real word box and lose the word (Work, PR #103). The ink must be given by the caller (independent page facts).
                            ink_inside = ink is not None and _rect_ok(ink) and ((ink[edge] <= nearest + TOLERANCE) if edge in (hi,) else (ink[edge] >= nearest - TOLERANCE))
                            if ink_inside and gap <= OVERSHOOT_ERROR:
                                add("E-RULING", "info", f"row {i} {role}: the word box ends {gap:.1f} points from the nearest {axis} ruling line but the drawn ink lies inside the ruled cell (font-box overhang, K-5)")
                            else:
                                add("E-RULING", "error" if gap > OVERSHOOT_ERROR else "warning",
                                    f"row {i} {role}: a rectangle that crosses a ruling line ends {gap:.1f} points from the nearest {axis} ruling line (K-5)")
    if total_counts != values["total_special"]:
        add("E-VALUE", "error", f"the counts of the rows add up to {total_counts}, not to total_special {values['total_special']}")
    if values["total_special"] + values["total_general"] != values["faculty_total"]:
        add("E-VALUE", "error", "total_special + total_general must equal faculty_total (the faculty total is not a per-category count)")
    if values["selection"] == "一般選抜" or values["category"] == "一般選抜":
        add("E-SCOPE", "error", "a special-category count is never labelled as the general selection")
    if values["unit"] != "名" or not (isinstance(values["admission_year"], int) and 2000 <= values["admission_year"] <= 2100):
        add("E-SCOPE", "error", "unit must be 名 and admission_year a year")
    return out


def blocking(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["level"] == "error"]
