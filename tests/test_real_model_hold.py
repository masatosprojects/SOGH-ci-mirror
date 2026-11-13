"""The user's hold on real-model runs (research/antigravity-local-ai/HOLD_REAL_MODEL_RUN.txt): the three entry points stop before starting anything while the file exists.
No model, no sensor, no process of llama is started by these tests."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AG = REPO / "research" / "antigravity-local-ai"
HOLD = AG / "HOLD_REAL_MODEL_RUN.txt"


def test_the_hold_file_exists_and_explains_who_may_lift_it():
    text = HOLD.read_text(encoding="utf-8")
    assert "ON HOLD" in text and "Lift: only the user" in text


def test_the_python_entry_points_stop_with_exit_code_3_and_start_nothing():
    for name in ("standalone_production_runner.py", "evaluate_real_model_grounding.py"):
        r = subprocess.run([sys.executable, "-B", str(AG / "scripts" / name)], cwd=AG, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 3, (name, r.stdout[-300:], r.stderr[-300:])
        assert "ON HOLD" in r.stdout and "Nothing was started" in r.stdout
        assert "Executing" not in r.stdout and "Current Physical RAM" not in r.stdout      # it never reached the RAM / thermal / launch steps


def test_the_batch_launcher_checks_the_hold_before_anything_else():
    lines = [ln.strip().lower() for ln in (REPO / "run_standalone_inference.bat").read_text(encoding="utf-8").splitlines() if ln.strip()]
    first_action = [i for i, ln in enumerate(lines) if "hwinfo" in ln or "python" in ln or ln.startswith("start ")][0]
    hold_check = [i for i, ln in enumerate(lines) if "hold_real_model_run.txt" in ln][0]
    assert hold_check < first_action and any("exit /b 3" in ln for ln in lines[hold_check:first_action])


def test_the_batch_launcher_checks_the_real_hold_file_path_and_has_no_control_characters():
    import re
    raw = (REPO / "run_standalone_inference.bat").read_bytes()
    assert not [c for c in raw if c < 32 and c not in (9, 10, 13)]          # a stray  (BEL) once turned the path into a wrong one
    m = re.search(rb'if exist "%~dp0([^"]+HOLD_REAL_MODEL_RUN\.txt)"', raw)
    assert m, "the launcher must test for the hold file first"
    assert (REPO / m.group(1).decode("ascii").replace("\\", "/")).resolve() == HOLD.resolve()

