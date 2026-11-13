"""Independent abnormal-path tests of the update transaction (RevisionStore.finalize) on the stage-1 patched Work code.

Claude-owned QA for the review of PR #93 (head cb03ff8). It runs on whichever patched copy of Work's pipeline `tests/db_support.py` selects: the default copy
made with Claude's own patch (patches/m1-stage1) or, with SOGH_PIPELINE_ROOT, the isolation made by Work's `prepare_isolation.py`. SYNTHETIC_ONLY: invented cycles in
temporary databases; no real database, no source document. A pass says the transaction is all-or-nothing on these inputs; it does not say who produced the QA result
(`sogh_write_ok` is a capability, not an authentication: see the D2 test of Work and docs/THREAT_MODEL_D2_G08.md).
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from tests import db_support as S
from admissions_pipeline.notice_articles import revise_article
from admissions_pipeline.revisions import RevisionStore
from admissions_pipeline.store import canonical
from src.db_contract import additive_schema as ad

REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 1)


def snapshot(path):
    """Everything a failed update must leave untouched: every row of every table, the schema text, user_version, and the integrity check."""
    with closing(sqlite3.connect(path)) as db:
        tables = [n for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {"rows": {t: sorted(repr(tuple(r)) for r in db.execute(f'SELECT * FROM "{t}"')) for t in tables},
                "schema": [tuple(r) for r in db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")],
                "user_version": db.execute("PRAGMA user_version").fetchone()[0], "integrity": db.execute("PRAGMA integrity_check").fetchone()[0]}


def make(tmp, migrate=True, name="u.sqlite"):
    path, profile = S.make_native(tmp, name)
    store = RevisionStore(path, tmp / (name + ".before"))
    if migrate:
        assert not ad.apply(path, confirm_disposable_copy=True)["rolled_back"]
    batch = store.stage([S.notice(profile)], S.REGISTRY)
    article = revise_article(S.base_article(store), store.effective_records(batch), AS_OF)
    return path, store, batch, article, qa_for(batch, article)


def qa_for(batch, article, **over):
    qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical([article]).encode()).hexdigest()}
    qa.update(over)
    return qa


def reason(**over):
    data = dict(reason_class="article_refresh", reason_text="explicit synthetic caller reason", source_changed="no", actor="synthetic-test-fixture-not-user-approval")
    data.update(over)
    return data


def states(path):
    with closing(sqlite3.connect(path)) as db:
        return {"batches": dict(db.execute("SELECT batch_id,state FROM update_batches")), "events": [r[0] for r in db.execute("SELECT event FROM update_events ORDER BY rowid")],
                "reasons": db.execute("SELECT count(*) FROM revision_reasons").fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE name='revision_reasons'").fetchone() else None}


# --- failure injected after each write step: all or nothing -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("table", ["revised_articles", "evidence_heads", "article_heads", "update_events", "revision_reasons"])
def test_a_failure_at_any_write_step_leaves_every_row_the_schema_and_user_version_unchanged(tmp_path, table):
    path, store, batch, article, qa = make(tmp_path)
    with store.connect() as db:
        db.execute(f"CREATE TRIGGER qa_inject_{table} BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected fault'); END")
    before = snapshot(path)
    with pytest.raises(sqlite3.IntegrityError, match="injected fault"):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert snapshot(path) == before and before["integrity"] == "ok"
    assert S.heads(path) == {"evidence": {}, "articles": {}}


def test_a_failed_head_move_after_the_batch_was_approved_does_not_leave_the_batch_approved(tmp_path):
    """The patched order is approve first, heads second (INV-06 needs the batch approved when a head points at it): the rollback must still take the approval back."""
    path, store, batch, article, qa = make(tmp_path)
    with store.connect() as db:
        db.execute("CREATE TRIGGER qa_inject BEFORE INSERT ON evidence_heads BEGIN SELECT RAISE(ABORT,'injected fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.finalize(batch, [article], qa, S.REGISTRY)
    assert states(path)["batches"][batch["batch_id"]] == "candidate" and states(path)["events"] == []


# --- the QA binding and the batch state ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [{"batch_input_sha": "0" * 64}, {"articles_sha256": "0" * 64}, {"batch_input_sha": None}, {"articles_sha256": ""}])
def test_a_qa_result_not_bound_to_this_exact_update_is_refused_and_changes_nothing(tmp_path, bad):
    path, store, batch, article, _ = make(tmp_path)
    before = snapshot(path)
    with pytest.raises(ValueError, match="not bound"):
        store.finalize(batch, [article], qa_for(batch, article, **bad), S.REGISTRY, reason=reason())
    assert snapshot(path) == before


def test_a_failed_qa_marks_the_batch_rejected_and_never_moves_a_head_and_it_cannot_then_be_approved(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    assert store.finalize(batch, [article], qa_for(batch, article, success=False), S.REGISTRY) is False
    assert states(path)["batches"][batch["batch_id"]] == "rejected" and S.heads(path) == {"evidence": {}, "articles": {}} and states(path)["events"] == []
    before = snapshot(path)
    with pytest.raises(ValueError, match="not eligible"):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert snapshot(path) == before


def test_finalizing_twice_approves_once_and_the_second_call_changes_nothing(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    after_first = snapshot(path)
    with pytest.raises(ValueError, match="not eligible"):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason(reason_text="a second, different reason"))
    assert snapshot(path) == after_first and states(path)["events"] == ["approved"] and states(path)["reasons"] == 1


def test_a_retry_after_a_rolled_back_failure_succeeds_exactly_once(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    before = snapshot(path)
    with pytest.raises(sqlite3.IntegrityError):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason(reason_text=""))
    assert snapshot(path) == before
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert states(path)["events"] == ["approved"] and states(path)["reasons"] == 1 and S.failing(path) == {}


def test_a_rolled_back_batch_cannot_be_approved_again(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    assert store.finalize(batch, [article], qa, S.REGISTRY)
    store.rollback_batch(batch["batch_id"])
    before = snapshot(path)
    with pytest.raises(ValueError, match="not eligible"):
        store.finalize(batch, [article], qa, S.REGISTRY)
    assert snapshot(path) == before and states(path)["events"] == ["approved", "rolled_back"]


def test_a_batch_that_is_not_a_candidate_is_not_approved(tmp_path):
    path, store, _, _, _ = make(tmp_path)
    other = RevisionStore(path, tmp_path / "b2")
    proposed = S.notice(S.profile(), eid="EV-U-2", logical="n2", fact_key="multilingual_evaluation")  # a proposed fact key: no contract yet
    unknown_state = other.stage([proposed], S.REGISTRY)
    assert unknown_state["state"] == "pending_contract"
    article = revise_article(S.base_article(store), [proposed], AS_OF)
    before = snapshot(path)
    with pytest.raises(ValueError, match="not eligible"):
        other.finalize(unknown_state, [article], qa_for(unknown_state, article), S.REGISTRY)
    assert snapshot(path) == before


def test_an_unknown_batch_id_changes_nothing(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    before = snapshot(path)
    with pytest.raises(Exception):  # the exception type is not part of the contract; the database must be untouched
        store.finalize(dict(batch, batch_id="no-such-batch"), [article], qa, S.REGISTRY)
    assert snapshot(path) == before


def test_an_article_that_cites_another_cycles_evidence_is_refused_and_changes_nothing(tmp_path):
    path, store, batch, article, _ = make(tmp_path)
    S.ingest_cycle(store, "case2", S.profile(university="別大学", sha="c" * 64), tmp_path, eid="EV-case2-1")
    bad = dict(article, text=article["text"] + "\n別の大学の根拠[EV-case2-1]。", evidence_ids=sorted(set(article["evidence_ids"]) | {"EV-case2-1"}))
    before = snapshot(path)
    with pytest.raises(ValueError, match="different cycle|unknown or inactive|differs"):
        store.finalize(batch, [bad], qa_for(batch, bad), S.REGISTRY, reason=reason())
    assert snapshot(path) == before


# --- two writers ---------------------------------------------------------------------------------------------------------------------------------------------

def test_a_second_batch_staged_from_the_same_heads_is_refused_after_the_first_is_approved(tmp_path):
    path, store, first, article, qa = make(tmp_path)
    other = RevisionStore(path, tmp_path / "b2")
    second = other.stage([S.notice(S.profile(), eid="EV-U-2", logical="n2")], S.REGISTRY)
    art2 = revise_article(S.base_article(other), other.effective_records(second), AS_OF)
    assert store.finalize(first, [article], qa, S.REGISTRY)
    after_first = snapshot(path)
    with pytest.raises(ValueError, match="concurrent head change|not eligible"):
        other.finalize(second, [art2], qa_for(second, art2), S.REGISTRY)
    assert snapshot(path) == after_first and states(path)["batches"][second["batch_id"]] == "candidate"


def test_two_threads_finalizing_the_same_batch_approve_it_once(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    gate, outcome = threading.Barrier(2), []

    def attempt():
        mine = RevisionStore(path, tmp_path / ("b-" + str(threading.get_ident())))
        gate.wait()
        try:
            outcome.append(("ok", mine.finalize(batch, [article], qa, S.REGISTRY, reason=reason())))
        except Exception as e:  # noqa: BLE001 - the loser may fail in more than one way (lock timeout, not eligible)
            outcome.append(("err", type(e).__name__))

    workers = [threading.Thread(target=attempt) for _ in range(2)]
    [w.start() for w in workers]
    [w.join(60) for w in workers]
    assert sorted(o[0] for o in outcome) == ["err", "ok"], outcome
    assert states(path)["events"] == ["approved"] and states(path)["reasons"] == 1 and S.failing(path) == {}


# --- the process dies inside the transaction ------------------------------------------------------------------------------------------------------------------

CRASH = """
import json, os, sys
sys.path.insert(0, {repo!r})
from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
job = json.load(open({job!r}, encoding='utf-8'))
store = RevisionStore(job['path'], job['backup'])
def die(db, batch_id, reason):  # after the heads and the event were written, before the commit
    os._exit(9)
RevisionStore._record_reason = staticmethod(die)
store.finalize(job['batch'], [job['article']], job['qa'], S.REGISTRY, reason=job['reason'])
"""


def test_a_process_that_dies_before_commit_leaves_the_database_as_it_was_and_the_update_can_be_run_again(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    before = snapshot(path)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"path": str(path), "backup": str(tmp_path / "crash.before"), "batch": batch, "article": article, "qa": qa, "reason": reason()}), encoding="utf-8")
    script = tmp_path / "crash.py"
    script.write_text(CRASH.format(repo=str(REPO), job=str(job)), encoding="utf-8")
    done = subprocess.run([sys.executable, "-B", str(script)], capture_output=True, text=True, timeout=120, cwd=REPO, env=dict(os.environ, PYTHONUTF8="1"))
    assert done.returncode == 9, done.stderr[-400:]  # it really died inside the transaction
    assert snapshot(path) == before
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=reason()) and states(path)["events"] == ["approved"] and S.failing(path) == {}


# --- the connection conditions and what the guards refuse ---------------------------------------------------------------------------------------------------------

def test_the_store_connection_has_the_pragmas_and_the_capability_and_a_plain_connection_does_not(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    with store.connect() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1 and db.execute("PRAGMA recursive_triggers").fetchone()[0] == 1 and db.execute("SELECT sogh_write_ok()").fetchone()[0] == 1
    with closing(sqlite3.connect(path)) as plain:
        with pytest.raises(sqlite3.OperationalError, match="sogh_write_ok"):
            plain.execute("SELECT sogh_write_ok()")


@pytest.mark.parametrize("statement", [
    "INSERT OR REPLACE INTO evidence_heads VALUES('forged-logical','EV-forged')",
    "INSERT INTO evidence_heads VALUES('forged-logical','EV-forged')",
    "UPDATE update_batches SET state='approved'",
    "DELETE FROM update_events",
    "UPDATE update_events SET event='rolled_back'",
    "DELETE FROM revision_reasons",
])
def test_a_connection_that_does_not_register_the_capability_cannot_write_the_guarded_tables(tmp_path, statement):
    path, store, batch, article, qa = make(tmp_path)
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    before = snapshot(path)
    with closing(sqlite3.connect(path)) as plain:
        plain.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.Error):
            plain.execute(statement)
            plain.commit()
    assert snapshot(path) == before


def test_dropping_a_guard_with_plain_sql_is_possible_but_detected_never_silently_accepted(tmp_path):
    """The known limit: DDL by a file writer is not prevented (the guards are triggers of the same file). It must be DETECTED by the schema-state check."""
    path, store, batch, article, qa = make(tmp_path)
    with closing(sqlite3.connect(path)) as plain:
        name = plain.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_%' ORDER BY name").fetchone()[0]
        plain.execute(f'DROP TRIGGER "{name}"')
        plain.commit()
    assert ad.plan(path)["drift"] and S.audit(path)["invariants"]["DB-17"]["status"] == "fail"


# --- the reason: only what the caller said, nothing guessed ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [{}, [], "text", 0, reason(reason_text=""), reason(reason_text="   "), reason(source_changed="maybe"), reason(reason_class="not_a_class"), reason(actor=""),
                                 {k: v for k, v in reason().items() if k != "actor"}, reason(reason_class="source_changed", source_changed="no")])
def test_a_missing_or_invalid_reason_rolls_back_the_whole_approval(tmp_path, bad):
    path, store, batch, article, qa = make(tmp_path)
    before = snapshot(path)
    with pytest.raises(Exception):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=bad)
    assert snapshot(path) == before and S.heads(path) == {"evidence": {}, "articles": {}}


def test_a_reason_is_stored_as_given_and_extra_fields_are_not_propagated_or_invented(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    given = reason(approved_by_user=True, approver="somebody", reason_text="Quota text refreshed after the school's notice.")
    assert store.finalize(batch, [article], qa, S.REGISTRY, reason=given)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM revision_reasons").fetchone()
        text = json.dumps(dict(row), ensure_ascii=False)
    assert row["reason_text"] == given["reason_text"] and row["actor"] == given["actor"] and "approved_by_user" not in text and "somebody" not in text
    assert row["recorded_at"] and row["batch_id"] == batch["batch_id"]


def test_no_reason_given_means_no_reason_row_and_nothing_is_made_up(tmp_path):
    path, store, batch, article, qa = make(tmp_path)
    assert store.finalize(batch, [article], qa, S.REGISTRY)
    assert states(path)["reasons"] == 0 and states(path)["events"] == ["approved"]


def test_a_reason_on_a_database_without_the_reason_table_is_refused_without_a_partial_approval(tmp_path):
    path, store, batch, article, qa = make(tmp_path, migrate=False)
    before = snapshot(path)
    with pytest.raises(ValueError, match="no revision_reasons"):
        store.finalize(batch, [article], qa, S.REGISTRY, reason=reason())
    assert snapshot(path) == before


# --- the command line: --reason-json ---------------------------------------------------------------------------------------------------------------------------
# Only Work's patch adds the flag (Claude's patch deliberately leaves the CLI to Work). The tests below are defined only when the selected copy has it; they therefore run
# in the review run `SOGH_PIPELINE_ROOT=<isolation made by Work's prepare_isolation.py>` and are absent (not skipped) on the default copy.
HAS_REASON_FLAG = "--reason-json" in (Path(S.PIPELINE) / "scripts" / "revise_notices.py").read_text(encoding="utf-8")


def load_cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("review_revise_notices", Path(S.PIPELINE) / "scripts" / "revise_notices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(module, monkeypatch, tmp_path, payload=None, raw=None, with_flag=True):
    seen = []
    monkeypatch.setattr(module, "run", lambda *a, **kw: seen.append(kw.get("reason", "NO_REASON_ARGUMENT")) or {"approved": True, "pending_contract": [], "revised_articles": 0, "source_review_pending": []})
    argv = ["revise_notices.py"] + [x for n in ("specs", "monitor-root", "base-export", "base-db", "work-db", "qa-root", "output") for x in ("--" + n, str(tmp_path / n))]
    if with_flag:
        f = tmp_path / "reason.json"
        f.write_bytes(raw if raw is not None else json.dumps(payload).encode("utf-8"))
        argv += ["--reason-json", str(f)]
    monkeypatch.setattr(sys, "argv", argv)
    return seen


def test_cli_without_the_flag_passes_no_reason(tmp_path, monkeypatch):
    module = load_cli()
    seen = run_cli(module, monkeypatch, tmp_path, with_flag=False)
    with pytest.raises(SystemExit) as e:
        module.main()
    assert e.value.code == 0 and seen == [None]


def test_cli_passes_the_object_unchanged_and_adds_nothing(tmp_path, monkeypatch):
    module = load_cli()
    given = reason(extra="kept as given, filtered by the store")
    seen = run_cli(module, monkeypatch, tmp_path, given)
    with pytest.raises(SystemExit):
        module.main()
    assert seen == [given]


@pytest.mark.parametrize("payload", [[], "x", 0, 1.5, True, False, ""])
def test_cli_rejects_json_that_is_not_an_object(tmp_path, monkeypatch, payload):
    module = load_cli()
    seen = run_cli(module, monkeypatch, tmp_path, payload)
    with pytest.raises(SystemExit) as e:
        module.main()
    assert e.value.code == 2 and seen == []  # argparse error: the update is never started


@pytest.mark.parametrize("raw", [b"{not json", b"", b"\xef\xbb\xbf" + b'{"reason_class":"x"}', b"\xff\xfe"])
def test_cli_rejects_broken_json_before_anything_runs(tmp_path, monkeypatch, raw):
    module = load_cli()
    seen = run_cli(module, monkeypatch, tmp_path, raw=raw)
    with pytest.raises((ValueError, SystemExit)):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        module.main()
    assert seen == []


def test_cli_a_null_reason_file_is_refused_like_every_other_non_object(tmp_path, monkeypatch):
    """PR #93 review finding F-3 (fixed in head 2019231): `--reason-json` was given explicitly and the file says `null`: that is not a reason and must not be read as
    'no reason requested'. Exit 2 and the update never starts (the flag-less call still passes None: see the first CLI test)."""
    module = load_cli()
    seen = run_cli(module, monkeypatch, tmp_path, None)
    with pytest.raises(SystemExit) as e:
        module.main()
    assert e.value.code == 2 and seen == []


if not HAS_REASON_FLAG:  # the default copy has no --reason-json: its CLI tests are removed (not skipped); the review run on Work's isolation keeps them
    for _name in [n for n in list(globals()) if n.startswith("test_cli_")]:
        del globals()[_name]
