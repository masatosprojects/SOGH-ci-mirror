"""Manual QA run of the g6 REAL old->new pair on a COPY of the pinned real v06 file (not collected by default: no test_ prefix).

Run:  python -m pytest tests/qa_g6_real_pair_real_clone.py -q -p no:cacheprovider
Needs the pinned v06 file and the official previous-edition PDF; this file FAILS (it never skips) when either is missing. Both are only read.
"""
import shutil
from pathlib import Path

from scripts import g6_real_pair_e2e as rp
from src.db_contract import additive_schema as ad
from tests.test_m1_g6_sim_e2e import PINNED, PINNED_SHA, _sha

OLD_PDF = Path(r"C:\Users\USER\sogh-c-tmp\g6real\AC-2026-youkou_sec.pdf")
OLD_PDF_SHA = "81a8635f855ce0cbb475c4b04cb22aa89f40cd8cf1ec10f744e8801aee39f571"


def test_real_pair_tsukuba_ac_reiwa8_to_reiwa9(tmp_path):
    assert PINNED.exists(), "the pinned real v06 file is required for this manual QA run"
    assert OLD_PDF.exists(), "the official previous-edition PDF is required for this manual QA run"
    assert _sha(PINNED) == PINNED_SHA and _sha(OLD_PDF) == OLD_PDF_SHA
    copy = tmp_path / "clone.sqlite"
    shutil.copyfile(PINNED, copy)
    r = ad.apply(copy, confirm_disposable_copy=True)
    assert not r["rolled_back"] and r["applied"][-1] == "0014-g06-source-series"
    out = rp.run(copy, rp.extract_pdf_pages(OLD_PDF), "49cb4d7d", OLD_PDF_SHA, OLD_PDF.name)
    assert out["all_checks_pass"], [k for k, v in out["checks"].items() if not v]
    o, i = out["oracle"], out["impact"]
    assert out["old_edition"]["pages"] == 15 and out["new_edition"]["pages"] == 15
    assert (o["new_edition_evidence"], o["proofs"], o["proofs_unchanged"], o["proofs_moved"], o["proofs_changed"]) == (14, 19, 12, 1, 6)
    assert o["evidence_changed"] == i["evidence_flagged_republish"] and len(o["evidence_changed"]) == 5
    assert i["articles_flagged"] == o["articles_by_text"] == o["articles_by_table"] and len(i["articles_flagged"]) == 2
    assert i["class_counts"] == {"revision_candidate": 2, "review_same_page": 0, "not_flagged": 4}
    assert i["proof_mismatches"] == [] and len(out["real_changes"]) == 6
    d = out["diff"]
    assert (d["pages_added"], d["pages_removed"], d["pages_changed"], d["changed_lines"], d["value_changes"]) == (3, 3, 11, 27, 20)
    assert all(g["refused"] for g in out["guards"]) and len(out["guards"]) == 7 and out["old_tables"]["unchanged"]
    assert _sha(PINNED) == PINNED_SHA and _sha(OLD_PDF) == OLD_PDF_SHA
