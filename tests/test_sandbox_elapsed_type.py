"""The elapsed time of an answer must be a real integer number of seconds. A bool is an int in Python (True == 1), so `isinstance(x, int)` let `True` advance the clock by one second.
Found by Work (Issue #75, Stage 0 design review) and reproduced on master. SYNTHETIC_ONLY. Regression tests: the same input must now be refused, and nothing else about the boundary changes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox.cases import CASES  # noqa: E402
from interview_sandbox.engine import InterviewSession  # noqa: E402

ANSWER = "探究活動で地域の課題を調べました。"


def started():
    s = InterviewSession(CASES["fiction-ac-1"]())
    s.start()
    return s


@pytest.mark.parametrize("bad", [True, False, 1.0, 20.5, "20", None, [20]], ids=repr)
def test_a_non_integer_elapsed_time_is_refused_and_changes_nothing(bad):
    s = started()
    before = (s.remaining_seconds, len(s.turns), s.state)
    with pytest.raises(ValueError, match="elapsed_seconds"):
        s.answer(s._open.turn_id, ANSWER, bad)
    assert (s.remaining_seconds, len(s.turns), s.state) == before


@pytest.mark.parametrize("bad", [-1, 3601])
def test_an_out_of_range_integer_is_still_refused(bad):
    s = started()
    with pytest.raises(ValueError, match="elapsed_seconds"):
        s.answer(s._open.turn_id, ANSWER, bad)


@pytest.mark.parametrize("good", [0, 1, 20, 3600])
def test_a_real_integer_in_range_is_still_accepted(good):
    s = started()
    r = s.answer(s._open.turn_id, ANSWER, good)
    assert r.accepted
