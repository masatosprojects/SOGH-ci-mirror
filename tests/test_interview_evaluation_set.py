"""The human-evaluation set of the interview sandbox: invented scripts, a rating sheet that is blank on purpose, and an agreement measure that refuses to produce a number without human ratings.
SYNTHETIC_ONLY. A pass here is not a human evaluation: nobody has rated anything."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from evaluation import evalset as ev  # noqa: E402
from interview_sandbox import guards  # noqa: E402
from interview_sandbox.feedback import NOT_ENOUGH, RUBRIC, STAGES  # noqa: E402


def test_every_script_runs_deterministically_through_the_mock_and_covers_different_situations():
    assert set(ev.SCRIPTS) >= {"concrete", "vague", "short", "no_reason", "personal_topic", "general_practice"}
    for name in ev.SCRIPTS:
        a, b = ev.run_script(name), ev.run_script(name)
        assert a.transcript == b.transcript and a.stages == b.stages and set(a.stages) == {k for k, _ in RUBRIC}
    concrete, vague = ev.run_script("concrete").stages, ev.run_script("vague").stages
    assert concrete["specificity"] == STAGES[2] and vague["specificity"] == STAGES[0]  # the scripts really differ in what the rubric looks at


def test_the_rating_sheet_is_blank_for_the_raters_and_carries_the_limits():
    sheet = ev.rating_sheet()
    assert all(name in sheet for name in ev.SCRIPTS) and "評価者の記入" in sheet and "練習用の目安" in sheet and "同意を得た人に限り" in sheet
    rows = [ln for ln in sheet.splitlines() if ln.startswith("| F:") or ln.startswith("| A ") or ln.startswith("| E ")]
    assert rows and all(ln.split("|")[2].strip() == "" for ln in rows)  # the rater's cell is empty: nothing is pre-filled
    assert guards.forbidden_claims_in(sheet) == []


def test_without_a_human_rating_no_agreement_number_is_produced():
    r = ev.agreement({}, ev.mock_cells())
    assert r["status"] == "not_run" and "exact" not in r
    only_unjudged = ev.agreement({("vague", "clarity"): "判定できない"}, ev.mock_cells())
    assert only_unjudged["status"] == "not_run" and only_unjudged["left_out_cells"] == 1  # not judged is neither a match nor a miss


def test_the_agreement_counts_exact_and_within_one_stage_and_leaves_out_what_could_not_be_judged():
    mock = {("s", "a"): STAGES[2], ("s", "b"): STAGES[0], ("s", "c"): STAGES[1], ("s", "d"): NOT_ENOUGH}
    human = {("s", "a"): STAGES[2], ("s", "b"): STAGES[1], ("s", "c"): STAGES[1], ("s", "d"): STAGES[0], ("t", "a"): STAGES[0]}  # (t, a) was not rated by the mock
    r = ev.agreement(human, mock)
    assert r["status"] == "measured" and r["cells"] == 3 and abs(r["exact"] - 2 / 3) < 1e-9 and r["within_one_stage"] == 1.0 and r["left_out_cells"] == 1
    assert "not a validation" in r["caution"]
    far = ev.agreement({("s", "a"): STAGES[0]}, {("s", "a"): STAGES[2]})
    assert far["exact"] == 0.0 and far["within_one_stage"] == 0.0
