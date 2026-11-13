import ast
import dataclasses
import pathlib
import unittest

from src.gamepc_ops import candidate as c
from src.gamepc_ops import router as r

SRC = "第1条 出願期間は2026年9月1日から9月8日までとする。\n募集人員は 15 名とする。"
SHA = c.sha256_hex(SRC)
OLD = "0" * 64


def at_extracted() -> c.Candidate:
    x = c.Candidate("c1", SHA)
    x = x.to_difference_detected(previous_sha256=OLD)
    x = x.to_scope_checked(university="架空あさひ未来大", fiscal_year=2027, method="総合型", scope_evidence_ref="ev-independent-1")
    return x.to_extracted(fact_key="admission.quota", value="15", quote="募集人員は 15 名とする")


def with_(x, **kw):
    return dataclasses.replace(x, **kw)


class CandidateTests(unittest.TestCase):
    def test_happy_path_reaches_qa_ready_without_any_authority(self):
        x = at_extracted().to_evidence_validated(source_text=SRC).to_qa_ready()
        self.assertIs(x.state, c.State.QA_READY)
        self.assertEqual([h[1] for h in x.history], [s.value for s in c.HAPPY[1:]])
        self.assertTrue(all(v is False for v in x.authority.values()))

    def test_no_skipping_steps(self):
        with self.assertRaises(c.TransitionError):
            c.Candidate("c", SHA).to_extracted(fact_key="k", value="v", quote="q")
        with self.assertRaises(c.TransitionError):
            c.Candidate("c", SHA).to_qa_ready()

    def test_difference_needs_a_real_difference(self):
        for prev in ("", SHA):
            with self.assertRaises(c.TransitionError):
                c.Candidate("c", SHA).to_difference_detected(previous_sha256=prev)

    def test_scope_needs_independent_evidence_not_the_source_itself(self):
        x = c.Candidate("c", SHA).to_difference_detected(previous_sha256=OLD)
        for ref in ("", SHA):
            with self.assertRaises(c.TransitionError):
                x.to_scope_checked(university="u", fiscal_year=2027, method="m", scope_evidence_ref=ref)
        with self.assertRaises(c.TransitionError):
            x.to_scope_checked(university="u", fiscal_year="2027", method="m", scope_evidence_ref="ev")

    def test_quote_must_be_in_the_hashed_source_text(self):
        x = at_extracted()
        with self.assertRaises(c.TransitionError):
            x.to_evidence_validated(source_text=SRC + " 改ざん")          # text no longer matches the hash
        with self.assertRaises(c.TransitionError):
            with_(x, quote="募集人員は 99 名とする").to_evidence_validated(source_text=SRC)   # quote not in source
        with self.assertRaises(c.TransitionError):
            with_(x, value="99").to_evidence_validated(source_text=SRC)                    # value not in its quote

    def test_high_risk_needs_independent_qa_before_qa_ready(self):
        x = with_(at_extracted(), high_risk=True).to_evidence_validated(source_text=SRC)
        with self.assertRaises(c.TransitionError):
            x.to_qa_ready()
        self.assertIs(with_(x, independent_qa_ref="qa-1").to_qa_ready().state, c.State.QA_READY)

    def test_unknown_and_human_states_leave_only_by_human_decision(self):
        held = at_extracted().hold_unknown("year could not be proven")
        with self.assertRaises(c.TransitionError):
            held.to_evidence_validated(source_text=SRC)
        with self.assertRaises(c.TransitionError):
            held.human_decision(human_ref="", resume_at=c.State.EXTRACTED, reason="r")
        with self.assertRaises(c.TransitionError):
            held.human_decision(human_ref="h1", resume_at=c.State.QA_READY, reason="r")   # no jump to QA_READY
        back = held.human_decision(human_ref="h1", resume_at=c.State.EXTRACTED, reason="checked by the owner")
        self.assertIs(back.state, c.State.EXTRACTED)

    def test_quarantine_is_terminal_and_every_move_needs_a_reason(self):
        q = at_extracted().quarantine("contradiction")
        for f in (lambda: q.hold_unknown("x"), lambda: q.need_human("x"), lambda: q.quarantine("x")):
            with self.assertRaises(c.TransitionError):
                f()
        with self.assertRaises(c.TransitionError):
            at_extracted().quarantine("  ")

    def test_candidates_are_immutable(self):
        x = c.Candidate("c", SHA)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            x.state = c.State.QA_READY


class RouterTests(unittest.TestCase):
    NO_HOLD = staticmethod(lambda: False)
    HOLD = staticmethod(lambda: True)
    OK = {"kind": "ambiguous_diff", "go_ref": "go-1", "die_temp_c": 60.0, "temp_sensor_authentic": True, "mem_used_percent": 50.0}

    def test_deterministic_kinds_never_use_a_model(self):
        for k in r.DETERMINISTIC_KINDS:
            x = r.route({"kind": k}, hold_check=self.HOLD)
            self.assertEqual((x.lane, x.llm_may_run), ("NON_LLM", False))

    def test_unknown_kind_goes_to_a_human(self):
        self.assertEqual(r.route({"kind": "???"}).lane, "HUMAN_REVIEW")

    def test_ambiguity_is_deferred_under_hold_even_if_everything_else_is_fine(self):
        self.assertEqual(r.route(self.OK, hold_check=self.HOLD).lane, "DEFER")

    def test_each_missing_or_unsafe_condition_defers(self):
        for patch in ({"go_ref": None}, {"die_temp_c": None}, {"temp_sensor_authentic": False}, {"temp_sensor_authentic": None},
                      {"die_temp_c": 80.0}, {"mem_used_percent": None}, {"mem_used_percent": 95.0}):
            job = {**self.OK, **patch}
            self.assertEqual(r.route(job, hold_check=self.NO_HOLD).lane, "DEFER", patch)

    def test_only_a_fully_safe_ambiguity_may_produce_a_candidate(self):
        x = r.route(self.OK, hold_check=self.NO_HOLD)
        self.assertEqual((x.lane, x.llm_may_run), ("LLM_CANDIDATE_ONLY", True))

    def test_real_backend_is_refused_under_hold_and_otherwise_not_implemented(self):
        with self.assertRaises(r.HoldActive):
            r.get_backend("real", hold_check=self.HOLD)
        with self.assertRaises(r.ModelUnavailable):
            r.get_backend("real", hold_check=self.NO_HOLD)
        with self.assertRaises(ValueError):
            r.get_backend("gpu")

    def test_the_repository_hold_file_is_seen_by_the_default_check(self):
        self.assertTrue(r.hold_active())           # the real HOLD is in force in this repository
        with self.assertRaises(r.HoldActive):
            r.get_backend("real")

    def test_fake_and_null_backends(self):
        self.assertTrue(r.get_backend("fake").interpret("t", "q").startswith("FAKE:"))
        with self.assertRaises(r.ModelUnavailable):
            r.get_backend("null").interpret("t", "q")


class NoSideEffectModuleTests(unittest.TestCase):
    FORBIDDEN = {"socket", "requests", "urllib", "http", "subprocess", "sqlite3", "ctypes", "shutil", "os"}

    def test_modules_import_nothing_that_can_reach_the_network_a_process_or_a_database(self):
        base = pathlib.Path(__file__).resolve().parents[1] / "src" / "gamepc_ops"
        for name in ("candidate.py", "router.py"):
            tree = ast.parse((base / name).read_text(encoding="utf-8"))
            mods = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    mods |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    mods.add(n.module.split(".")[0])
            self.assertFalse(mods & self.FORBIDDEN, (name, mods & self.FORBIDDEN))


if __name__ == "__main__":
    unittest.main()
