"""Manual QA run of the g6 simulated old->new end-to-end on a COPY of the pinned real v06 file (not collected by default: no test_ prefix).

Run:  python -m pytest tests/qa_g6_sim_e2e_real_clone.py -q -p no:cacheprovider
The pinned file must exist; this file FAILS (it never skips) when it is missing. The pinned file is only read (copied).
"""
import shutil

from src.db_contract import additive_schema as ad
from scripts import g6_sim_e2e as e2e
from tests.test_m1_g6_sim_e2e import PINNED, PINNED_SHA, _sha


def test_real_v06_clone_old_to_simulated_new_edition(tmp_path):
    assert PINNED.exists(), "the pinned real v06 file is required for this manual QA run"
    """The REAL data shape: the pinned v06 file COPIED to a temporary directory, migrated 0002..0014 on the copy, then the end-to-end run. SIMULATED new edition; SELF_TEST."""
    assert _sha(PINNED) == PINNED_SHA
    copy = tmp_path / "clone.sqlite"
    shutil.copyfile(PINNED, copy)
    r = ad.apply(copy, confirm_disposable_copy=True)
    assert not r["rolled_back"] and len(r["applied"]) == 13 and r["applied"][-1] == "0014-g06-source-series"
    out = e2e.run(copy, evidence_id="EV-T27-01-49cb4d")
    assert out["all_checks_pass"], [k for k, v in out["checks"].items() if not v]
    assert out["old_edition"]["pages"] == 15 and out["new_edition"]["pages"] == 16
    assert out["simulated_change"] == {"evidence_id": "EV-T27-01-49cb4d", "page": 5, "old_number": "5", "new_number": "6"}
    d = out["diff"]
    assert (d["pages_added"], d["pages_changed"], d["changed_lines"], d["value_changes"]) == (1, 1, 1, 1)
    i = out["impact"]
    s = i["summary"]
    assert (s["evidence"], s["evidence_value_change"], s["evidence_page_changed"], s["evidence_intact"], s["evidence_unassessed"]) == (55, 1, 4, 44, 6)
    assert i["articles_total"] == 6 and i["class_counts"] == {"revision_candidate": 1, "review_same_page": 1, "not_flagged": 4}
    assert i["evidence_flagged_republish"] == i["oracle_evidence"] == ["EV-T27-01-49cb4d"]
    assert len(i["articles_flagged"]) == 1 and i["articles_flagged"] == i["oracle_articles"] and i["articles_flagged"][0].startswith("tsukuba-klis-ac-2027:overview:")
    assert all(a.startswith(("keio-", "tsukuba-klis-general-front-")) for a in i["articles_not_flagged"]) and len(i["articles_not_flagged"]) == 4
    assert len(i["articles_review_same_page"]) == 1 and i["articles_review_same_page"][0].startswith("tsukuba-klis-ac-2027:interview:")
    assert out["old_tables"]["unchanged"] and out["old_tables"]["count"] == 41 and out["old_tables"]["rows_total"] == 930
    assert all(g["refused"] for g in out["guards"]) and len(out["guards"]) == 7
    assert _sha(PINNED) == PINNED_SHA  # the real file was only ever read (copied)
