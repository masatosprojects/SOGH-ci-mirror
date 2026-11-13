"""The fact_key adopted on 2026-11-13 (STR-138 decision 3) must be recognised by the quarantine staging product, and its value rules must apply to it."""
from src.db_contract.quarantine_staging import RefusalCode, evaluate_table_cell_format


def table(key, value="25"):
    return {
        "headers": ["学科", "募集人員"],
        "rows": [["物理学科", value]],
        "context_text": "2027年度入学者選抜 募集人員",
        "target_key": key,
        "raw_cell_value": value,
        "row_label": "物理学科",
        "column": "募集人員",
    }


def test_the_adopted_key_is_recognised_and_a_valid_quota_is_accepted():
    r = evaluate_table_cell_format(table("admission_unit_quota"))
    assert r.decision == "ACCEPT" and r.code == RefusalCode.ACCEPTED


def test_the_value_rules_apply_to_the_adopted_key():
    for bad in ("0", "十名", "12.5", "-3", "15人", "約15"):
        r = evaluate_table_cell_format(table("admission_unit_quota", bad))
        assert (r.decision, r.code) == ("REFUSE", RefusalCode.INVALID_UNIT_OR_TYPE), bad
    assert evaluate_table_cell_format(table("admission_unit_quota", "25名")).decision == "ACCEPT"


def test_the_earlier_working_name_is_still_accepted_for_existing_bundles():
    assert evaluate_table_cell_format(table("admission_category_quota")).decision == "ACCEPT"


def test_other_unknown_keys_are_still_refused():
    for key in ("admission_quota_by_category", "unit_quota", "quota_unit"):
        r = evaluate_table_cell_format(table(key))
        assert (r.decision, r.code) == ("REFUSE", RefusalCode.UNKNOWN_SCHEMA_KEY), key
