"""Positive and negative cases of the table-cell evidence contract candidate (src/integration/table_cell_evidence_check.py, docs/G7_TABLE_CELL_CONTRACT_V1_CANDIDATE.md).

SYNTHETIC_ONLY: an invented page geometry (three ruled rows, two pools, a title above the table). No real document is read. The cases are the ones Work's next implementation has to pass: every negative
names the code that must fire. Passing accepts nothing and registers nothing."""
from copy import deepcopy

import pytest

from src.integration import table_cell_evidence_check as T

PAGE = (595.0, 842.0)
RULINGS = {"horizontal": [110.0, 150.0, 190.0, 230.0], "vertical": [50.0, 150.0, 160.0, 440.0, 450.0, 500.0]}
APPROVED = {"admission_quota_by_category"}
H = "0" * 64


def cell(rect):
    return {"rect": rect, "text_sha256": H}


def row(rid, y0, y1, pool_rect, value):
    return {"row_id": rid, "label": cell([50.0, y0, 150.0, y1]), "pool": cell(pool_rect), "count": cell([450.0, y0, 500.0, y1]), "value": value}


def entry():
    return {"fact_key": "admission_quota_by_category", "source_sha256": "a" * 64, "page": 1, "extractor_id": "pymupdf-page-get_text-words/1.27", "profile_id": "fiction-profile-1",
            "profile_sha256": "b" * 64, "reading_order": "column_rtl", "table_rect": [40.0, 100.0, 550.0, 400.0], "title_scope": [20.0, 20.0, 570.0, 420.0], "expected_table_clusters": 1,
            "year_anchor": {"text": "2027年度 入学者選抜 募集人員", "rect": [40.0, 70.0, 300.0, 90.0]},
            "rows": [row("r0", 110.0, 150.0, [160.0, 110.0, 440.0, 190.0], 5), row("r1", 150.0, 190.0, [160.0, 110.0, 440.0, 190.0], 10), row("r2", 190.0, 230.0, [160.0, 190.0, 440.0, 230.0], 7)],
            "values": {"unit": "名", "category": "特色入試", "selection": "総合型選抜", "admission_year": 2027, "total_special": 22, "total_general": 90, "faculty_total": 112}}


FACTS = {"years_in_scope": [{"year": 2027, "rect": [40.0, 70.0, 300.0, 90.0]}], "anchor_text_found": "2027年度 入学者選抜 募集人員", "table_clusters_in_scope": 1, "drawn_bbox": [38.0, 98.0, 552.0, 402.0]}


def run(e, **kw):
    kw.setdefault("page_facts", FACTS)
    kw.setdefault("page_size", PAGE)
    kw.setdefault("rulings", RULINGS)
    kw.setdefault("approved_fact_keys", APPROVED)
    return T.check_entry(e, **kw)


def codes(findings, level="error"):
    return sorted({f["code"] for f in findings if f["level"] == level})


def test_a_correct_entry_has_no_finding_at_all():
    assert run(entry()) == []


NEGATIVE = [
    ("extra field", lambda e: e.update(note="x"), ["E-SHAPE"]),
    ("hash not hex", lambda e: e.update(profile_sha256="G" * 64), ["E-HASH"]),
    ("source hash short", lambda e: e.update(source_sha256="a" * 63), ["E-HASH"]),
    ("extractor without a version", lambda e: e.update(extractor_id="pymupdf"), ["E-SHAPE"]),
    ("page 0", lambda e: e.update(page=0), ["E-SHAPE"]),
    ("reading order not named", lambda e: e.update(reading_order="auto"), ["E-ORDER"]),
    ("new fact key without agreement", lambda e: e.update(fact_key="quota_by_category_v2"), ["E-FACTKEY"]),
    ("table leaves the page", lambda e: e.update(table_rect=[40.0, 100.0, 700.0, 400.0]), ["E-PAGE"]),
    ("year anchor is a bare string", lambda e: e.update(year_anchor="2027年度"), ["E-YEAR"]),
    ("year anchor below the table", lambda e: e["year_anchor"].update(rect=[40.0, 405.0, 300.0, 415.0]), ["E-YEAR"]),
    ("year anchor outside the title scope (another column)", lambda e: e["year_anchor"].update(rect=[575.0, 70.0, 590.0, 90.0]), ["E-YEAR"]),
    ("year anchor outside the title scope (above it)", lambda e: e["year_anchor"].update(rect=[40.0, 5.0, 300.0, 15.0]), ["E-YEAR"]),
    ("title scope outside the page", lambda e: e.update(title_scope=[20.0, 20.0, 700.0, 420.0]), ["E-YEAR"]),
    ("table enlarged beyond the title scope", lambda e: e.update(title_scope=[20.0, 20.0, 570.0, 390.0]), ["E-SCOPE"]),
    ("same-page other year inside the scope", lambda e: e["page_facts"]["years_in_scope"].append({"year": 2026, "rect": [40.0, 300.0, 100.0, 310.0]}), ["E-YEARCONFLICT"]),
    ("no year string inside the scope", lambda e: e["page_facts"].update(years_in_scope=[]), ["E-YEARCONFLICT"]),
    ("adjacent table inside the scope", lambda e: e["page_facts"].update(table_clusters_in_scope=2), ["E-SCOPE"]),
    ("table rectangle enlarged beyond the drawn table", lambda e: e.update(table_rect=[40.0, 100.0, 550.0, 415.0]), ["E-SCOPE"]),
    ("title moved: the page has other text at the anchor rectangle", lambda e: e["page_facts"].update(anchor_text_found="別の表の題名"), ["E-YEAR"]),
    ("expected table clusters not declared as an integer", lambda e: e.update(expected_table_clusters="1"), ["E-SHAPE"]),
    ("year anchor names another year", lambda e: e["year_anchor"].update(text="2026年度 入学者選抜"), ["E-YEAR"]),
    ("count of another row (no vertical overlap)", lambda e: e["rows"][0]["count"].update(rect=[450.0, 150.0, 500.0, 190.0]), ["E-ROW"]),
    ("pool borrowed from another row", lambda e: e["rows"][2].update(pool=cell([160.0, 110.0, 440.0, 150.0])), ["E-ROW"]),
    ("duplicate row id", lambda e: e["rows"][1].update(row_id="r0"), ["E-ROW"]),
    ("cell outside the table", lambda e: e["rows"][0]["count"].update(rect=[560.0, 110.0, 590.0, 150.0]), ["E-INSIDE"]),
    ("count 0 (an empty cell is never 0)", lambda e: e["rows"][0].update(value=0), ["E-VALUE"]),
    ("count as string", lambda e: e["rows"][0].update(value="5"), ["E-VALUE"]),
    ("count as bool", lambda e: e["rows"][0].update(value=True), ["E-VALUE"]),
    ("counts do not add up to the special total", lambda e: e["values"].update(total_special=23), ["E-VALUE"]),
    ("special + general is not the faculty total", lambda e: e["values"].update(faculty_total=111), ["E-VALUE"]),
    ("faculty total used as a category count", lambda e: e["rows"][0].update(value=112), ["E-VALUE"]),
    ("special count labelled as the general selection", lambda e: e["values"].update(selection="一般選抜"), ["E-SCOPE"]),
    ("unit not 名", lambda e: e["values"].update(unit="人"), ["E-SCOPE"]),
    ("rectangle crosses a ruling line far from any ruling", lambda e: e["rows"][0]["label"].update(rect=[50.0, 120.0, 150.0, 170.0]), ["E-RULING"]),
]


@pytest.mark.parametrize("name,mutate,expected", NEGATIVE, ids=[n[0] for n in NEGATIVE])
def test_each_negative_case_fires_its_code(name, mutate, expected):
    e = entry()
    e["page_facts"] = deepcopy(FACTS)
    mutate(e)
    facts = e.pop("page_facts")
    got = codes(run(e, page_facts=facts))
    assert set(expected) <= set(got), (name, got)


def test_a_rectangle_a_few_points_below_its_ruling_line_is_a_warning_not_an_error_k5():
    """The K-5 finding of PR #103: the last pool rectangle ended 6 points below the drawn line. It is reported, never silently accepted, and it does not block by itself."""
    e = entry()
    e["rows"][2]["pool"]["rect"] = [160.0, 190.0, 440.0, 236.0]
    assert codes(run(e)) == [] and codes(run(e), "warning") == ["E-RULING"]
    e["rows"][2]["pool"]["rect"] = [160.0, 190.0, 440.0, 245.0]  # 15 points: an error
    assert "E-RULING" in codes(run(e))


def test_a_word_box_overhang_is_information_when_the_ink_lies_inside_the_ruled_cell_and_still_a_warning_otherwise():
    """v1.2 (K-5): the font box of a word can reach past the drawn glyphs. The ink must come from independent page facts; without it, or with ink outside the cell, the finding stays what it was."""
    e = entry()
    e["rows"][2]["pool"]["rect"] = [160.0, 190.0, 440.0, 236.0]  # 6 points below the drawn line at 230
    inside = {(2, "pool"): [165.0, 192.0, 435.0, 228.0]}
    f = run(e, ink_extents=inside)
    assert codes(f) == [] and codes(f, "warning") == [] and codes(f, "info") == ["E-RULING"]
    outside = {(2, "pool"): [165.0, 192.0, 435.0, 234.0]}  # the ink itself crosses the line
    assert codes(run(e, ink_extents=outside), "warning") == ["E-RULING"]
    assert codes(run(e), "warning") == ["E-RULING"]  # no ink given: unchanged
    assert codes(run(e, ink_extents={(2, "pool"): [0, 0, 0, 0]}), "warning") == ["E-RULING"]  # a malformed ink box is not trusted


def test_the_ink_cannot_excuse_an_overhang_beyond_the_error_distance():
    e = entry()
    e["rows"][2]["pool"]["rect"] = [160.0, 190.0, 440.0, 245.0]  # 15 points
    assert "E-RULING" in codes(run(e, ink_extents={(2, "pool"): [165.0, 192.0, 435.0, 228.0]}))


def test_a_merged_pool_cell_whose_ends_are_on_ruling_lines_is_legal():
    assert run(entry()) == []  # the first pool spans rows r0 and r1 and ends on the lines at 110 and 190


def test_without_rulings_the_entry_is_checked_but_flagged_as_not_anchored_to_drawn_lines():
    e = entry()
    assert run(e, rulings=None) == []  # the ruling check is skipped only when the caller has none; the contract requires them for a new layout (see the document)


def test_the_check_never_modifies_its_input():
    e = entry()
    before = deepcopy(e)
    run(e)
    assert e == before


def test_a_page_size_that_differs_from_the_one_of_the_entry_is_the_callers_to_refuse_and_a_smaller_page_makes_the_table_leave_it():
    assert "E-PAGE" in codes(run(entry(), page_size=(400.0, 300.0)))


def test_a_title_far_above_the_table_is_accepted_when_it_lies_inside_the_reviewed_scope_and_nothing_else_in_the_scope_names_another_year():
    """The real Kyoto page: the title is 152 points above the table. The fixed 80-point rule rejected it; the scope rule does not look at the distance."""
    e = entry()
    e["title_scope"] = [5.0, 5.0, 590.0, 420.0]
    e["year_anchor"]["rect"] = [40.0, 8.0, 300.0, 20.0]
    assert run(e) == []


def test_the_reiwa_notation_of_the_year_is_the_same_year():
    e = entry()
    e["year_anchor"]["text"] = "令和9年度 入学者選抜 募集人員"
    f = deepcopy(FACTS)
    f["anchor_text_found"] = "令和9年度 入学者選抜 募集人員"
    assert run(e, page_facts=f) == []


REVIEWED = {"b" * 64: {"source_sha256": "a" * 64, "reading_order": "column_rtl"}}


def test_the_reviewed_pair_passes_and_every_deviation_from_it_is_refused():
    assert run(entry(), reviewed_profiles=REVIEWED) == []
    e = entry(); e["profile_sha256"] = "c" * 64
    assert codes(run(e, reviewed_profiles=REVIEWED)) == ["E-PIN"]  # profile SHA not reviewed
    e = entry(); e["source_sha256"] = "d" * 64
    assert "E-PIN" in codes(run(e, reviewed_profiles=REVIEWED))  # the profile was reviewed for another PDF
    e = entry(); e["reading_order"] = "row"
    assert codes(run(e, reviewed_profiles=REVIEWED)) == ["E-ORDER"]  # reading order differs from the pinned one
    assert "E-PIN" in codes(run(entry(), reviewed_profiles=REVIEWED, page_facts={**FACTS, "source_sha256": "e" * 64}))  # the facts were read from other bytes


def test_without_page_facts_a_new_layout_gets_a_warning_not_a_pass():
    assert codes(run(entry(), page_facts=None), "warning") == ["E-FACTS"] and codes(run(entry(), page_facts=None)) == []


def test_a_wrong_title_scope_cannot_be_used_to_hide_a_second_year():
    """Widening the scope to hold the whole page only makes more year strings visible: a different year anywhere in it is a conflict."""
    e = entry()
    e["title_scope"] = [0.0, 0.0, 595.0, 842.0]
    f = deepcopy(FACTS)
    f["years_in_scope"].append({"year": 2028, "rect": [40.0, 600.0, 100.0, 610.0]})
    assert codes(run(e, page_facts=f)) == ["E-YEARCONFLICT"]


# ---- the real Kyoto page (defined only where the SHA-pinned PDF, Work's local probe entry and PyMuPDF are all present: never skipped, never counted where absent) ----------------------------
import glob  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

_PDF_SHA = "58dd4540d8a3a932d5bf124f3e03fa3209361d2dae430b96d4fa5527a993105f"
_PDF = Path(os.environ.get("SOGH_G7_SOURCES_DIR") or "O:/sogh-g7-20261102") / "sources" / f"{_PDF_SHA}.pdf"
_PROBE = Path(os.environ.get("SOGH_G7_PROBE") or "O:/sogh-integration-20261102/table-contract-probe.json")
try:
    import fitz  # noqa: F401
    _FITZ = True
except ImportError:
    _FITZ = False


def _readable():
    try:
        return _PDF.is_file() and _PROBE.is_file() and hashlib.sha256(_PDF.read_bytes()).hexdigest() == _PDF_SHA
    except OSError:
        return False


if _FITZ and _readable():
    from src.integration.pdf_page_facts import page_facts

    SCOPE = [24.0, 20.0, 562.0, 826.0]

    def real_entry():
        probe = json.loads(_PROBE.read_text(encoding="utf-8"))
        e = deepcopy(probe["entry"])
        e["title_scope"], e["expected_table_clusters"] = SCOPE, 1
        return e, probe["rulings_from_saved_pdf_vectors"]

    def real_run(e, rulings, **kw):
        facts = page_facts(_PDF.read_bytes(), 1, e["title_scope"], e["year_anchor"]["rect"])
        return T.check_entry(e, page_size=(595.22, 842.0), rulings=rulings, approved_fact_keys={"admission_category_quota"}, page_facts=kw.get("page_facts", facts))

    def test_real_the_kyoto_page_is_accepted_by_the_scope_rule_with_only_the_k5_warnings_left():
        e, rul = real_entry()
        f = real_run(e, rul)
        assert codes(f) == [], f
        assert [x["code"] for x in f if x["level"] == "warning"] == ["E-RULING"] * 4

    def test_real_the_pinned_pair_and_the_saved_bytes_are_the_reviewed_ones_and_any_other_pair_is_refused():
        e, rul = real_entry()
        reviewed = {e["profile_sha256"]: {"source_sha256": _PDF_SHA, "reading_order": e["reading_order"]}}
        facts = page_facts(_PDF.read_bytes(), 1, e["title_scope"], e["year_anchor"]["rect"])
        assert facts["source_sha256"] == _PDF_SHA
        ok = T.check_entry(e, page_size=(595.22, 842.0), rulings=rul, approved_fact_keys={"admission_category_quota"}, page_facts=facts, reviewed_profiles=reviewed)
        assert codes(ok) == []
        bad_profile = {**e, "profile_sha256": "0" * 64}
        assert "E-PIN" in codes(T.check_entry(bad_profile, page_size=(595.22, 842.0), approved_fact_keys={"admission_category_quota"}, page_facts=facts, reviewed_profiles=reviewed))
        assert "E-PIN" in codes(T.check_entry(e, page_size=(595.22, 842.0), approved_fact_keys={"admission_category_quota"}, page_facts={**facts, "source_sha256": "0" * 64}, reviewed_profiles=reviewed))
        assert "E-ORDER" in codes(T.check_entry({**e, "reading_order": "row"}, page_size=(595.22, 842.0), approved_fact_keys={"admission_category_quota"}, page_facts=facts, reviewed_profiles=reviewed))

    def test_real_the_old_distance_rule_would_have_refused_this_page_and_the_scope_rule_does_not_depend_on_the_distance():
        e, rul = real_entry()
        gap = e["table_rect"][1] - e["year_anchor"]["rect"][3]
        assert gap > 150 and not (gap <= 80)

    def test_real_the_page_holds_one_year_one_title_and_one_drawn_table():
        e, rul = real_entry()
        facts = page_facts(_PDF.read_bytes(), 1, e["title_scope"], e["year_anchor"]["rect"])
        assert {y["year"] for y in facts["years_in_scope"]} == {2027} and facts["table_clusters_in_scope"] == 1 and _flat_eq(facts["anchor_text_found"], e["year_anchor"]["text"])

    def _flat_eq(a, b):
        import unicodedata
        f = lambda t: "".join(c for c in unicodedata.normalize("NFKC", t) if not c.isspace())  # noqa: E731
        return f(a) == f(b)

    REAL_NEGATIVE = [
        ("the title is moved to a place that has other text", lambda e: e["year_anchor"].update(rect=[28.0, 118.0, 555.0, 127.0]), "E-YEAR"),
        ("the title is claimed to be below the table", lambda e: e["year_anchor"].update(rect=[40.0, 780.0, 300.0, 790.0]), "E-YEAR"),
        ("the scope is narrowed so that it no longer holds the title", lambda e: e.update(title_scope=[24.0, 60.0, 562.0, 826.0]), "E-YEAR"),
        ("the scope is narrowed so that it no longer holds the table", lambda e: e.update(title_scope=[24.0, 20.0, 562.0, 600.0]), "E-SCOPE"),
        ("the table rectangle is enlarged beyond the drawn table", lambda e: e.update(table_rect=[45.0, 187.0, 553.0, 826.0]), "E-SCOPE"),
        ("another table is declared to be in the scope", lambda e: e.update(expected_table_clusters=2), "E-SCOPE"),
        ("the admission year of the value is another year", lambda e: (e["values"].update(admission_year=2026)), "E-YEAR"),
        ("the faculty total is used as the special total", lambda e: e["values"].update(total_special=311), "E-VALUE"),
    ]

    @pytest.mark.parametrize("name,mutate,code", REAL_NEGATIVE, ids=[n[0] for n in REAL_NEGATIVE])
    def test_real_negative_cases_on_the_kyoto_page_fire_their_code(name, mutate, code):
        e, rul = real_entry()
        mutate(e)
        assert code in codes(real_run(e, rul)), name

    def test_real_a_different_year_inside_the_scope_is_a_conflict_even_when_the_pdf_itself_is_unchanged():
        e, rul = real_entry()
        facts = page_facts(_PDF.read_bytes(), 1, e["title_scope"], e["year_anchor"]["rect"])
        facts["years_in_scope"].append({"year": 2026, "rect": [28.0, 39.0, 562.0, 49.0]})
        assert "E-YEARCONFLICT" in codes(real_run(e, rul, page_facts=facts))

    def test_real_k5_classification_the_four_warnings_come_from_one_bottom_edge_and_the_checker_alone_stops_warning_when_it_is_at_the_ruling():
        """A property of the CHECKER only: the four warnings trace to rectangles whose bottom is y=731 (drawn bottom border 724.6-724.8; the next line, 731.16, starts the general-selection band). With the bottom
        at 724.8 the checker is silent. CORRECTION (2026-11-03, after Work's review of PR #103): this is NOT a recommendation to tighten the profile. The extraction keeps whole word boxes, and the last character's box
        ends at 728.6 although its ink ends at ~720.3: tightening to the ruling would clip a real word. The right classification is the ink-based one in the tests below (information, font-box overhang)."""
        e, rul = real_entry()
        for row in e["rows"]:
            for role in ("label", "pool", "count"):
                r = row[role]["rect"]
                if r[3] == 731:
                    r[3] = 724.8
        f = real_run(e, rul)
        assert codes(f) == [] and [x for x in f if x["level"] == "warning"] == []


if _FITZ and _readable():
    from src.integration.pdf_page_facts import ink_extent

    def _ink_for_the_warned_cells(e, rul):
        raw = _PDF.read_bytes()
        ys = rul["horizontal"]
        ink = {}
        for i in (3, 4):
            for role in ("label", "pool"):
                x0, _, x1, _ = e["rows"][i][role]["rect"]
                top = max(y for y in ys if y <= e["rows"][i][role]["rect"][1] + 6)
                bottom = 724.59
                ink[(i, role)] = ink_extent(raw, 1, [x0 + 1.5, top + 1.5, x1 - 1.5, bottom - 1.5])
        return ink

    def test_real_k5_the_overhang_is_the_font_box_not_the_ink_and_tightening_the_rectangle_would_clip_a_word():
        """Corrects the earlier recommendation (Issue #122, 2026-11-03: 'tighten the bottom to 724.8'). The words of the last row have boxes that end at 728.6 while the drawn glyphs end at ~720.3, inside the
        ruled cell (bottom rules 724.6-724.8). A rectangle that must contain whole word boxes cannot be tightened to the rule without dropping that word (Work, PR #103)."""
        import fitz
        e, rul = real_entry()
        raw = _PDF.read_bytes()
        with fitz.open(stream=raw, filetype="pdf") as doc:
            overhanging = [w for w in doc[0].get_text("words") if 60 <= w[0] <= 84 and 633 <= w[1] and w[3] > 724.9 and w[1] < 731.5]
        assert overhanging and max(w[3] for w in overhanging) > 724.84
        ink = _ink_for_the_warned_cells(e, rul)
        assert all(v is not None and v[3] < 724.0 for v in ink.values()), ink

    def test_real_k5_with_the_independent_ink_the_four_warnings_become_information():
        e, rul = real_entry()
        facts = page_facts(_PDF.read_bytes(), 1, e["title_scope"], e["year_anchor"]["rect"])
        f = T.check_entry(e, page_size=(595.22, 842.0), rulings=rul, approved_fact_keys={"admission_category_quota"}, page_facts=facts, ink_extents=_ink_for_the_warned_cells(e, rul))
        assert codes(f) == [] and [x for x in f if x["level"] == "warning"] == []
        assert [x["code"] for x in f if x["level"] == "info"] == ["E-RULING"] * 4
