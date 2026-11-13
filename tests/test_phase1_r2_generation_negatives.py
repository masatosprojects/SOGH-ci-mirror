"""Independent negatives for R2 (generation and replay) and proof that they have teeth.
See docs/realtime-interview/PHASE1_MINIMAL_CONTRACTS_R1_R8.md (R2). SYNTHETIC_ONLY, no I/O, no sockets, no files.

Why this file exists: the first R2 reference tests had ONE generation case (an older generation is refused). A mutation run showed what that leaves open:
  - a check moved before the key lookup (a replay after an interruption is refused instead of acknowledged: Work's W-2),
  - `!=` weakened to `<` (a NEWER generation is accepted),
  - `True` / `1.0` accepted as generation 1,
  - a refusal remembered as if it were a success,
  - a refusal that leaves no error event.
Each check below is written once (`check_*`) and used twice: directly against the reference ledger, and against deliberately broken copies of it (mutants).
A mutant that no check catches would fail `test_every_mutant_is_caught_by_the_check_written_for_it`: a passing suite cannot hide a removed or weakened generation check.
The mutants are built from the reference's own source and each anchor is asserted to exist exactly once, so a refactor cannot silently turn a mutant into a no-op.
Passing accepts nothing: M1 stays 2/8, NOT ACCEPTED. These checks target the REFERENCE; Work's controller is reviewed against the same cases."""
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox"))
sys.dont_write_bytecode = True

from tests import phase1_reference as R  # noqa: E402


def command(**kw):
    base = {"idempotency_key": "k1", "session_id": "s1", "turn_id": "t2", "generation_id": 1, "text": "回答", "elapsed_seconds": 5}
    base.update(kw)
    return base


def accepting(calls):
    def accept(cmd):
        calls.append(cmd["idempotency_key"])
        return True

    return accept


def _error_codes(ledger):
    return [e["code"] for e in ledger.events if e["kind"] == "error"]


# ---------------------------------------------------------------- the checks (each takes the ledger class to test)
def check_a_newer_generation_is_refused_as_well_as_an_older_one(L):
    ledger, calls = L("s1"), []
    out = ledger.commit(command(generation_id=2), accepting(calls))  # the current generation is 1: 2 is from the future
    assert out == {"ok": False, "reason": "stale_generation"} and calls == []
    ledger.new_generation()  # now 2
    assert ledger.commit(command(idempotency_key="k2", generation_id=3), accepting(calls))["reason"] == "stale_generation" and calls == []


def check_a_missing_generation_is_refused(L):
    ledger, calls = L("s1"), []
    cmd = command()
    del cmd["generation_id"]
    assert ledger.commit(cmd, accepting(calls)) == {"ok": False, "reason": "stale_generation"} and calls == []


def check_only_an_int_equal_to_the_current_generation_passes(L):
    for bad in (True, 1.0, "1", None, [1]):  # True == 1 and 1.0 == 1 in Python: neither may count as generation 1
        ledger, calls = L("s1"), []
        out = ledger.commit(command(generation_id=bad), accepting(calls))
        assert out == {"ok": False, "reason": "stale_generation"} and calls == [], repr(bad)
    ledger, calls = L("s1"), []
    assert ledger.commit(command(generation_id=1), accepting(calls))["ok"]  # the plain int 1 is accepted: the check is not simply refusing everything


def check_a_replay_after_the_generation_moved_is_acknowledged_with_the_first_result(L):
    ledger, calls = L("s1"), []
    first = ledger.commit(command(), accepting(calls))
    ledger.new_generation()  # an interruption: the question moved on after the answer was committed
    again = ledger.commit(command(), accepting(calls))
    assert first["ok"] and again["ok"] and again["replayed"] is True and again["seq"] == first["seq"]
    assert calls == ["k1"] and len(ledger.events) == 1  # not applied twice, and no error event for an acknowledged replay


def check_an_unregistered_old_generation_stays_refused_after_the_generation_moved(L):
    ledger, calls = L("s1"), []
    ledger.commit(command(), accepting(calls))
    ledger.new_generation()
    out = ledger.commit(command(idempotency_key="k9", turn_id="t3"), accepting(calls))  # a NEW key still carrying generation 1
    assert out == {"ok": False, "reason": "stale_generation"} and calls == ["k1"]


def check_the_same_key_with_a_different_generation_is_a_conflict_not_a_replay(L):
    ledger, calls = L("s1"), []
    ledger.commit(command(), accepting(calls))
    ledger.new_generation()
    out = ledger.commit(command(generation_id=2), accepting(calls))  # same key, same text, but the payload (which includes generation_id) differs
    assert out == {"ok": False, "reason": "idempotency_conflict"} and calls == ["k1"]
    assert ledger.commit(command(), accepting(calls))["replayed"] is True  # the first result still stands


def check_a_stale_refusal_is_not_remembered_as_a_success(L):
    ledger, calls = L("s1"), []
    ledger.new_generation()
    assert ledger.commit(command(idempotency_key="k5", generation_id=1), accepting(calls))["reason"] == "stale_generation"
    again = ledger.commit(command(idempotency_key="k5", generation_id=1), accepting(calls))
    assert again == {"ok": False, "reason": "stale_generation"}  # refused again, not "replayed"
    fixed = ledger.commit(command(idempotency_key="k5", generation_id=2), accepting(calls))  # the sender corrects the generation and sends the same key
    assert fixed["ok"] and fixed["replayed"] is False and calls == ["k5"]


def check_a_stale_refusal_appends_one_bounded_error_event_and_the_log_stays_contiguous(L):
    ledger, calls = L("s1"), []
    ledger.new_generation()
    ledger.commit(command(generation_id=1), accepting(calls))
    assert _error_codes(ledger) == ["stale_generation"] and calls == [] and ledger.seqs_are_contiguous()
    for i in range(R.MAX_ERROR_EVENTS + 20):
        ledger.commit(command(idempotency_key=f"f{i}", generation_id=1), accepting(calls))
    assert len(_error_codes(ledger)) == R.MAX_ERROR_EVENTS and ledger.seqs_are_contiguous()


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


# ---------------------------------------------------------------- the checks against the real reference
@pytest.mark.parametrize("check", CHECKS, ids=lambda f: f.__name__)
def test_the_reference_ledger_satisfies_each_generation_check(check):
    check(R.Ledger)


# ---------------------------------------------------------------- mutants: deliberately broken copies of Ledger.commit
_SRC = textwrap.dedent(inspect.getsource(R.Ledger.commit))
_GEN_TEST = "if type(gid) is not int or gid != self.generation_id:"
_STALE_RETURN = 'return {"ok": False, "reason": "stale_generation"}'
_SHA_LINE = "sha = canonical_payload_sha256(command)\n"


def make_mutant(old, new):
    assert _SRC.count(old) == 1, f"mutation anchor is missing or ambiguous (the reference changed?): {old!r}"
    namespace = {"canonical_payload_sha256": R.canonical_payload_sha256, "MAX_ERROR_EVENTS": R.MAX_ERROR_EVENTS}
    exec(compile(_SRC.replace(old, new), "<mutant>", "exec"), namespace)  # our own reference source with one deliberate defect; no external input
    return type("Mutant", (R.Ledger,), {"commit": namespace["commit"]})


MUTANTS = {
    # name: (mutant class factory args, the check written to catch it)
    "generation_check_removed": ((_GEN_TEST, "if False:"), check_a_newer_generation_is_refused_as_well_as_an_older_one),
    "refuses_only_older_generations": (("gid != self.generation_id", "gid < self.generation_id"), check_a_newer_generation_is_refused_as_well_as_an_older_one),
    "bool_and_float_count_as_an_int_generation": (("type(gid) is not int or ", ""), check_only_an_int_equal_to_the_current_generation_passes),
    "generation_checked_before_the_key_lookup": ((_SHA_LINE, _SHA_LINE + '    if command.get("generation_id") != self.generation_id:\n        self.error("stale_generation")\n        ' + _STALE_RETURN + "\n"), check_a_replay_after_the_generation_moved_is_acknowledged_with_the_first_result),
    "a_stale_refusal_is_remembered": ((_STALE_RETURN, 'self._seen[key] = (sha, {"ok": False, "reason": "stale_generation"}); ' + _STALE_RETURN), check_a_stale_refusal_is_not_remembered_as_a_success),
    "a_stale_refusal_leaves_no_error_event": (('self.error("stale_generation")', "pass"), check_a_stale_refusal_appends_one_bounded_error_event_and_the_log_stays_contiguous),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_every_mutant_is_caught_by_the_check_written_for_it(name):
    (old, new), target_check = MUTANTS[name]
    mutant = make_mutant(old, new)  # built outside `raises`: a broken mutant (syntax error) must surface, not count as "caught"
    with pytest.raises(Exception):  # an AssertionError, or the mutant breaking the checked contract so badly that the check cannot even read its answer
        target_check(mutant)


def test_no_mutant_survives_the_whole_set_of_checks():
    for name, ((old, new), _target) in MUTANTS.items():
        mutant = make_mutant(old, new)
        failed = []
        for check in CHECKS:
            try:
                check(mutant)
            except Exception:
                failed.append(check.__name__)
        assert failed, f"mutant {name!r} survives every check"
