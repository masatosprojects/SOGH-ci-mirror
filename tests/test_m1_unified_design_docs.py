"""The unified design documents must keep their honesty rules: nothing is approved by them, the findings and their reproductions exist, and the freeze verdict is not an approval."""
import re
from pathlib import Path

ARCH = Path(__file__).resolve().parents[1] / "docs" / "architecture"
NAMES = ["M1_UNIFIED_DATA_ARCHITECTURE_RFC", "M1_DESIGN_DECISION_MATRIX", "M1_SAFE_MIGRATION_PLAN", "M1_FINAL_APPROVAL_ITEMS"]
TEXT = {n: (ARCH / f"{n}.md").read_text(encoding="utf-8") for n in NAMES}
REPO = Path(__file__).resolve().parents[1]


def test_the_documents_exist_and_none_claims_user_or_work_approval():
    for n, t in TEXT.items():
        assert "SELF_VALIDATED" in t or "USER_DECISION_REQUIRED" in t, n
        assert "許可ではない" in t or "承認ではない" in t, n
    items = TEXT["M1_FINAL_APPROVAL_ITEMS"]
    assert "DESIGN_FREEZE_READY" in items and "ユーザーの判断の記録（2026-11-01）" in items and "推奨どおり承認" in items
    assert "Work の独立レビューは**まだ**受けていない" in TEXT["M1_UNIFIED_DATA_ARCHITECTURE_RFC"]
    assert "受容そのものはまだ成立していない" in items and "鍵の作成・配布" in items and "PR #72 のマージ" in items


def test_the_twelve_invariants_and_the_seven_findings_are_all_present():
    rfc = TEXT["M1_UNIFIED_DATA_ARCHITECTURE_RFC"]
    for i in range(1, 13):
        assert f"| {i:02d} |" in rfc, i
    for d in range(1, 9):
        assert f"D{d}" in rfc, d
    assert "未達" in rfc and "条件付き" in rfc and "完全保証" not in rfc.replace("「追記専用を完全保証」とは書かない", "")


def test_every_finding_names_a_reproducing_test_that_exists():
    rfc = TEXT["M1_UNIFIED_DATA_ARCHITECTURE_RFC"]
    tests = (REPO / "tests" / "test_unified_design_falsification.py").read_text(encoding="utf-8")
    names = set(re.findall(r"def (test_\w+)\(", tests))
    for frag in re.findall(r"`(?:test_)?(…[\w_…]+|test_[\w_…]+)`", rfc):
        key = frag.replace("…", "").replace("test_", "")
        assert key == "" or any(key.split("…")[0] in n for n in names), frag
    for must in ("test_fixed_d1_a_head_cannot_point_at_an_unapproved_candidate_revision_not_even_with_the_capability", "test_fixed_d4_insert_or_replace_cannot_overwrite_append_only_tables_approved_batches_or_article_versions"):
        assert must in names


def test_the_decision_matrix_uses_only_the_defined_states_and_the_approval_items_keep_the_prohibitions():
    states = set(re.findall(r"`(TECHNICALLY_RESOLVED|PROVISIONALLY_FROZEN|WORK_REVIEW_PENDING|USER_DECISION_REQUIRED|NOT_RESOLVED)`", TEXT["M1_DESIGN_DECISION_MATRIX"]))
    assert states == {"TECHNICALLY_RESOLVED", "PROVISIONALLY_FROZEN", "WORK_REVIEW_PENDING", "USER_DECISION_REQUIRED", "NOT_RESOLVED"}
    items = TEXT["M1_FINAL_APPROVAL_ITEMS"]
    for needle in ("F-2", "有効化を保留のまま", "PR #64", "自動受容はしない", "運用DBの変更"):
        assert needle in items, needle


def test_the_plan_forbids_applying_before_review_and_orders_the_work_code_change_before_the_database_side():
    plan = TEXT["M1_SAFE_MIGRATION_PLAN"]
    assert "禁止中" in plan and "段 2 より前に必須" in plan and "適用前に統一して再発行" in plan
    assert not re.search(r"[A-Za-z]:[\/]|Users|maruy", "".join(TEXT.values()))
