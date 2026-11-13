"""Independent tests of Work's G7 layout probe (PR #103: `research/inbox/work-g7-layout-probe/layout_probe.py`; K-1/K-2 fixed in head 297ffe8).

Claude-owned QA. DEFINED ONLY when Work's directory exists (absent, not skipped, until PR #103 is merged). The synthetic part uses invented word boxes. The REAL-DOCUMENT part is defined only when the two
SHA-pinned Kyoto PDFs are readable on the machine (a local read-only folder named in PR #103 comment 6572559830, or SOGH_G7_SOURCES_DIR): it never runs in CI and its result is not a CI fact.
Work's code is only imported and called. The former `test_known_issue_*` tests (K-1, K-2) were turned into regression tests once Work fixed them: the same inputs must now be rejected.
K-3 (multi-column reading order) and K-4 (year anchor not bound to the table block) are still open limitations and stay pinned as such."""
import importlib.util
import os
import re
from copy import deepcopy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_G7_DIR") or REPO / "research" / "inbox" / "work-g7-layout-probe")

if (WORK / "layout_probe.py").exists():
    _spec = importlib.util.spec_from_file_location("pr103_probe", WORK / "layout_probe.py")
    P = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(P)

    def two_rows():
        """Two rows of a table: 'A' in the general pool, 'B' in the women's pool; the pool cell of each is a merged cell on the left. All values invented."""
        words = [(0, 0, 2, 2, "方式A"), (3, 0, 5, 2, "一般枠"), (6, 0, 7, 2, "5"), (7.1, 0, 7.8, 2, "名"),
                 (0, 4, 2, 6, "方式B"), (3, 4, 5, 6, "女性枠"), (6, 4, 7, 6, "7"), (7.1, 4, 7.8, 6, "名"),
                 (6, 8, 7, 10, "20"), (7.1, 8, 7.8, 10, "名"), (6, 12, 7, 14, "32"), (7.1, 12, 7.8, 14, "名")]
        profile = {"rows": [{"label": "方式A", "pool": "一般枠", "label_rect": [-0.1, -0.1, 2.5, 2.5], "pool_rect": [2.9, -0.1, 5.5, 2.5], "count_rect": [5.9, -0.1, 8.5, 2.5]},
                            {"label": "方式B", "pool": "女性枠", "label_rect": [-0.1, 3.9, 2.5, 6.5], "pool_rect": [2.9, 3.9, 5.5, 6.5], "count_rect": [5.9, 3.9, 8.5, 6.5]}],
                   "page": 1, "guide_page": 8, "admission_category": "架空区分", "general_rect": [5.9, 7.9, 8.5, 10.5], "faculty_total_rect": [5.9, 11.9, 8.5, 14.5]}
        return words, profile, "学部(方式A)5人(方式B)7人"

    def test_the_consistent_two_row_table_is_extracted_with_scope_kept_apart():
        words, profile, guide = two_rows()
        r = P.extract(words, profile, guide)
        assert [(x["method_label"], x["pool"], x["count"]) for x in r["proposals"]] == [("方式A", "一般枠", 5), ("方式B", "女性枠", 7)]
        assert (r["faculty_total"], r["general_selection"], r["special_selection_total"]) == (32, 20, 12)

    @pytest.mark.parametrize("what", ["pool_text", "label_text", "count_vs_guide", "total", "empty_count", "two_counts_in_one_cell"])
    def test_a_wrong_pool_label_count_total_or_empty_cell_is_refused_and_zero_is_never_the_default(what):
        words, profile, guide = two_rows()
        if what == "pool_text":
            profile["rows"][0]["pool"] = "女性枠"
        elif what == "label_text":
            profile["rows"][0]["label"] = "方式C"
        elif what == "count_vs_guide":
            guide = guide.replace("5人", "6人")
        elif what == "total":
            profile["faculty_total_rect"] = [5.9, 7.9, 8.5, 10.5]  # points at the general count: 20 != 20 + 12
        elif what == "empty_count":
            words = [w for w in words if w[4] != "5"]
        else:
            words = words + [(6, 0.5, 7, 1.5, "9"), (7.1, 0.5, 7.8, 1.5, "名")]
        with pytest.raises(ValueError):
            P.extract(words, profile, guide)

    def test_the_same_label_twice_in_the_guide_is_refused_not_first_matched():
        words, profile, guide = two_rows()
        with pytest.raises(ValueError):
            P.extract(words, profile, guide + guide)

    def test_a_glyph_cut_by_the_cell_boundary_is_refused():
        with pytest.raises(ValueError, match="clipped_cell"):
            P.cell([(0, 0, 5, 5, "半端")], [1, 1, 4, 4])

    def test_the_order_of_the_flat_text_is_never_used_to_assign_numbers():
        """The profile binds each number by its rectangle: shuffling the order of the words changes nothing."""
        words, profile, guide = two_rows()
        a = P.extract(words, profile, guide)["proposals"]
        b = P.extract(list(reversed(words)), profile, guide)["proposals"]
        assert [(x["method_label"], x["count"]) for x in a] == [(x["method_label"], x["count"]) for x in b]


    # ---- K-1 (fixed): the pool cell must cover the row, and the label and count cells must be the same row -----------------------------------------------

    def three_rows():
        """A merged general pool spanning rows A and B, the women's pool for row C, then the general-selection count and the faculty total. All values invented."""
        words = [(0, 0, 2, 2, "方式A"), (6, 0, 7, 2, "5"), (7.1, 0, 7.8, 2, "名"), (0, 4, 2, 6, "方式B"), (6, 4, 7, 6, "10"), (7.1, 4, 7.8, 6, "名"),
                 (0, 8, 2, 10, "方式C"), (6, 8, 7, 10, "7"), (7.1, 8, 7.8, 10, "名"), (3, 1, 5, 5, "一般枠"), (3, 8.5, 5, 9.5, "女性枠"),
                 (6, 12, 7, 14, "20"), (7.1, 12, 7.8, 14, "名"), (6, 16, 7, 18, "42"), (7.1, 16, 7.8, 18, "名")]
        general_pool, women_pool = [2.9, -0.1, 5.5, 6.5], [2.9, 7.9, 5.5, 10.5]
        profile = {"rows": [{"label": "方式A", "pool": "一般枠", "label_rect": [-0.1, -0.1, 2.5, 2.5], "pool_rect": general_pool, "count_rect": [5.9, -0.1, 8.5, 2.5]},
                            {"label": "方式B", "pool": "一般枠", "label_rect": [-0.1, 3.9, 2.5, 6.5], "pool_rect": general_pool, "count_rect": [5.9, 3.9, 8.5, 6.5]},
                            {"label": "方式C", "pool": "女性枠", "label_rect": [-0.1, 7.9, 2.5, 10.5], "pool_rect": women_pool, "count_rect": [5.9, 7.9, 8.5, 10.5]}],
                   "page": 1, "guide_page": 8, "admission_category": "架空区分", "general_rect": [5.9, 11.9, 8.5, 14.5], "faculty_total_rect": [5.9, 15.9, 8.5, 18.5]}
        return words, profile, "学部(方式A)5人(方式B)10人(方式C)7人"

    def test_a_merged_pool_cell_that_spans_several_rows_is_accepted_for_each_of_its_rows():
        words, profile, guide = three_rows()
        r = P.extract(words, profile, guide)
        assert [(x["method_label"], x["pool"], x["count"]) for x in r["proposals"]] == [("方式A", "一般枠", 5), ("方式B", "一般枠", 10), ("方式C", "女性枠", 7)]
        assert (r["faculty_total"], r["general_selection"], r["special_selection_total"]) == (42, 20, 22)

    def test_k1_regression_a_row_that_borrows_another_rows_pool_cell_is_refused():
        """The former pinned weakness: row B (women's pool) pointed at row A's pool cell, whose text is the general pool."""
        words, profile, guide = two_rows()
        profile["rows"][1]["pool"] = "一般枠"
        profile["rows"][1]["pool_rect"] = deepcopy(profile["rows"][0]["pool_rect"])
        with pytest.raises(ValueError, match="pool_does_not_cover_row"):
            P.extract(words, profile, guide)

    def test_a_row_pointing_at_the_count_of_another_row_is_refused():
        words, profile, guide = three_rows()
        profile["rows"][1]["count_rect"] = deepcopy(profile["rows"][0]["count_rect"])  # row B's label, row A's number
        with pytest.raises(ValueError, match="label_count_row_mismatch"):
            P.extract(words, profile, guide)

    def test_a_second_merged_cell_with_the_same_text_is_not_a_substitute_for_the_cell_that_covers_the_row():
        words, profile, guide = three_rows()
        words = words + [(3, 11, 5, 12, "一般枠")]  # another cell below, same text
        profile["rows"][0]["pool_rect"] = [2.9, 10.6, 5.5, 12.5]
        with pytest.raises(ValueError, match="pool_does_not_cover_row"):
            P.extract(words, profile, guide)

    def test_a_label_that_straddles_the_boundary_between_two_pools_or_two_rows_is_refused():
        words, profile, guide = three_rows()
        straddle_pools = deepcopy(profile)
        straddle_pools["rows"][1]["label_rect"] = [-0.1, 3.9, 2.5, 10.5]  # reaches into the women's pool
        with pytest.raises(ValueError):
            P.extract(words, straddle_pools, guide)
        two_labels = deepcopy(profile)
        two_labels["rows"][0]["label_rect"] = [-0.1, -0.1, 2.5, 6.5]  # contains the labels of rows A and B
        with pytest.raises(ValueError, match="row_label_mismatch"):
            P.extract(words, two_labels, guide)

    def test_k3_fixed_a_multi_column_vertical_label_is_read_in_the_declared_order_and_the_default_order_is_unchanged():
        """K-3 (fixed in head a850773 by an explicit reading order): a label written in two vertical columns is read right-to-left, top-to-bottom when the profile says `vertical-rtl`.
        The low-level default stays `horizontal-ltr` (a legacy fixture), where the same glyphs come out interleaved: still a refusal at the label check, never a wrong binding."""
        words = [(2, 0, 3, 1, "上"), (2, 1, 3, 2, "中"), (1, 0, 2, 1, "下"), (1, 1, 2, 2, "端")]
        rect = [0.9, -0.1, 3.1, 2.1]
        assert P.cell(words, rect, "vertical-rtl") == "上中下端"
        assert P.cell(words, rect) != "上中下端" and sorted(P.cell(words, rect)) == sorted("上中下端")
        with pytest.raises(ValueError, match="unsupported_cell_reading_order"):
            P.cell(words, rect, "diagonal")

    def test_a_vertical_label_whose_glyph_columns_jitter_is_refused_not_misread():
        """Glyphs of one column with slightly different x make the right-to-left sort interleave them; the label check then fails (a refusal). A reviewed profile or a tolerance is the fix."""
        words = [(2.0, 0, 3, 1, "上"), (2.3, 1, 3.3, 2, "中"), (2.0, 2, 3, 3, "下")]
        assert P.cell(words, [1.9, -0.1, 3.4, 3.1], "vertical-rtl") != "上中下"
    def test_the_general_selection_count_is_not_added_to_the_special_selection_total():
        words, profile, guide = three_rows()
        profile["general_rect"] = deepcopy(profile["rows"][0]["count_rect"])  # the 'general' number is really a special count
        with pytest.raises(ValueError, match="faculty_general_special_consistency_failed"):
            P.extract(words, profile, guide)

    def test_the_faculty_total_is_not_confused_with_a_method_quota():
        words, profile, guide = three_rows()
        profile["faculty_total_rect"] = deepcopy(profile["general_rect"])  # 20 instead of 42
        with pytest.raises(ValueError, match="faculty_general_special_consistency_failed"):
            P.extract(words, profile, guide)

    def test_the_women_pool_and_the_general_pool_are_not_interchangeable():
        words, profile, guide = three_rows()
        profile["rows"][2]["pool"] = "一般枠"
        with pytest.raises(ValueError, match="pool_scope_mismatch"):
            P.extract(words, profile, guide)

    def test_a_degenerate_or_inverted_rectangle_is_refused():
        words, profile, guide = three_rows()
        profile["rows"][0]["pool_rect"] = [5.5, 6.5, 2.9, -0.1]
        with pytest.raises(ValueError):
            P.extract(words, profile, guide)

    # ---- K-4 (fixed in head a850773): the anchors are bound to rectangles of the reviewed block, above the table -----------------------------------------------

    def scoped():
        words, profile, guide = three_rows()
        words = words + [(0, -9, 3, -8, "2027年4月入学者"), (0, -6, 3, -5, "総合型選抜")]  # the title block above the table
        profile = deepcopy(profile)
        profile.update(year_anchor="2027年4月入学者", category_anchor="総合型選抜",
                       scope={"block_rect": [-1, -10, 9, 19], "table_rect": [-0.5, -0.2, 8.9, 18.8], "year_rect": [-0.1, -9.1, 3.1, -7.9], "category_rect": [-0.1, -6.1, 3.1, -4.9], "max_anchor_table_gap": 12, "basis": "synthetic"})
        return words, profile, guide

    def test_a_profile_with_a_reviewed_block_scope_is_extracted_and_labelled_as_scope_validated():
        words, profile, guide = scoped()
        r = P.extract(words, profile, guide)
        assert r["scope_validation"] == "reviewed_rectangles_and_local_anchors" and [x["count"] for x in r["proposals"]] == [5, 10, 7]

    def test_a_year_that_appears_only_elsewhere_on_the_page_does_not_satisfy_the_anchor():
        """The old check searched the whole page: a footnote mentioning the year satisfied it. Now the year must be inside its own rectangle."""
        words, profile, guide = scoped()
        words = [w for w in words if w[4] != "2027年4月入学者"] + [(6, 20, 8, 21, "2027年4月入学者")]  # the same text, but in a footnote far from the title rectangle
        with pytest.raises(ValueError, match="scope_anchor_missing_or_wrong|empty_cell"):  # the title rectangle holds no year at all (an empty cell is a refusal too)
            P.extract(words, profile, guide)

    def test_an_anchor_for_another_year_in_the_title_rectangle_is_refused():
        words, profile, guide = scoped()
        words = [w if w[4] != "2027年4月入学者" else (0, -9, 3, -8, "2028年4月入学者") for w in words]
        with pytest.raises(ValueError, match="scope_anchor_missing_or_wrong"):
            P.extract(words, profile, guide)

    def test_an_anchor_below_the_table_or_too_far_above_it_is_refused():
        words, profile, guide = scoped()
        below = deepcopy(profile)
        below["scope"]["year_rect"] = [-0.1, 19.0, 3.1, 19.9]
        below["scope"]["block_rect"] = [-1, -10, 9, 21]
        with pytest.raises(ValueError):
            P.extract(words + [(0, 19.2, 3, 19.7, "2027年4月入学者")], below, guide)
        far = deepcopy(profile)
        far["scope"]["max_anchor_table_gap"] = 2
        with pytest.raises(ValueError, match="anchor_not_above_target_table"):
            P.extract(words, far, guide)

    def test_a_table_or_a_row_outside_the_reviewed_block_or_table_is_refused():
        words, profile, guide = scoped()
        outside_block = deepcopy(profile)
        outside_block["scope"]["table_rect"] = [-0.5, -0.2, 9.9, 18.8]
        with pytest.raises(ValueError, match="table_outside_reviewed_block"):
            P.extract(words, outside_block, guide)
        outside_table = deepcopy(profile)
        outside_table["rows"][0]["count_rect"] = [5.9, -0.1, 12.5, 2.5]
        with pytest.raises(ValueError, match="row_outside_target_table"):
            P.extract(words, outside_table, guide)
        total_outside = deepcopy(profile)
        total_outside["scope"]["table_rect"] = [-0.5, -0.2, 8.9, 14.8]
        with pytest.raises(ValueError, match="totals_outside_target_table"):
            P.extract(words, total_outside, guide)

    def test_the_command_line_refuses_a_profile_without_a_reviewed_block_scope_before_reading_any_pdf(tmp_path, monkeypatch):
        import hashlib as _h
        import json as _j
        import sys as _s
        pdf = tmp_path / "fake.pdf"
        pdf.write_bytes(b"synthetic bytes, never parsed")
        digest = _h.sha256(pdf.read_bytes()).hexdigest()
        profile = tmp_path / "profile.json"
        profile.write_text(_j.dumps({"source_sha256": digest, "guide_sha256": digest}), encoding="utf-8")
        out = tmp_path / "out.json"
        monkeypatch.setattr(_s, "argv", ["layout_probe.py", "--profile", str(profile), "--pdf", str(pdf), "--guide", str(pdf), "--output", str(out)])
        with pytest.raises(ValueError, match="reviewed_block_scope_required"):
            P.main()
        assert not out.exists()

    def test_a_profile_without_scope_is_labelled_as_not_scope_validated_at_the_low_level():
        words, profile, guide = three_rows()
        assert P.extract(words, profile, guide)["scope_validation"] == "not_run_legacy_low_level_fixture"

    def test_k5_limit_the_probe_trusts_the_reviewed_rectangles_it_does_not_check_them_against_the_drawn_rules():
        """K-5 (open, information): the rectangles and the scope are a manually reviewed, SHA-pinned association (Work says so). Against the drawn table rules the last pool rectangle ends 6 pt below the
        rule; a check that the rectangles lie within the ruled cells would remove the reliance on the reviewer's eye. Pinned by reading that no rule is consulted."""
        source = (WORK / "layout_probe.py").read_text(encoding="utf-8")
        assert "get_drawings" not in source

    # ---- REAL documents (local only: defined when the two SHA-pinned PDFs are readable) --------------------------------------------------------------------
    import hashlib
    import json
    import subprocess
    import sys

    SUMMARY_SHA = "58dd4540d8a3a932d5bf124f3e03fa3209361d2dae430b96d4fa5527a993105f"
    GUIDE_SHA = "93b94cc803cc384f39c8776724f8a52bfc0a3b2bbd6dad928900677a246cb35a"
    SOURCES = Path(os.environ.get("SOGH_G7_SOURCES_DIR") or "O:/sogh-g7-20261102")
    SUMMARY_PDF, GUIDE_PDF = SOURCES / "sources" / f"{SUMMARY_SHA}.pdf", SOURCES / "guide" / f"{GUIDE_SHA}.pdf"

    def _readable(path, sha):
        try:
            return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha
        except OSError:
            return False

    try:
        import fitz as _fitz  # noqa: F401
        _HAS_FITZ = True
    except ImportError:  # the real-PDF tests read the PDFs with PyMuPDF: where it is absent they are not DEFINED (never skipped, never counted as passed)
        _HAS_FITZ = False

    if _HAS_FITZ and _readable(SUMMARY_PDF, SUMMARY_SHA) and _readable(GUIDE_PDF, GUIDE_SHA):
        def independent_rows():
            """Derive the five rows from the drawn rules and the glyphs themselves (not from the profile's rectangles): rows are the intervals between the horizontal rules of the table, pools are the
            intervals between the pool-column rules, the label is read from the vertical glyph stream, the quota from the 'N名' token whose centre lies in the row's interval."""
            import fitz
            with fitz.open(SUMMARY_PDF) as doc:
                page = doc[0]
                words = page.get_text("words")
                rules = set()
                for d in page.get_drawings():
                    for it in d["items"]:
                        if it[0] == "l" and abs(it[1][1] - it[2][1]) < 0.5 and abs(it[2][0] - it[1][0]) > 5:
                            rules.add((round(min(it[1][0], it[2][0])), round(max(it[1][0], it[2][0])), round(it[1][1])))
                        elif it[0] == "re" and it[1].height < 1.5 and it[1].width > 5:
                            rules.add((round(it[1].x0), round(it[1].x1), round((it[1].y0 + it[1].y1) / 2)))
            table = [y for x0, x1, y in rules if x0 <= 66 and x1 >= 82 and 240 < y < 726]
            pool_rules = sorted({y for x0, x1, y in rules if x0 <= 50 and x1 >= 80 and 240 < y < 726})
            row_bounds = sorted(set(table))
            labels = sorted((w for w in words if 66 <= w[0] <= 82 and 240 <= w[1] <= 726), key=lambda w: w[1])
            counts = [(w, words[i + 1]) for i, w in enumerate(words) if w[4].isdigit() and 355 < w[0] < 383 and i + 1 < len(words) and words[i + 1][4] == "名"]
            pools = sorted((w for w in words if 50 <= w[0] <= 62 and 360 <= w[1] <= 726), key=lambda w: w[1])
            rows = []
            for top, bottom in zip(row_bounds, row_bounds[1:]):
                label = "".join(w[4] for w in labels if top <= (w[1] + w[3]) / 2 < bottom)
                number = [int(c[0][4]) for c in counts if top <= (c[0][1] + c[0][3]) / 2 < bottom]
                pool_cells = [(a, b) for a, b in zip(pool_rules, pool_rules[1:]) if a <= top and bottom <= b]
                pool_glyphs = {("".join(w[4] for w in pools if a <= (w[1] + w[3]) / 2 < b)) for a, b in pool_cells}
                rows.append({"label": label, "count": number, "pool": sorted(pool_glyphs)})
            general = [int(c[0][4]) for c in counts if c[0][1] > 735]
            total = [int(w[4]) for w in words if w[4].isdigit() and 355 < w[0] < 383 and 210 < w[1] < 230]
            return rows, general, total

        def test_real_documents_the_five_special_selection_rows_are_the_same_when_derived_independently_from_the_drawn_rules(tmp_path):
            rows, general, total = independent_rows()
            assert [r["label"] for r in rows] == ["数理科学入試", "生物科学入試", "化学入試", "物理学・数学入試", "宇宙・地球惑星科学入試"]
            assert [r["count"] for r in rows] == [[5], [10], [7], [10], [5]] and general == [274] and total == [311]
            assert [r["pool"] for r in rows] == [["一般枠"], ["一般枠"], ["一般枠"], ["女性募集枠"], ["女性募集枠"]]
            out = tmp_path / "work-result.json"
            done = subprocess.run([sys.executable, "-B", "-X", "utf8", str(WORK / "layout_probe.py"), "--profile", str(WORK / "kyoto_science_2027.json"), "--pdf", str(SUMMARY_PDF),
                                   "--guide", str(GUIDE_PDF), "--output", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"), timeout=300)
            assert done.returncode == 0, done.stderr[-400:]
            result = json.loads(out.read_text(encoding="utf-8"))
            assert [(p["method_label"], p["pool"][:3] if p["pool"].startswith("一般") else p["pool"], p["count"]) for p in result["proposals"]] == \
                   [(r["label"], "一般枠" if r["pool"] == ["一般枠"] else "女性募集枠", r["count"][0]) for r in rows]
            assert result["faculty_total"] == total[0] and result["general_selection"] == general[0] and result["special_selection_total"] == 37
            assert result["not_registered"] is True and all(p["candidate_status"].startswith("pending") for p in result["proposals"])

        def test_real_documents_the_guide_confirms_each_label_and_count_but_not_the_pool_or_the_totals():
            """The second source (the guide) corroborates 'label -> number' only. The pool (general / women's) and the totals (311, 274) rest on the summary table alone."""
            import fitz
            import unicodedata
            with fitz.open(GUIDE_PDF) as guide:
                text = "".join(c for c in unicodedata.normalize("NFKC", guide[7].get_text()) if not c.isspace())
            start = text.find("理学部(数理科学入試)")
            section = text[start:text.find("医学部", start)]
            for label, n in (("数理科学入試", 5), ("生物科学入試", 10), ("化学入試", 7), ("物理学・数学入試", 10), ("宇宙・地球惑星科学入試", 5)):
                assert f"({label}){n}人" in section
            assert "女性募集枠" not in section and "311" not in section and "274" not in section