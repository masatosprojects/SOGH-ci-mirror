"""SELF_TEST (Claude) for candidate G (owner-approved 2026-11-08): the provenance detection of PR #268 is now part of ``plan()``, ``apply()`` and the DB-17 audit, and it changes nothing for a database that has no
history yet. SYNTHETIC disposable databases only. Not an acceptance of g5 (an independent re-computation on the real copy is still needed).
Proven: a replaced from_version / description / applied_at, a row written again (out of order) is DRIFT: plan() says so, apply() refuses and the file is byte-identical, DB-17 fails; a fresh database
migrates exactly as before; a database built by the runner is never reported (no false positive) at any step of the chain; the existing behaviour of verify_history is unchanged."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests import db_support as S  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from src.db_contract import additive_schema as ad  # noqa: E402

CHAIN = [m[0] for m in ad.MIGRATIONS]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fresh(tmp_path):
    path, _p = S.make_native(tmp_path)
    RevisionStore(path, tmp_path / "backup.sqlite")
    return path


class open_history:
    """Rewrite the history the way a hostile or hand-edited file would have it: the guard triggers of 0004 are dropped, the rows are changed, and the SAME triggers are put back, so that the only thing that
    differs from a database the runner built is the history itself (DB-17's trigger check must not be what notices)."""

    def __init__(self, path):
        self.c = sqlite3.connect(path)
        self.saved = self.c.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='schema_migrations'").fetchall()
        for name, _sql in self.saved:
            self.c.execute(f"DROP TRIGGER {name}")

    def __enter__(self):
        return self.c

    def __exit__(self, *exc):
        for _name, sql in self.saved:
            self.c.execute(sql)
        self.c.commit()
        self.c.close()


def test_a_fresh_database_migrates_exactly_as_before(tmp_path):
    path = fresh(tmp_path)
    assert ad.plan(path)["drift"] == []
    r = ad.apply(path, confirm_disposable_copy=True)
    assert r["applied"] == CHAIN and not r["rolled_back"]


@pytest.mark.parametrize("stop", range(1, len(CHAIN)))
def test_a_database_built_by_the_runner_is_never_reported_at_any_step(tmp_path, stop):
    path = fresh(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(CHAIN[:stop]))
    with closing(sqlite3.connect(path)) as c:
        assert ad.provenance_problems_if_history(c) == [] and ad.verify_history(c) == []
    p = ad.plan(path)
    assert p["drift"] == [] and p["can_apply"]
    r = ad.apply(path, confirm_disposable_copy=True)  # and the rest still applies
    assert r["applied"] == CHAIN[stop:] and not r["rolled_back"]


@pytest.mark.parametrize("tamper,expect", [
    ("UPDATE schema_migrations SET from_version='forged' WHERE seq=4", "says it follows"),
    ("UPDATE schema_migrations SET description='forged' WHERE seq=3", "description"),
    ("UPDATE schema_migrations SET applied_at='yesterday' WHERE seq=3", "applied_at"),
    ("UPDATE schema_migrations SET applied_at='2000-01-01T00:00:00+00:00' WHERE seq=5", "before the migration applied just before it"),
])
def test_a_tampered_history_is_drift_for_plan_apply_and_db17(tmp_path, tamper, expect):
    path = fresh(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(CHAIN[:6]))
    with open_history(path) as c:
        c.execute(tamper)
        c.commit()
    # verify_history (the old contract) does not see it: this is exactly what the integration adds
    with closing(sqlite3.connect(path)) as c:
        assert ad.verify_history(c) == [] and any(expect in p for p in ad.provenance_problems_if_history(c))
    before = sha(path)
    p = ad.plan(path)
    assert not p["can_apply"] and any(expect in d for d in p["drift"]) and sha(path) == before
    with pytest.raises(ad.MigrationError, match=expect):
        ad.apply(path, confirm_disposable_copy=True)
    assert sha(path) == before  # nothing was applied, the file is byte-identical
    assert S.audit(path)["invariants"]["DB-17"]["status"] == "fail"


def test_a_row_written_again_lands_out_of_order_and_is_drift(tmp_path):
    path = fresh(tmp_path)
    ad.apply(path, confirm_disposable_copy=True, only=tuple(CHAIN[:5]))
    with open_history(path) as c:
        row = c.execute("SELECT * FROM schema_migrations WHERE seq=3").fetchone()
        c.execute("DELETE FROM schema_migrations WHERE seq=3")
        c.execute(f"INSERT INTO schema_migrations VALUES ({','.join('?' * len(row))})", row)  # the same content, now after the later rows
        c.commit()
    with closing(sqlite3.connect(path)) as c:
        assert ad.verify_history(c) == [] and ad.provenance_problems_if_history(c)
    with pytest.raises(ad.MigrationError):
        ad.apply(path, confirm_disposable_copy=True)


def test_db17_passes_on_every_database_the_runner_built(tmp_path):
    path = fresh(tmp_path)
    ad.apply(path, confirm_disposable_copy=True)
    assert S.audit(path)["invariants"]["DB-17"]["status"] == "pass"


def test_a_database_without_any_history_is_not_reported_by_the_integration(tmp_path):
    path = fresh(tmp_path)
    with closing(sqlite3.connect(path)) as c:
        assert ad.provenance_problems_if_history(c) == []  # the old answer for a database that was never migrated
        assert ad.verify_history(c) == []


def test_the_acceptance_gate_is_unchanged_and_still_refuses_an_empty_history(tmp_path):
    path = fresh(tmp_path)
    with closing(sqlite3.connect(path)) as c:
        gate = ad.verify_history_for_acceptance(c, before=())
        assert gate  # no history is still not an acceptance
