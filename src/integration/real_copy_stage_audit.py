"""Activation of Work's stage-contract-A candidates (PR #61) on DISPOSABLE clones of an audited real database copy; checks computed by Claude.

Usage (private/local inputs; nothing here runs in CI):
  SOGH_G4_PIPELINE=<pipeline root> SOGH_G4_QA_ROOT=<export of this repo> SOGH_G4_VIEW=<active-state.json>
  python -B -X utf8 src/integration/real_copy_stage_audit.py --source <copy v06.sqlite> --candidates <stage-candidates.json> \
      --candidate-view <candidate-full-view.json> --out <new empty dir>

The candidates are NOT activated anywhere except in the clones. `stage` here is the ordinal a quoted sentence may use, not the selection stage of an interview."""
import argparse, hashlib, json, shutil, sqlite3, sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_copy_g4_audit as g4  # noqa: E402  (the module reads its three SOGH_G4_* paths from the environment)
from real_copy_g4_audit import RevisionStore, ProcessLock, REG, canonical, dump, diff, heads, sha  # noqa: E402


def effective(path):
    with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as c:
        facts = {r[0] for r in c.execute("select evidence_id from facts")}
        revs = {r[0]: r[1] for r in c.execute("select evidence_id,parent_evidence_id from evidence_revisions")}
        hs = dict(c.execute("select logical_id,evidence_id from evidence_heads"))
        anc = set()
        for h in hs.values():
            p = revs.get(h)
            while p:
                anc.add(p)
                p = revs.get(p)
        art = {r[0] for r in c.execute("select article_id from article_versions")}
        ah = dict(c.execute("select base_article_id,article_id from article_heads"))
        groups = {(r[0], r[1]) for r in c.execute("select case_id,series from article_versions")}
    return (facts - anc) | set(hs.values()), ah, groups, art


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source"); p.add_argument("--candidates"); p.add_argument("--candidate-view"); p.add_argument("--out")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    src = Path(a.source)
    sha0 = sha(src)
    base = dump(src)
    records = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
    view = json.loads(Path(a.candidate_view).read_text(encoding="utf-8"))
    active = json.loads(g4.VIEW.read_text(encoding="utf-8"))
    articles = [x for x in view["articles"] if x["article_id"] not in {y["article_id"] for y in active["articles"]}]
    results = []

    def rec(case, ok, **kw):
        results.append({"case": case, "result": "PASS" if ok else "FAIL", **kw})

    def clone(name):
        d = out / name
        d.mkdir()
        t = d / "copy.sqlite"
        shutil.copyfile(src, t)
        assert sha(t) == sha0
        return t

    def qa(batch, ok=True):
        return {"success": ok, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical(articles).encode()).hexdigest()}

    # P1 activation
    t = clone("P1"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage(records, REG)
    approved = st.finalize(batch, articles, qa(batch), REG) if batch["state"] == "candidate" else None
    d = diff(base, dump(t))
    want = {"evidence_revisions": (0, 0, 2), "update_batches": (0, 0, 1), "batch_evidence": (0, 0, 2), "revised_articles": (0, 0, 2), "update_events": (0, 0, 1), "article_heads": (0, 2, 0), "evidence_heads": (0, 1, 1)}
    from src.integration.db_audit import audit
    au = audit(t, baseline=src, target_kind="copied_real_db")
    rec("P1_activation_adds_two_revisions_moves_only_heads_and_removes_no_old_row", batch["state"] == "candidate" and approved is True and d == want and au["ok"] and au["invariants"]["DB-09"]["status"] == "pass",
        stage_state=batch["state"], row_diff_vs_original=d, expected=want, db_audit_ok_db09=[au["ok"], au["invariants"]["DB-09"]["status"]])
    ev, ah, groups, versions = effective(t)
    changed_ids = {x["article_id"] for x in articles}
    rec("P2_the_effective_view_recomputed_from_the_clone_equals_the_delivered_candidate_view", ev == set(view["evidence"]) and len(ev) == 50 and len(view["articles"]) == 13 and len(groups) == 13
        and changed_ids <= set(ah.values()) and all(x["article_id"] in set(ah.values()) or x["article_id"] in versions for x in view["articles"]),
        evidence=len(ev), only_in_clone=sorted(ev - set(view["evidence"])), only_in_view=sorted(set(view["evidence"]) - ev), changed_articles_are_heads=changed_ids <= set(ah.values()))
    h_after = heads(t)
    # P3 idempotent re-run on the activated clone
    st2 = RevisionStore(t, t.parent / "b2.sqlite")
    again = st2.stage(records, REG)
    d2 = diff(base, dump(t))
    extra = {k: (d2[k][0], d2[k][1], d2[k][2] - want.get(k, (0, 0, 0))[2]) for k in d2 if d2[k][2] != want.get(k, (0, 0, 0))[2]}
    rec("P3_the_same_candidates_again_are_no_change_and_add_no_business_record", again["state"] == "no_change" and heads(t) == h_after and all(k in ("update_batches", "batch_evidence") for k in extra), state=again["state"], new_rows_beyond_the_first_run=extra)
    # P4 rollback
    st3 = RevisionStore(t, t.parent / "b3.sqlite")
    st3.rollback_batch(batch["batch_id"])
    try:
        st3.rollback_batch(batch["batch_id"]); second = "accepted"
    except ValueError as e:
        second = "refused" if "newer progress" in str(e) else "other:" + str(e)
    rec("P4_rollback_restores_the_old_heads_keeps_the_history_and_a_second_rollback_is_refused", heads(t) == heads(src) and second == "refused", second_rollback=second)
    # P5 QA rejection keeps the heads
    t = clone("P5"); st = RevisionStore(t, t.parent / "b.sqlite")
    batch = st.stage(records, REG); accepted = st.finalize(batch, [], {"success": False}, REG)
    rec("P5_QA_rejection_keeps_the_heads_and_the_business_tables", accepted is False and heads(t) == heads(src) and diff(base, dump(t)) == {"evidence_revisions": (0, 0, 2), "update_batches": (0, 0, 1), "batch_evidence": (0, 0, 2)},
        row_diff_vs_original=diff(base, dump(t)))
    # P6 invalid candidate input rolls back atomically
    for name, mutate, text in (("P6a_wrong_year_scope", lambda r: r.update(fiscal_year=2026), "cross-cycle update rejected"),
                               ("P6b_parent_of_another_fact", lambda r: r.update(parent_evidence_id=next(k for k in base["facts"] if base["facts"][k][3] != r["fact_key"])[0]), "correction parent has different case or fact key")):
        t = clone(name); st = RevisionStore(t, t.parent / "b.sqlite")
        bad = json.loads(json.dumps(records)); mutate(bad[0])
        try:
            st.stage(bad, REG); msg = "no exception"
        except ValueError as e:
            msg = str(e)
        rec(name + "_is_rejected_atomically", text in msg and diff(base, dump(t)) == {}, error=msg)
    # P7 the candidates' parents and the ids
    with closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as c:
        present = [c.execute("select count(*) from facts where evidence_id=? union all select count(*) from evidence_revisions where evidence_id=?", (r["evidence_id"], r["evidence_id"])).fetchall() for r in records]
        parents = [c.execute("select (select count(*) from facts where evidence_id=?)+(select count(*) from evidence_revisions where evidence_id=?)", (r["parent_evidence_id"],) * 2).fetchone()[0] for r in records]
        registered = [c.execute("select count(*) from source_documents where sha256=?", (r["source_sha256"],)).fetchone()[0] for r in records]
    rec("P7_candidate_ids_are_new_and_parents_exist", all(x == [(0,), (0,)] for x in present) and all(n == 1 for n in parents), candidate_ids_new=all(x == [(0,), (0,)] for x in present), parents_found=parents)
    results.append({"case": "P8_source_documents_registration_of_the_candidates_sources", "result": "FINDING", "registered_in_source_documents": registered, "meaning": "a candidate whose source SHA is not in source_documents is accepted by the update path (evidence_revisions has no foreign key to source_documents); the reference gap is a g2 matter"})
    summary = {"source_copy_sha256": sha0, "source_copy_unchanged": sha(src) == sha0, "pass": sum(r["result"] == "PASS" for r in results), "fail": sum(r["result"] == "FAIL" for r in results), "finding": sum(r["result"] == "FINDING" for r in results), "cases": results}
    (out / "claude_stage_activation_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}))
    for r in results:
        print(r["result"], r["case"], "" if r["result"] == "PASS" else json.dumps({k: v for k, v in r.items() if k not in ("case", "result")}, ensure_ascii=False)[:600])
    return 0 if summary["fail"] == 0 and summary["source_copy_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
