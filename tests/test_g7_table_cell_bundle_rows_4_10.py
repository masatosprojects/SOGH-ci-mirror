"""SELF_TEST (author Claude; independent QA is Antigravity's).  Rows 4-10 of the 12-row G-07 refusal matrix, fed with bundles in the format of Work's PR #103 (read only) into the
MERGED quarantine staging product code (src/db_contract/quarantine_staging.py, migration 0013) through the adapter scripts/g7_bundle_adapter.py.

SYNTHETIC_ONLY: an invented university, invented labels, invented geometry.  No original text, no network, no operational DB.  Nothing here accepts a fact or promotes a candidate.

Layers (stated per test, so that no row is credited to a layer that did not refuse it):
  ADAPTER   scripts/g7_bundle_adapter.py  (text must hash to the bundle's text_sha256; profile-pinned cell hashes)
  GEOMETRY  src/integration/table_cell_evidence_check.check_entry  (rectangles, merged cells, scope, sums)
  PRODUCT   quarantine_staging.evaluate_table_cell_format  (the refusal matrix)
Where the PRODUCT alone ACCEPTS something that the contract says must be refused, a test pins that fact (CHARACTERIZATION) instead of faking a refusal; the report lists them."""
import importlib.util
import json
import sqlite3
import sys
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from src.db_contract import additive_schema as ad
from src.db_contract import quarantine_staging as qs
from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore

_spec = importlib.util.spec_from_file_location("g7_bundle_adapter", Path(__file__).resolve().parent.parent / "scripts" / "g7_bundle_adapter.py")
A = importlib.util.module_from_spec(_spec)
sys.modules["g7_bundle_adapter"] = A
_spec.loader.exec_module(A)
RC = qs.RefusalCode

PAGE = (595.0, 842.0)
RULINGS = {"horizontal": [110.0, 150.0, 190.0, 230.0], "vertical": [50.0, 150.0, 160.0, 440.0, 450.0, 500.0]}
FACTS = {"years_in_scope": [{"year": 2027, "rect": [40.0, 70.0, 300.0, 90.0]}], "anchor_text_found": "架空大学 架空学部 2027年度 入学者選抜 募集人員", "table_clusters_in_scope": 1, "drawn_bbox": [38.0, 98.0, 552.0, 402.0]}
TITLE = "架空大学 架空学部 2027年度 入学者選抜 募集人員"
KEY = "admission_category_quota"  # the only quota-by-category key the PRODUCT recognises (see test_adopted_fact_key_is_not_recognised_by_the_product)
LABELS = {"r0": "方式甲", "r1": "方式乙", "r2": "方式丙"}
POOLS = {"r0": "一般枠", "r1": "一般枠", "r2": "女性枠"}
COUNTS = {"r0": "5名", "r1": "10名", "r2": "7名"}


def _cell(rect, text):
    return {"rect": rect, "text_sha256": A.text_sha(text)}


def make():
    """(entry, texts): a bundle in the PR #103 entry format whose row r0/r1 share one MERGED pool cell, plus the texts the caller read from the document."""
    pool_a, pool_b = [160.0, 110.0, 440.0, 190.0], [160.0, 190.0, 440.0, 230.0]
    ys = {"r0": (110.0, 150.0), "r1": (150.0, 190.0), "r2": (190.0, 230.0)}
    rows, texts = [], {}
    for rid, (y0, y1) in ys.items():
        pool = pool_a if rid != "r2" else pool_b
        rows.append({"row_id": rid, "label": _cell([50.0, y0, 150.0, y1], LABELS[rid]), "pool": _cell(pool, POOLS[rid]), "count": _cell([450.0, y0, 500.0, y1], COUNTS[rid]),
                     "value": int(COUNTS[rid].rstrip("名"))})
        texts[(rid, "label")], texts[(rid, "pool")], texts[(rid, "count")] = LABELS[rid], POOLS[rid], COUNTS[rid]
    entry = {"fact_key": KEY, "source_sha256": "a" * 64, "page": 1, "extractor_id": "pymupdf-words/1.27", "profile_id": "fiction-profile-1", "profile_sha256": "b" * 64, "reading_order": "column_rtl",
             "table_rect": [40.0, 100.0, 550.0, 400.0], "title_scope": [20.0, 20.0, 570.0, 420.0], "expected_table_clusters": 1, "year_anchor": {"text": TITLE, "rect": [40.0, 70.0, 300.0, 90.0]},
             "rows": rows, "values": {"unit": "名", "category": "特色入試", "selection": "総合型選抜", "admission_year": 2027, "total_special": 22, "total_general": 90, "faculty_total": 112}}
    return entry, texts


def pins(**kw):
    kw.setdefault("page", 1)
    kw.setdefault("title_sha256", A.text_sha(TITLE))
    return A.Pins(**kw)


GEO = {"page_size": PAGE, "rulings": RULINGS, "page_facts": FACTS}


def run(entry, texts, p=None, claim=None, geometry=GEO):
    return A.evaluate_bundle(entry, texts, p or pins(), claim, geometry=geometry, approved=frozenset({KEY}))


def set_text(entry, texts, rid, role, text, value=None):
    """Change a cell text AND keep the bundle self-consistent (the bundle's hash is recomputed): the submitter is not careless, the product must still refuse."""
    texts[(rid, role)] = text
    row = next(r for r in entry["rows"] if r["row_id"] == rid)
    row[role]["text_sha256"] = A.text_sha(text)
    if value is not None:
        row["value"] = value


def codes(out, rid="r0"):
    return out["rows"][rid].code


# ---- positive control (row 11) -------------------------------------------------------------------------------------------------------------------------------------------------
def test_row11_positive_control_all_three_layers_accept_the_clean_bundle():
    entry, texts = make()
    out = run(entry, texts)
    assert out["adapter"] == [] and [f for f in out["geometry"] if f["level"] != "info"] == []
    assert {k: v.code for k, v in out["rows"].items()} == {"r0": RC.ACCEPTED, "r1": RC.ACCEPTED, "r2": RC.ACCEPTED}
    assert out["decision"] == "ACCEPT"
    assert out["rows"]["r1"].normalized_value == "10名" and out["rows"]["r1"].quarantine_payload["row_label"] == "方式乙" and out["rows"]["r1"].quarantine_payload["column"] == "人数"


def test_merged_pool_cell_two_rows_share_one_rectangle_and_both_bind():
    entry, texts = make()
    assert entry["rows"][0]["pool"]["rect"] == entry["rows"][1]["pool"]["rect"]
    assert run(entry, texts)["decision"] == "ACCEPT"


# ---- row 4: same value, another table title -------------------------------------------------------------------------------------------------------------------------------------
def test_row4_title_of_another_table_with_the_same_year_is_refused_by_the_product():
    entry, texts = make()
    entry["year_anchor"]["text"] = "架空大学 別の表 2027年度 入学者選抜 募集人員"
    out = run(entry, texts, geometry=None)
    assert all(v.code == RC.TABLE_TITLE_MISMATCH for v in out["rows"].values()) and out["decision"] == "REFUSE"


def test_row4_title_differing_only_by_one_character_is_refused():
    entry, texts = make()
    entry["year_anchor"]["text"] = TITLE.replace("募集人員", "募集人数")
    assert codes(run(entry, texts, geometry=None)) == RC.TABLE_TITLE_MISMATCH


def test_row4_title_compare_is_by_the_pinned_sha_so_whitespace_and_width_variants_are_the_same_title():
    entry, texts = make()
    entry["year_anchor"]["text"] = "架空大学　架空学部　２０２７年度　入学者選抜　募集人員"  # full-width: NFKC + whitespace removal give the same SHA
    # the PRODUCT compares strings; the adapter hands it the claimed title when the SHA matches the pin, so the same title is accepted
    out = run(entry, texts, geometry=None)
    assert out["decision"] == "ACCEPT"


# ---- row 5: another year / enrollment month, ambiguous multi-year tables ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("extra", ["2026年度 入学者選抜の結果", "令和8年度", "2027年度及び2028年度", "2027〜2028年度", "令和9年度及び令和10年度", "翌年度の募集は別に定める"])
def test_row5_a_second_year_or_range_in_the_title_scope_is_refused(extra):
    entry, texts = make()
    out = run(entry, texts, claim=A.Claim(extra_context=extra), geometry=None)
    assert all(v.code == RC.AMBIGUOUS_MULTI_YEAR for v in out["rows"].values())


def test_row5_title_that_names_another_year_than_the_value_is_refused():
    entry, texts = make()
    title = "架空大学 架空学部 2026年度 入学者選抜 募集人員"
    entry["year_anchor"]["text"] = title
    out = run(entry, texts, p=pins(title_sha256=A.text_sha(title)), geometry=None)
    assert codes(out) == RC.AMBIGUOUS_MULTI_YEAR  # column_year 2026 != expected_year 2027


def test_row5_era_and_western_name_of_the_same_year_are_one_year_and_accepted():
    entry, texts = make()
    title = "架空大学 令和9年度 入学者選抜(2027年4月入学者)"
    entry["year_anchor"]["text"] = title
    assert run(entry, texts, p=pins(title_sha256=A.text_sha(title)), geometry=None)["decision"] == "ACCEPT"


def test_row5_characterization_title_without_any_year_is_accepted_by_the_product_and_refused_by_the_geometry_layer():
    entry, texts = make()
    title = "架空大学 架空学部 入学者選抜 募集人員"
    entry["year_anchor"]["text"] = title
    p = pins(title_sha256=A.text_sha(title))
    out = run(entry, texts, p=p, geometry={**GEO, "page_facts": {**FACTS, "anchor_text_found": title}})
    assert {v.code for v in out["rows"].values()} == {RC.ACCEPTED}  # PRODUCT alone: no year string, no refusal (row 5 only fires on a year it can read)
    assert any(f["code"] == "E-YEAR" and f["level"] == "error" for f in out["geometry"]) and out["decision"] == "REFUSE"  # GEOMETRY layer


def test_row5_same_page_other_year_inside_the_scope_is_refused_by_the_geometry_layer():
    entry, texts = make()
    facts = deepcopy(FACTS)
    facts["years_in_scope"].append({"year": 2026, "rect": [40.0, 300.0, 100.0, 310.0]})
    out = run(entry, texts, geometry={**GEO, "page_facts": facts})
    assert any(f["code"] == "E-YEARCONFLICT" for f in out["geometry"]) and out["decision"] == "REFUSE"


# ---- row 6: primary vs secondary page --------------------------------------------------------------------------------------------------------------------------------------------
def test_row6_secondary_span_on_another_page_than_the_pinned_guide_page_is_refused():
    entry, texts = make()
    out = run(entry, texts, p=pins(guide_page=8), claim=A.Claim(guide_page_claimed=9), geometry=None)
    assert all(v.code == RC.CROSS_SOURCE_MISMATCH for v in out["rows"].values())
    assert run(entry, texts, p=pins(guide_page=8), claim=A.Claim(guide_page_claimed=8), geometry=None)["decision"] == "ACCEPT"


def test_row6_primary_table_on_another_page_than_the_pinned_page_is_refused_row3():
    entry, texts = make()
    entry["page"] = 2
    assert codes(run(entry, texts, geometry=None)) == RC.PAGE_MISMATCH


# ---- row 7: pool replaced after structuring ----------------------------------------------------------------------------------------------------------------------------------------
def test_row7_pool_text_re_read_from_the_source_differs_from_the_structured_record_is_refused():
    entry, texts = make()
    set_text(entry, texts, "r2", "pool", "一般枠")  # a consistent bundle that now says the pool of r2 is the general one
    out = run(entry, texts, claim=A.Claim(source_pool_text={"r2": "女性枠"}), geometry=None)
    assert codes(out, "r2") == RC.POOL_TAMPERED and codes(out, "r0") == RC.ACCEPTED


def test_row7_pool_text_changed_without_recomputing_the_bundle_hash_is_refused_by_the_adapter():
    entry, texts = make()
    texts[("r2", "pool")] = "一般枠"
    out = run(entry, texts)
    assert out["decision"] == "REFUSE" and out["adapter"] and out["adapter"][0][0] == "ADAPTER_TEXT_HASH_MISMATCH" and out["rows"] == {}


def test_row7_pool_swapped_for_a_consistent_bundle_is_refused_by_the_reviewed_profile_pin():
    entry, texts = make()
    set_text(entry, texts, "r2", "pool", "一般枠")
    pinned = {(rid, role): A.text_sha(t) for (rid, role), t in make()[1].items()}
    out = run(entry, texts, p=pins(cell_sha256=pinned))
    assert out["adapter"][0][0] == "ADAPTER_PINNED_CELL_MISMATCH" and "r2/pool" in out["adapter"][0][1]


# ---- row 8: bundle SHA pinned outside ----------------------------------------------------------------------------------------------------------------------------------------------
def _pinned_bundle_shas(entry, texts):
    out = run(entry, texts, geometry=None)
    return {rid: v.quarantine_payload["bundle_sha256"] for rid, v in out["rows"].items()}


def test_row8_a_changed_value_does_not_match_the_externally_pinned_bundle_sha():
    entry, texts = make()
    shas = _pinned_bundle_shas(entry, texts)
    assert run(entry, texts, p=pins(bundle_sha256=shas), geometry=None)["decision"] == "ACCEPT"
    set_text(entry, texts, "r0", "count", "6名", value=6)
    out = run(entry, texts, p=pins(bundle_sha256=shas), geometry=None)
    assert codes(out, "r0") == RC.BUNDLE_HASH_MISMATCH and codes(out, "r1") == RC.ACCEPTED


def test_row8_a_changed_label_does_not_match_the_pinned_bundle_sha():
    entry, texts = make()
    shas = _pinned_bundle_shas(entry, texts)
    set_text(entry, texts, "r1", "label", "方式丁")
    assert codes(run(entry, texts, p=pins(bundle_sha256=shas), geometry=None), "r1") == RC.BUNDLE_HASH_MISMATCH


def test_row8_characterization_the_product_bundle_sha_ignores_rectangles_and_source_sha():
    """The product's bundle SHA covers target_key, value, row_label, column, page, table_title, headers - NOT the cell rectangles, the source SHA or the profile SHA.  A bundle whose rectangles
    moved (same texts) therefore has the SAME product bundle SHA: the pin cannot catch it.  Only the geometry layer can (here: the count leaves its row)."""
    entry, texts = make()
    shas = _pinned_bundle_shas(entry, texts)
    entry["rows"][0]["count"]["rect"] = [450.0, 150.0, 500.0, 190.0]  # now on the row of r1
    entry["source_sha256"] = "c" * 64
    out = run(entry, texts, p=pins(bundle_sha256=shas))
    assert codes(out, "r0") == RC.ACCEPTED  # PRODUCT: the pin still matches
    assert any(f["code"] == "E-ROW" and f["level"] == "error" for f in out["geometry"]) and out["decision"] == "REFUSE"  # GEOMETRY


# ---- row 9: unit / type against the registry ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["0名", "5人", "5.5名", "-5名", "05名", "五名", "５名", "5名※1", "5名/3名", "約5名", "5名以内"])
def test_row9_count_cells_that_are_not_a_positive_integer_with_unit_mei_are_refused(bad):
    entry, texts = make()
    set_text(entry, texts, "r0", "count", bad)
    assert codes(run(entry, texts, geometry=None)) == RC.INVALID_UNIT_OR_TYPE


def test_row9_footnote_marker_inside_the_count_cell_is_a_refusal_not_a_silent_strip():
    entry, texts = make()
    set_text(entry, texts, "r1", "count", "10名＊")
    out = run(entry, texts, geometry=None)
    assert codes(out, "r1") == RC.INVALID_UNIT_OR_TYPE and codes(out, "r0") == RC.ACCEPTED


def test_row9_empty_count_cell_is_refused_never_zero():
    entry, texts = make()
    set_text(entry, texts, "r0", "count", "")
    assert codes(run(entry, texts, geometry=None)) == RC.MISSING_EVIDENCE_CONTEXT


@pytest.mark.parametrize("value", [0, True, "5", 5.0, -1])
def test_row9_bundle_value_that_is_not_a_positive_int_is_refused_by_the_geometry_layer(value):
    entry, texts = make()
    entry["rows"][0]["value"] = value
    out = run(entry, texts)
    assert any(f["code"] == "E-VALUE" and f["level"] == "error" for f in out["geometry"]) and out["decision"] == "REFUSE"


def test_row9_characterization_a_bare_integer_without_the_unit_is_accepted_by_the_product():
    """The registry contract (values.unit == 名) and PR #103's count cell (`\\d+名`) both want the unit; the product's regex makes it optional.  Pinned as the product's present behaviour."""
    entry, texts = make()
    set_text(entry, texts, "r0", "count", "5")
    assert codes(run(entry, texts, geometry=None)) == RC.ACCEPTED


def test_row9_unit_in_the_bundle_values_other_than_mei_is_refused_by_the_geometry_layer():
    entry, texts = make()
    entry["values"]["unit"] = "人"
    assert any(f["code"] == "E-SCOPE" and f["level"] == "error" for f in run(entry, texts)["geometry"])


def test_row9_unregistered_key_is_refused():
    entry, texts = make()
    entry["fact_key"] = "quota_by_category_v2"
    assert codes(run(entry, texts, geometry=None)) == RC.UNKNOWN_SCHEMA_KEY


def test_adopted_fact_key_is_recognised_by_the_product():
    """Decision 3 (STR-138) adopted `admission_unit_quota` (docs/G7_TITLE_SCOPE_AND_FACT_KEY_CONTRACT.md section 6); since PR #416 the product's catalog recognises it (the old provisional name stays accepted).
    Registry registration (fact_keys.json / DB-11) is NOT part of this."""
    entry, texts = make()
    entry["fact_key"] = "admission_unit_quota"
    assert codes(run(entry, texts, geometry=None)) == "ACCEPTED"


# ---- row 10: UNKNOWN granularity ---------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [("category", None), ("category", ""), ("category", "UNKNOWN"), ("selection", "unknown"), ("unit", " ")])
def test_row10_unknown_empty_or_missing_granularity_dimension_is_refused(field, value):
    entry, texts = make()
    entry["values"][field] = value
    out = run(entry, texts, geometry=None)
    assert all(v.code == RC.UNKNOWN_GRANULARITY for v in out["rows"].values())


def test_row10_missing_admission_year_is_refused_by_row5_first_so_it_is_a_refusal_but_not_row_10():
    entry, texts = make()
    entry["values"]["admission_year"] = None
    out = run(entry, texts, geometry=None)
    assert {v.code for v in out["rows"].values()} == {RC.AMBIGUOUS_MULTI_YEAR}  # the title's 2027 != None: order of the matrix, still a refusal


def test_row10_extra_dimension_exam_year_none_is_refused_by_the_product_even_though_the_contract_allows_null_with_reason():
    """CHARACTERIZATION: the contract (section 6) allows exam_year = null + a reason.  The product has no 'null with reason': any None dimension is UNKNOWN_GRANULARITY.  The adapter therefore leaves
    exam_year out unless the caller asks for it; the contract's null-with-reason representation cannot be expressed against the product."""
    entry, texts = make()
    assert run(entry, texts, geometry=None)["decision"] == "ACCEPT"  # exam_year simply not a dimension
    out = run(entry, texts, claim=A.Claim(scope_extra={"exam_year": None}), geometry=None)
    assert codes(out) == RC.UNKNOWN_GRANULARITY


# ---- the other cases named by the contract: merged cells, faculty/scope mismatch, footnote-modified cells --------------------------------------------------------------------------------
def test_merged_pool_borrowed_from_another_row_is_refused_by_the_geometry_layer_and_not_by_the_product():
    entry, texts = make()
    entry["rows"][2]["pool"]["rect"] = [160.0, 110.0, 440.0, 150.0]
    out = run(entry, texts)
    assert any(f["code"] == "E-ROW" for f in out["geometry"] if f["level"] == "error")
    assert codes(out, "r2") == RC.ACCEPTED  # PRODUCT alone has no geometry: it cannot express merged-cell binding (stated in the report)
    assert out["decision"] == "REFUSE"


def test_count_of_another_row_without_vertical_overlap_is_refused_by_the_geometry_layer():
    entry, texts = make()
    entry["rows"][0]["count"]["rect"] = [450.0, 150.0, 500.0, 190.0]
    assert any(f["code"] == "E-ROW" and f["level"] == "error" for f in run(entry, texts)["geometry"])


def test_faculty_total_used_as_a_category_count_is_refused_by_the_geometry_layer_not_by_the_product():
    entry, texts = make()
    set_text(entry, texts, "r0", "count", "112名", value=112)
    out = run(entry, texts)
    assert codes(out) == RC.ACCEPTED  # PRODUCT: 112名 is a positive integer with the unit; it cannot know it is the faculty total
    assert any(f["code"] == "E-VALUE" and f["level"] == "error" for f in out["geometry"]) and out["decision"] == "REFUSE"


def test_adjacent_table_or_enlarged_scope_is_refused_by_the_geometry_layer():
    entry, texts = make()
    out = run(entry, texts, geometry={**GEO, "page_facts": {**FACTS, "table_clusters_in_scope": 2}})
    assert any(f["code"] == "E-SCOPE" for f in out["geometry"]) and out["decision"] == "REFUSE"


def test_footnote_modified_label_is_refused_only_by_the_profile_pinned_cell_hash():
    entry, texts = make()
    pinned = {(rid, role): A.text_sha(t) for (rid, role), t in make()[1].items()}
    set_text(entry, texts, "r0", "label", "方式甲※1")
    plain = run(entry, texts)
    assert codes(plain) == RC.ACCEPTED and plain["decision"] == "ACCEPT"  # PRODUCT + GEOMETRY: a marker inside a label is invisible to both (stated in the report)
    pinned_run = run(entry, texts, p=pins(cell_sha256=pinned))
    assert pinned_run["decision"] == "REFUSE" and pinned_run["adapter"][0][0] == "ADAPTER_PINNED_CELL_MISMATCH"


def test_ruling_overshoot_of_a_word_box_is_a_warning_or_error_by_distance_not_a_silent_pass():
    entry, texts = make()
    assert run(entry, texts)["geometry"] == []  # unchanged geometry stays clean
    entry["rows"][1]["label"]["rect"] = [50.0, 150.0, 150.0, 201.0]  # 11pt past the ruling at 190
    assert any(f["code"] == "E-RULING" and f["level"] == "error" for f in run(entry, texts)["geometry"])


# ---- row 12 + the guards: identical re-submission and the approval path stays closed -------------------------------------------------------------------------------------------------------
@pytest.fixture
def migrated(tmp_path):
    path, _p = S.make_native(tmp_path, "g7.sqlite")
    RevisionStore(path, tmp_path / "g7.backup")
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"]
    with closing(sqlite3.connect(path)) as c:
        qs.register_quarantine_connection_guards(c)
        yield path, c


def _stage(c, entry, texts, rid, staging_id=None, staged_by="adapter_g7_test"):
    out = run(entry, texts)
    res = out["rows"][rid]
    assert res.decision == "ACCEPT"
    pl = A.candidate_payload(entry, texts, rid, res)
    return qs.stage_candidate(c, staging_id or f"stg-{rid}", "src-fiction-1", "PDF_TABLE_CELL", pl["extracted_key"], pl["extracted_value"], staged_by=staged_by)


def test_row12_identical_resubmission_is_idempotent_and_a_conflicting_one_is_refused(migrated):
    _path, c = migrated
    entry, texts = make()
    assert _stage(c, entry, texts, "r0") == "stg-r0"
    assert _stage(c, entry, texts, "r0") == "stg-r0"
    assert c.execute("SELECT count(*) FROM quarantine_staging_candidates").fetchone()[0] == 1
    set_text(entry, texts, "r0", "count", "6名", value=6)
    out = run(entry, texts)
    pl = A.candidate_payload(entry, texts, "r0", out["rows"]["r0"])
    with pytest.raises(sqlite3.IntegrityError):
        qs.stage_candidate(c, "stg-r0", "src-fiction-1", "PDF_TABLE_CELL", pl["extracted_key"], pl["extracted_value"], staged_by="adapter_g7_test")


def test_staged_candidate_is_quarantined_pending_with_no_approval_seal_and_cannot_be_promoted(migrated):
    _path, c = migrated
    entry, texts = make()
    for rid in ("r0", "r1", "r2"):
        _stage(c, entry, texts, rid)
    rows = c.execute("SELECT quarantine_status, review_status, approved_by, approval_token FROM quarantine_staging_candidates").fetchall()
    assert rows == [("QUARANTINED", "PENDING", None, None)] * 3
    assert c.execute("SELECT count(*) FROM _quarantine_approval_seals").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM canonical_facts_staging_target").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        qs.promote_candidate(c, "stg-r0", fact_id="f-0")
    with pytest.raises(sqlite3.IntegrityError):  # the canonical mirror cannot be written around the quarantine
        c.execute("INSERT INTO canonical_facts_staging_target(fact_id, staging_id, key, value, promoted_at) VALUES('f-x','stg-r0','k','v','t')")
    payload = json.loads(c.execute("SELECT extracted_value FROM quarantine_staging_candidates WHERE staging_id='stg-r1'").fetchone()[0])
    assert payload["value"] == 10 and set(payload["cells"]) == {"label", "pool", "count"} and "方式乙" not in json.dumps(payload, ensure_ascii=False)  # hashes and positions only


def test_a_refused_row_is_never_staged_by_the_helper(migrated):
    _path, c = migrated
    entry, texts = make()
    set_text(entry, texts, "r0", "count", "0名")
    with pytest.raises(AssertionError):
        _stage(c, entry, texts, "r0")
    assert c.execute("SELECT count(*) FROM quarantine_staging_candidates").fetchone()[0] == 0


# ---- helpers of scripts/g7_new_format_probe.py (synthetic items; the probe itself runs on the local original and is not a test) -----------------------------------------------------------------
def _probe():
    spec = importlib.util.spec_from_file_location("g7_new_format_probe", Path(__file__).resolve().parent.parent / "scripts" / "g7_new_format_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_probe_cell_text_reads_vertical_rtl_columns_right_to_left_and_top_to_bottom():
    P = _probe()
    # two columns of two glyphs: right column "ab", left column "cd"
    items = [(90.0, 10.0, 10.0, 10.0, "a"), (90.0, 22.0, 10.0, 10.0, "b"), (70.0, 10.0, 10.0, 10.0, "c"), (70.0, 22.0, 10.0, 10.0, "d"), (300.0, 300.0, 10.0, 10.0, "z")]
    assert P.cell_text(items, (60.0, 0.0, 100.0, 40.0), "vertical-rtl") == "abcd"
    assert P.cell_text(items, (0.0, 0.0, 5.0, 5.0), "horizontal") == ""


def test_probe_agreement_counts_pairs_and_the_three_way_equality():
    P = _probe()
    per = {"x": {1: "a", 2: "b", 3: "c"}, "y": {1: "a", 2: "b", 3: "d"}, "z": {1: "a", 2: "q", 3: "d"}}
    st = P.agree_stats(per, [1, 2, 3])
    assert st["x~y"] == {"agree": 2, "of": 3} and st["y~z"] == {"agree": 2, "of": 3} and st["x~z"] == {"agree": 1, "of": 3} and st["all_three_equal"] == {"agree": 1, "of": 3}
