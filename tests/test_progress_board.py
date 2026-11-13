"""The development progress board: one data file, three generated documents, and rules that stop it from flattering the project."""
import copy
import json
import re

import pytest

from src.db_contract import progress as pg

DATA = pg.load()


def test_the_data_file_is_valid_and_the_generated_documents_are_current():
    assert pg.validate(DATA) == []
    for key, path in pg.OUTPUTS.items():
        assert path.exists(), path
        assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == pg.RENDERERS[key](DATA), f"{path.name} is stale: python -m src.db_contract.progress --write"


def test_every_process_p0_to_p10_and_db_area_1_to_7_is_present():
    assert [p["id"] for p in DATA["processes"]] == [f"P{i}" for i in range(11)]
    assert [a["id"] for a in DATA["db_areas"]] == [f"DB-{i}" for i in range(1, 8)]
    assert [m["id"] for m in DATA["milestones"]] == [f"M{i}" for i in range(1, 6)]
    assert sum(len(p["work_packages"]) for p in DATA["processes"]) >= 50


def test_every_work_package_has_every_required_field_and_a_known_state():
    for p in DATA["processes"]:
        for wp in p["work_packages"]:
            assert all(f in wp for f in pg.WP_FIELDS), wp["id"]
            assert wp["state"] in DATA["states"] and wp["positive_tests"] and wp["negative_tests"], wp["id"]


def test_progress_counts_only_verified_criteria_with_evidence_never_tests_or_prs():
    m = pg.metrics(DATA)
    for p in DATA["processes"]:
        verified = sum(1 for c in p["criteria"] if c["verified"] and c["evidence"])
        assert m["processes"][p["id"]]["verified"] == verified and m["processes"][p["id"]]["total"] == len(p["criteria"])
    text = json.dumps(DATA, ensure_ascii=False)
    assert "テスト成功" not in "".join(pg.render_progress(DATA).splitlines()[:5])  # the header never presents a test count as progress
    assert "%" in pg.render_progress(DATA) and "件のテスト" not in pg.render_progress(DATA)
    assert "percent" not in text  # the percentage is computed, not typed in


def test_m1_gates_are_all_accepted_by_the_user_but_no_db_area_claims_operational_use():
    m = pg.metrics(DATA)
    # 2026-11-01: g8 (Claude can recompute Work's real-copy results) and g4 (the update path survives faults on real copies) have real-copy evidence; every other gate is still open
    # 2026-11-13: g1, g2, g3, g5, g6, g7 were accepted by the user one by one (each with its stated scope) after g4 and g8; M1 is complete as defined by the gates
    assert m["m1"] == {"verified_gates": 8, "gates": 8, "complete": True}
    assert [g["id"] for g in DATA["m1_gates"] if g["verified"]] == ["M1.g1", "M1.g2", "M1.g3", "M1.g4", "M1.g5", "M1.g6", "M1.g7", "M1.g8"]
    assert all(a["dimensions"]["real_data"]["v"] != "yes" and a["dimensions"]["operational"]["v"] == "no" for a in DATA["db_areas"])
    dash = pg.render_dashboard(DATA)
    assert "達成 **8／8**" in dash and "M1 は未達成" not in dash


def broken(mutate):
    data = copy.deepcopy(DATA)
    mutate(data)
    return pg.validate(data)


def test_a_criterion_cannot_be_verified_without_evidence():
    assert any("without evidence" in p for p in broken(lambda d: d["processes"][0]["criteria"][0].update(verified=True)))


def test_a_work_package_cannot_be_accepted_without_evidence_or_operational_before_p9():
    def accept(d):
        wp = d["processes"][0]["work_packages"][0]
        wp.update(state="accepted", evidence="")
    assert any("accepted without evidence" in p for p in broken(accept))
    assert any("operational is only possible" in p for p in broken(lambda d: d["processes"][2]["work_packages"][0].update(state="operational", evidence="x")))


def test_real_data_cannot_be_yes_on_synthetic_or_sample_evidence():
    assert any("real database" in p for p in broken(lambda d: d["db_areas"][0]["dimensions"]["real_data"].update(v="yes", e="tests (synthetic) and repository_sample")))
    assert not any("real_data" in p for p in broken(lambda d: d["db_areas"][0]["dimensions"]["real_data"].update(v="yes", e="copied_real_db audit report")))


def test_an_m1_gate_cannot_be_verified_without_real_data_evidence():
    assert any("M1.g1" in p for p in broken(lambda d: d["m1_gates"][0].update(verified=True, evidence="合成DBで合格")))


def test_a_process_without_criteria_or_a_wp_with_a_missing_field_or_dependency_is_rejected():
    assert any("no acceptance criteria" in p for p in broken(lambda d: d["processes"][3].update(criteria=[])))
    assert any("missing fields" in p for p in broken(lambda d: d["processes"][1]["work_packages"][0].pop("negative_tests")))
    assert any("unknown" in p for p in broken(lambda d: d["processes"][1]["work_packages"][0].update(inputs=["P99-WP9.9"])))


def test_unknown_state_and_operational_without_real_data_are_rejected():
    assert any("unknown state" in p for p in broken(lambda d: d["processes"][1]["work_packages"][0].update(state="done")))
    def op(d):
        d["db_areas"][0]["dimensions"]["operational"].update(v="yes", e="x")
    assert any("operational: cannot be yes" in p for p in broken(op))


def test_the_cli_check_passes_on_the_committed_documents():
    assert pg.main(["--check"]) == 0


# ---- the numbers of the documents and of the final report are the same string, from the same file
def test_the_one_line_summary_is_in_the_progress_document_and_matches_the_metrics():
    summary = pg.summary_text(DATA)
    assert summary in pg.OUTPUTS["progress"].read_text(encoding="utf-8")
    m = pg.metrics(DATA)
    assert f"M1 {m['m1']['verified_gates']}/{m['m1']['gates']}" in summary
    for pid, x in m["processes"].items():
        assert f"{pid}:{x['verified']}/{x['total']}" in summary
    for aid, x in m["db_areas"].items():
        assert f"{aid}:{x['yes']}/7" in summary


def test_the_dashboard_table_and_the_summary_agree_for_every_db_area():
    dash = pg.OUTPUTS["dashboard"].read_text(encoding="utf-8")
    for a in DATA["db_areas"]:
        assert f"| {a['id']} {a['name']} |" in dash and f"{pg.metrics(DATA)['db_areas'][a['id']]['yes']}／7" in dash


def test_each_m1_gate_states_what_exists_what_is_missing_and_who_acts_next():
    assert len(DATA["m1_gates"]) == 8
    for g in DATA["m1_gates"]:
        assert all(g[f] for f in pg.GATE_FIELDS), g["id"]
        if g["verified"]:  # a verified gate cites the committed independent audit of the real copies, and that file exists
            cited = re.findall(r"reports/db-audit/real_copy_[\w.-]+\.json", g["evidence"])
            assert cited and all((pg.REPO / c).is_file() for c in cited), g["id"]
        else:  # an open gate never claims that the real-database run is done
            assert g["work_real_db"].startswith("未"), g["id"]
    dash = pg.OUTPUTS["dashboard"].read_text(encoding="utf-8")
    for label in pg.GATE_LABEL.values():
        assert label in dash


def test_a_gate_missing_a_field_or_claiming_a_real_run_without_being_verified_is_rejected():
    assert any("missing gate fields" in p for p in broken(lambda d: d["m1_gates"][0].pop("audit_method")))
    def claim_a_run_on_an_unverified_gate(d):  # take a gate, make it unverified, then let it claim a real run: the board must reject it
        g = d["m1_gates"][0]
        g["verified"] = False
        g.update(work_real_db="実施済み")

    assert any("does not say it was not run" in p for p in broken(claim_a_run_on_an_unverified_gate))


def test_p0_decision_is_recorded_but_the_publication_process_is_not_called_complete():
    p0 = next(p for p in DATA["processes"] if p["id"] == "P0")
    assert next(c for c in p0["criteria"] if c["id"] == "P0.c3")["verified"] is True
    wp = next(w for w in p0["work_packages"] if w["id"] == "P0-WP0.3")
    assert wp["state"] == "design" and "実装" in wp["unverified"]  # the decision is made; implementation is not
    p7 = next(p for p in DATA["processes"] if p["id"] == "P7")
    assert sum(1 for c in p7["criteria"] if c["verified"]) <= 3 and pg.metrics(DATA)["processes"]["P7"]["percent"] < 50
    others = [next(c for c in p0["criteria"] if c["id"] == i) for i in ("P0.c1", "P0.c2", "P0.c4")]
    assert not any(c["verified"] for c in others)  # readers, display rules and budget were NOT decided here


def test_the_v0_2_preservation_decision_is_recorded_and_no_migration_is_planned():
    p2 = next(p for p in DATA["processes"] if p["id"] == "P2")
    assert next(c for c in p2["criteria"] if c["id"] == "P2.c10")["verified"] is True
    g5 = next(g for g in DATA["m1_gates"] if g["id"] == "M1.g5")
    assert "保留" in g5["current_implementation"]  # the v0.2 preservation stands; g5 was accepted on 2026-11-13 for the v06 chain only (v0.2 migration excluded)
    assert g5["verified"] is True and "旧 v0.2 の移行は含まない" in g5["evidence"]
