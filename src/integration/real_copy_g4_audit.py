"""Independent g4 harness for M1 (disposable clones of an audited real database COPY; never the source, never a production file).

Usage (the copy and the pipeline are private/local; nothing here runs in CI):
  SOGH_G4_PIPELINE=<pipeline root> SOGH_G4_QA_ROOT=<export of this repo> SOGH_G4_VIEW=<active-state.json>
  python -B -X utf8 src/integration/real_copy_g4_audit.py --source <copy v06.sqlite> --older <older copy v05.sqlite> --out <new empty dir>
Optional: SOGH_G4_PREPARE=<module:function> is called on every disposable clone (and on one reference clone that becomes the row baseline) after it was copied,
for example src.integration.g4_prepare:prepare (the frozen migration chain) to check Work's update path on a clone that carries the final protections. The source itself is never prepared.

Claude's independent g4 harness. The code under test is Work's RevisionStore/ProcessLock;
all verification (row-by-row comparison, expected states, oracle heads from the older v05 copy, db_audit, integrity, journal handling) is computed here, not taken from Work's driver."""
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from contextlib import closing
from pathlib import Path

def _need(name):
    if name not in os.environ:
        raise SystemExit("set " + name + " (see the module docstring)")
    return Path(os.environ[name])


PIPE = _need("SOGH_G4_PIPELINE")  # the Work pipeline root that contains admissions_pipeline/ (read only)
QA = _need("SOGH_G4_QA_ROOT")  # a clean export of this repository (src/verify/data/fact_keys.json, src/integration/db_audit.py)
VIEW = _need("SOGH_G4_VIEW")  # the delivered active-state.json that holds the current head evidence record
PREPARE = os.environ.get("SOGH_G4_PREPARE")  # optional "module:function" run on every clone (see the docstring)
sys.path[:0] = [str(PIPE), str(QA)]
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.process_lock import ProcessLock  # noqa: E402
from admissions_pipeline.store import canonical  # noqa: E402

HEAD_ID = "EV-U-61c185ec5771"
REG = json.loads((QA / "src/verify/data/fact_keys.json").read_text(encoding="utf-8"))
VIEWD = json.loads(VIEW.read_text(encoding="utf-8"))
RECORD = VIEWD["evidence"][HEAD_ID]
FAQ_ARTICLES = [a for a in VIEWD["articles"] if HEAD_ID in a["evidence_ids"]]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(path):
    if PREPARE:
        import importlib
        module, name = PREPARE.split(":")
        getattr(importlib.import_module(module), name)(path)


def recover_and_close(path):
    with closing(sqlite3.connect(path)) as c:  # a read in read-write mode lets SQLite roll back a hot journal
        c.execute("select count(*) from sqlite_master").fetchone()


def dump(path):
    out = {}
    with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as c:
        for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1").fetchall():
            pk = [r[1] for r in sorted(c.execute(f'pragma table_info("{t}")').fetchall(), key=lambda r: r[5]) if r[5]]
            cols = [r[1] for r in c.execute(f'pragma table_info("{t}")').fetchall()]
            rows = c.execute(f'select * from "{t}"').fetchall()
            key = (lambda r: tuple(r[cols.index(k)] for k in pk)) if pk else (lambda r: tuple(r))
            out[t] = {key(r): tuple(r) for r in rows}
        out["_integrity"] = c.execute("pragma integrity_check").fetchone()[0]
        out["_fk"] = len(c.execute("pragma foreign_key_check").fetchall())
    return out


def diff(old, new):
    res = {}
    for t, rows in old.items():
        if t.startswith("_"):
            continue
        n = new[t]
        removed = sum(1 for k in rows if k not in n)
        changed = sum(1 for k, v in rows.items() if k in n and n[k] != v)
        added = sum(1 for k in n if k not in rows)
        if removed or changed or added:
            res[t] = (removed, changed, added)
    return res


def heads(path):
    with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as c:
        return {"e": dict(c.execute("select logical_id,evidence_id from evidence_heads").fetchall()), "a": dict(c.execute("select base_article_id,article_id from article_heads").fetchall())}


def new_article(suffix):
    a = dict(FAQ_ARTICLES[0])
    h = hashlib.sha256(("claude-test-" + suffix + a["text"]).encode("utf-8")).hexdigest()  # a synthetic revision that carries its own hash in its id (DB-06 convention)
    a["revision_hash"] = h
    a["article_id"] = a["base_article_id"] + ":revision:" + h[:16]
    return a


def bound_qa(batch, articles, ok=True):
    return {"success": ok, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical(articles).encode()).hexdigest()}


# ------------------------------------------------------------------ children (crash / other process)
def child(a):
    db = Path(a.db)
    if a.child == "lock_probe":
        try:
            with ProcessLock(Path(a.lock)):
                pass
        except RuntimeError:
            os._exit(42)
        os._exit(0)
    if a.child == "uncommitted":
        c = sqlite3.connect(db)
        c.create_function("sogh_write_ok", 0, lambda: 1)  # what SOGH's own connection registers (no effect on a clone without the gate)
        c.execute("pragma foreign_keys=ON")
        c.execute("BEGIN IMMEDIATE")
        b = c.execute("select batch_id from update_batches where state='approved' order by created_at desc limit 1").fetchone()[0]
        c.execute("insert into update_events(batch_id,event,created_at,detail_json) values(?,'claude_uncommitted','x','{}')", (b,))
        os._exit(73)
    store = RevisionStore(db, db.parent / ("child-before-" + a.child + "-" + str(os.getpid()) + ".sqlite"))
    if a.child == "stage_once":
        try:
            store.stage([RECORD], REG, refresh_articles=True)
        except Exception as e:  # noqa
            sys.stderr.write(repr(e)); os._exit(1)
        os._exit(0)
    if a.child == "candidate_crash":
        batch = store.stage([RECORD], REG, refresh_articles=True)
        assert batch["state"] == "candidate"
        os._exit(74)
    if a.child == "rollback_last":
        with store.connect() as c:
            last = c.execute("select batch_id from update_batches where state='approved' order by created_at desc limit 1").fetchone()[0]
        store.rollback_batch(last)
        os._exit(0)
    if a.child == "finalize_crash":
        batch = store.stage([RECORD], REG, refresh_articles=True)
        articles = [new_article("crash")]
        import admissions_pipeline.store as st
        orig = st.sqlite3.connect

        def hooked(*x, **k):
            c = orig(*x, **k)
            c.set_trace_callback(lambda s: os._exit(75) if s.startswith("UPDATE update_batches SET state='approved'") else None)
            return c
        st.sqlite3.connect = hooked
        store.finalize(batch, articles, bound_qa(batch, articles), REG)
        os._exit(1)  # not reached when the injected crash fires
    os._exit(99)


# ------------------------------------------------------------------ parent
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source"); p.add_argument("--older"); p.add_argument("--out")
    p.add_argument("--child"); p.add_argument("--db"); p.add_argument("--lock")
    a = p.parse_args()
    if a.child:
        return child(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    src, older = Path(a.source), Path(a.older)
    src_sha_before = sha(src)
    master = src
    if PREPARE:  # one prepared reference clone: every case clones IT (byte for byte), and it is the row baseline; the source stays untouched
        ref = out / "_reference"
        ref.mkdir()
        master = ref / "copy.sqlite"
        shutil.copyfile(src, master)
        prepare(master)
    master_sha = sha(master)
    base = dump(master)
    older_heads = heads(older)
    results = []

    def clone(name):
        d = out / name
        d.mkdir()
        t = d / "copy.sqlite"
        shutil.copyfile(master, t)
        assert sha(t) == master_sha
        return t

    def run_child(mode, t, lock=None):
        cmd = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--child", mode, "--db", str(t)] + (["--lock", str(lock)] if lock else [])
        env = dict(os.environ, PYTHONPATH=str(PIPE), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run(cmd, capture_output=True, timeout=60, env=env)
        return r.returncode, r.stderr.decode("utf-8", "replace")[-300:]

    def rec(case, passed, **kw):
        results.append({"case": case, "result": "PASS" if passed else "FAIL", **kw})

    def audit_ok(t):
        from src.integration.db_audit import audit
        r = audit(t, baseline=src, target_kind="copied_real_db")
        return r["ok"], r["invariants"]["DB-09"]["status"], r["summary"]

    def expect(t, want, extra=True):
        d = dump(t)
        return diff(base, d) == want and d["_integrity"] == "ok" and d["_fk"] == 0, diff(base, d)

    def relation(articles):
        """The rows the relation table of G-07 gains when a revised article is approved (only when the clone has the table): exactly one per version the article cites, counted from the article itself."""
        with closing(sqlite3.connect(f"file:{master.as_posix()}?mode=ro", uri=True)) as c:
            has = c.execute("select 1 from sqlite_master where name='revised_article_evidence'").fetchone()
        return {"revised_article_evidence": (0, 0, sum(len(set(a["evidence_ids"])) for a in articles))} if has else {}

    def raises(fn, text):
        try:
            fn()
        except ValueError as e:
            return text in str(e), str(e)
        except Exception as e:  # noqa
            return False, repr(e)
        return False, "no exception"

    # ---- S1 crash inside an uncommitted write transaction
    t = clone("S1"); code, err = run_child("uncommitted", t)
    journal = (t.parent / "copy.sqlite-journal").exists()
    recover_and_close(t); ok, d = expect(t, {})
    rec("S1_crash_in_uncommitted_transaction", code == 73 and ok, exit=code, hot_journal_present_before_recovery=journal, row_diff_vs_original=d)
    # ---- S2 candidate committed, process dies, recovery under the lock
    t = clone("S2"); code, err = run_child("candidate_crash", t)
    st = RevisionStore(t, t.parent / "rec-before.sqlite")
    with ProcessLock(t.parent / "rec.lock"):
        ids = st.recover_candidates()
    ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1), "update_events": (0, 0, 1)})
    with closing(sqlite3.connect(t)) as c:
        states = [r[0] for r in c.execute("select state from update_batches where batch_id=?", (ids[0],))] if ids else []
    au = audit_ok(t)
    rec("S2_candidate_then_crash_then_recover", code == 74 and len(ids) == 1 and states == ["interrupted"] and ok and heads(t) == heads(src) and au[0] and au[1] == "pass", exit=code, recovered=len(ids), batch_state=states, row_diff_vs_original=d, db_audit_ok_db09=au[:2])
    # ---- S3 QA failure never activates
    t = clone("S3"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); accepted = st.finalize(batch, [], {"success": False}, REG)
    ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    with closing(sqlite3.connect(t)) as c:
        bs = c.execute("select state from update_batches where batch_id=?", (batch["batch_id"],)).fetchone()[0]
    rec("S3_QA_failure_is_rejected", accepted is False and bs == "rejected" and ok and heads(t) == heads(src), batch_state=bs, row_diff_vs_original=d)
    # ---- S4 head moved by a separate process: the parent must not overwrite it
    t = clone("S4"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); code, err = run_child("rollback_last", t)
    articles = [new_article("s4")]
    refused, msg = raises(lambda: st.finalize(batch, articles, bound_qa(batch, articles), REG), "concurrent head change")
    ok, d = expect(t, {"update_batches": (0, 1, 1), "batch_evidence": (0, 0, 1), "update_events": (0, 0, 1), "evidence_heads": (0, 1, 0), "article_heads": (0, 2, 0)})
    rec("S4_head_changed_elsewhere_finalize_refused", code == 0 and refused and ok and heads(t) == older_heads, child_exit=code, refusal=msg, heads_equal_older_v05_copy=heads(t) == older_heads, row_diff_vs_original=d, child_stderr=err if code else "")
    # ---- S5 repeat of an unchanged input
    t = clone("S5"); st = RevisionStore(t, t.parent / "b.sqlite")
    states = [st.stage([RECORD], REG)["state"] for _ in range(2)]
    ok, d = expect(t, {"update_batches": (0, 0, 2), "batch_evidence": (0, 0, 2)})
    rec("S5_repeat_same_input_is_no_change", states == ["no_change", "no_change"] and ok and heads(t) == heads(src), states=states, row_diff_vs_original=d)
    # ---- S6 process lock between processes
    t = clone("S6"); lock = out / "S6" / "x.lock"
    with ProcessLock(lock):
        c1, _ = run_child("lock_probe", t, lock)
    with ProcessLock(lock):
        reacquired = True
    c2, _ = run_child("lock_probe", t, lock)
    rec("S6_second_process_refused_then_reacquire", c1 == 42 and reacquired and c2 == 0, while_held_exit=c1, after_release_exit=c2)
    # ================= extra cases for the 'invalid data / failure' part of g4
    bad = json.loads(json.dumps(RECORD)); bad["university"] = "X"
    t = clone("X1"); st = RevisionStore(t, t.parent / "b.sqlite")
    r_, m = raises(lambda: st.stage([bad], REG), "cross-cycle update rejected"); ok, d = expect(t, {})
    rec("X1_wrong_scope_record_rejected_atomically", r_ and ok, error=m, row_diff_vs_original=d)
    bad = json.loads(json.dumps(RECORD)); bad["evidence_id"] = "EV-CLAUDE-TEST-1"; bad["parent_evidence_id"] = "EV-K27-01-d5e70e" if False else next(k for k in base["facts"] if base["facts"][k][3] != RECORD["fact_key"])[0]
    t = clone("X2"); st = RevisionStore(t, t.parent / "b.sqlite")
    r_, m = raises(lambda: st.stage([bad], REG), "correction parent has different case or fact key"); ok, d = expect(t, {})
    rec("X2_parent_of_another_fact_rejected_atomically", r_ and ok, error=m, row_diff_vs_original=d)
    t = clone("X3"); st = RevisionStore(t, t.parent / "b.sqlite")
    r_, m = raises(lambda: st.stage([RECORD, RECORD], REG), "duplicate logical identity"); ok, d = expect(t, {})
    rec("X3_duplicate_logical_identity_rejected", r_ and ok, error=m, row_diff_vs_original=d)
    bad = json.loads(json.dumps(RECORD)); bad["value"] = {"claude": "tampered"}
    t = clone("X4"); st = RevisionStore(t, t.parent / "b.sqlite")
    r_, m = raises(lambda: st.stage([bad], REG), "immutable revision differs"); ok, d = expect(t, {})
    rec("X4_same_id_different_content_rejected", r_ and ok, error=m, row_diff_vs_original=d)
    t = clone("X5"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); articles = [new_article("x5")]; qa = bound_qa(batch, articles); qa["batch_input_sha"] = "0" * 64
    r_, m = raises(lambda: st.finalize(batch, articles, qa, REG), "QA result is not bound"); ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    rec("X5_unbound_QA_result_rejected_batch_stays_candidate", r_ and ok and heads(t) == heads(src), error=m, row_diff_vs_original=d)
    t = clone("X6"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); art = new_article("x6"); art["publish_allowed"] = True; articles = [art]
    r_, m = raises(lambda: st.finalize(batch, articles, bound_qa(batch, articles), REG), "unapproved article state"); ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    rec("X6_article_marked_publishable_rejected", r_ and ok and heads(t) == heads(src), error=m, row_diff_vs_original=d)
    t = clone("X7"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); st.finalize(batch, [], {"success": False}, REG); articles = [new_article("x7")]
    r_, m = raises(lambda: st.finalize(batch, articles, bound_qa(batch, articles), REG), "batch is not eligible"); ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    rec("X7_finalize_of_a_rejected_batch_refused", r_ and ok, error=m, row_diff_vs_original=d)
    foreign = next(k for k in base["facts"] if base["facts"][k][1] != RECORD["case_id"])[0]
    t = clone("X8"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); art = new_article("x8"); art["evidence_ids"] = list(art["evidence_ids"]) + [foreign]; art["text"] = art["text"] + " [" + foreign + "]"; articles = [art]
    r_, m = raises(lambda: st.finalize(batch, articles, bound_qa(batch, articles), REG), "article cites a different cycle"); ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    rec("X8_article_citing_another_case_rejected", r_ and ok and heads(t) == heads(src), error=m, row_diff_vs_original=d)
    # ---- X9 the valid approval path, a crash in the middle of the approval, and rollback
    t = clone("X9A"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); articles = [new_article("x9a")]
    okf = st.finalize(batch, articles, bound_qa(batch, articles), REG)
    ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1), "revised_articles": (0, 0, 1), "update_events": (0, 0, 1), "article_heads": (0, 1, 0), **relation(articles)})
    au = audit_ok(t); h = heads(t)
    rec("X9A_valid_approval_moves_only_the_article_head_and_keeps_all_old_rows", okf is True and ok and au[0] and au[1] == "pass" and h["a"][articles[0]["base_article_id"]] == articles[0]["article_id"], row_diff_vs_original=d, db_audit_ok_db09=au[:2])
    t = clone("X9B"); code, err = run_child("finalize_crash", t)
    j = (t.parent / "copy.sqlite-journal").exists(); recover_and_close(t)
    ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1)})
    st = RevisionStore(t, t.parent / "rb.sqlite")
    with ProcessLock(t.parent / "rb.lock"):
        ids = st.recover_candidates()
    rec("X9B_crash_in_the_middle_of_the_approval_leaves_heads_untouched", code == 75 and ok and heads(t) == heads(src) and len(ids) == 1, exit=code, hot_journal_present_before_recovery=j, row_diff_vs_original=d, recovered=len(ids), child_stderr=err if code != 75 else "")
    t = clone("X9C"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage([RECORD], REG, refresh_articles=True); articles = [new_article("x9c")]; st.finalize(batch, articles, bound_qa(batch, articles), REG)
    st.rollback_batch(batch["batch_id"]); twice, m = raises(lambda: st.rollback_batch(batch["batch_id"]), "rollback would overwrite newer progress")
    ok, d = expect(t, {"update_batches": (0, 0, 1), "batch_evidence": (0, 0, 1), "revised_articles": (0, 0, 1), "update_events": (0, 0, 2), **relation(articles)})
    rec("X9C_rollback_restores_heads_keeps_history_second_rollback_refused", ok and twice and heads(t) == heads(src), second_rollback=m, row_diff_vs_original=d)
    # ---- X11 two processes write at the same moment (not only a probe of the lock)
    for rnd in range(3):
        t = clone("X11_%d" % rnd)
        env = dict(os.environ, PYTHONPATH=str(PIPE), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        cmd = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--child", "stage_once", "--db", str(t)]
        procs = [subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE) for _ in range(2)]
        outs = [pr.communicate(timeout=90) for pr in procs]
        codes = [pr.returncode for pr in procs]; k = codes.count(0)
        d = dump(t)
        ok = diff(base, d) == ({"update_batches": (0, 0, k), "batch_evidence": (0, 0, k)} if k else {}) and d["_integrity"] == "ok" and d["_fk"] == 0 and heads(t) == heads(src)
        rec("X11_%d_two_simultaneous_writers_serialize_without_damage" % rnd, ok and k >= 1, exit_codes=codes, successful_writers=k, row_diff_vs_original=diff(base, d), stderr=[o[1].decode("utf-8", "replace")[-150:] for o in outs if o[1]])
    # ---- X12 a backup that cannot be completed (the target already exists) must stop the update before any change
    t = clone("X12")
    (t.parent / "b.sqlite").write_bytes(b"partial")
    try:
        RevisionStore(t, t.parent / "b.sqlite"); refused = False; msg = "no exception"
    except FileExistsError as e:
        refused = True; msg = str(e)
    ok, d = expect(t, {})
    rec("X12_existing_or_partial_backup_target_stops_the_update_before_any_change", refused and ok, error=msg, row_diff_vs_original=d)
    # ---- X10 informational: nothing in the database forbids a direct write to a head (no trigger; DB-14 is a warning)
    t = clone("X10")
    with closing(sqlite3.connect(t)) as c:
        c.execute("PRAGMA foreign_keys=ON")
        try:
            c.execute("UPDATE evidence_heads SET evidence_id=(SELECT evidence_id FROM evidence_revisions WHERE evidence_id<>? LIMIT 1) WHERE logical_id='tsukuba-ac-ai-faq'", (HEAD_ID,)); c.commit(); direct = "accepted_by_the_database"
        except Exception as e:  # noqa
            direct = "refused:" + type(e).__name__
    if direct.startswith("refused"):  # the clone carries the G-09 head rules: a head cannot be moved to a revision of another logical id
        results.append({"case": "X10_direct_head_write_to_a_foreign_revision_is_refused", "result": "PASS", "database_answer": direct})
    else:
        results.append({"case": "X10_direct_head_write_bypasses_the_update_path", "result": "KNOWN_LIMIT_G09", "database_answer": direct, "meaning": "no database-level protection; the update path protects, a direct writer is not stopped (DB-14 warn). Not counted as a pass"})
    src_sha_after = sha(src)
    summary = {"prepared_with": PREPARE, "source_copy_sha256": src_sha_before, "source_copy_unchanged": src_sha_before == src_sha_after, "source_integrity_unchanged": dump(src)["_integrity"] == "ok",
               "cases": results, "pass": sum(r["result"] == "PASS" for r in results), "fail": sum(r["result"] == "FAIL" for r in results), "known_limit": sum(r["result"].startswith("KNOWN") for r in results)}
    (out / "claude_g4_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False))
    for r in results:
        print(r["result"], r["case"], ("" if r["result"] == "PASS" else json.dumps({k: v for k, v in r.items() if k not in ("case", "result")}, ensure_ascii=False)[:400]))
    return 0 if summary["fail"] == 0 and summary["source_copy_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
