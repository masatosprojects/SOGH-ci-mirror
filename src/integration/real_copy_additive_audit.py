"""Applies the additive G-02/G-04/G-05 proposals (src/db_contract/additive_schema.py) to DISPOSABLE clones of an audited real database copy and checks the result.
SELF_VALIDATED (Claude wrote the migration and this check). Nothing is applied to an original or to the audited copy itself.

  python -B -X utf8 src/integration/real_copy_additive_audit.py --source <copy v06.sqlite> --older <copy v05.sqlite> --legacy-export <claude-compatible-export.json with EV-G27C-*> --out <new empty dir>
"""
import argparse, hashlib, json, shutil, sqlite3, sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.db_contract import additive_schema as ad  # noqa: E402
from src.integration.db_audit import audit  # noqa: E402


def app_connect(path):
    """A connection the way SOGH's own code opens one (the write capability registered, recursive triggers ON): the guards of migration 0004 refuse any other connection, which B3 and B5 also check on their own."""
    db = sqlite3.connect(path)
    db.create_function("sogh_write_ok", 0, lambda: 1)
    db.execute("PRAGMA recursive_triggers=ON")
    return db


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(path, skip=()):
    out = {}
    with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as c:
        for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1").fetchall():
            if t not in skip:
                out[t] = sorted(map(repr, c.execute(f'select * from "{t}"').fetchall()))
        out["_integrity"] = c.execute("pragma integrity_check").fetchone()[0]
        out["_fk"] = len(c.execute("pragma foreign_key_check").fetchall())
    return out


def main():
    p = argparse.ArgumentParser()
    for k in ("source", "older", "legacy-export", "out"):
        p.add_argument("--" + k, required=True)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    src = Path(a.source)
    sha0 = sha(src)
    base = dump(src)
    results = []

    def rec(case, ok, **kw):
        results.append({"case": case, "result": "PASS" if ok else "FAIL", **kw})

    def clone(name):
        d = out / name
        d.mkdir()
        t = d / "copy.sqlite"
        shutil.copyfile(src, t)
        return t

    plan = ad.plan(src)
    rec("A1_plan_on_the_audited_copy_is_read_only_and_every_preflight_passes", plan["can_apply"] and sha(src) == sha0 and all(m["would_apply"] for m in plan["migrations"]), plan=plan["migrations"])
    t = clone("A2")
    r = ad.apply(t, confirm_disposable_copy=True)
    after = dump(t, skip=("schema_migrations", "evidence_aliases", "offering_sources", "revised_article_evidence", "revision_reasons", "revision_reason_corrections", "revision_reason_contract", "source_document_metadata", "source_verification_events"))
    au = audit(t, baseline=src, target_kind="copied_real_db")
    with closing(app_connect(t)) as c:
        objs = sorted(x[0] for x in c.execute("select name from sqlite_master where name like 'ux_%' or name like 'trg_alias%' or name like 'trg_new_%'"))
    with closing(app_connect(t)) as c:  # the new link table holds exactly one row per existing offering (nothing is invented) and the schema-state check agrees
        links = c.execute("select count(*) from offering_sources").fetchone()[0]
        offerings_total = c.execute("select count(*) from admission_offerings").fetchone()[0]
        drift = ad.verify_history(c) + ad.verify_schema_state(c)
    rec("A2_apply_adds_only_new_objects_every_old_row_unchanged_and_db_audit_still_passes", r["applied"] == [m[0] for m in ad.MIGRATIONS] and after == {k: v for k, v in base.items()} and au["ok"] and au["invariants"]["DB-09"]["status"] == "pass"
        and links == offerings_total and drift == [] and au["invariants"]["DB-17"]["status"] == "pass" and au["invariants"]["DB-16"]["status"] == "pass",
        applied=r["applied"], offering_sources_rows=links, offerings=offerings_total, schema_state_problems=drift, new_objects=objs, db_audit_ok_db09=[au["ok"], au["invariants"]["DB-09"]["status"]], db_audit_warn=au["summary"]["warn"])
    before = sha(t)
    again = ad.apply(t, confirm_disposable_copy=True)
    rec("A3_a_second_run_changes_nothing", again["applied"] == [] and sha(t) == before, skipped=again["skipped"])
    # the keio cycle has no department: a second one with a missing or empty department must now be refused, other cycles stay possible
    with closing(app_connect(t)) as c:
        c.row_factory = sqlite3.Row
        keio = dict(c.execute("select * from admission_cycles where department is null").fetchone())
        refused = []
        for name, dep in (("null", None), ("empty", "")):
            try:
                c.execute("insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values(?,?,?,?,?,?,?)", ("claude-dup-" + name, keio["university"], keio["faculty"], dep, keio["admission_method"], keio["fiscal_year"], keio["exam_year"]))
                refused.append(name + ":ACCEPTED")
            except sqlite3.IntegrityError:
                refused.append(name + ":refused")
        c.rollback()
        offerings = c.execute("select count(*) from admission_offerings where case_id=?", (keio["case_id"],)).fetchone()[0]
    rec("A4_G04_missing_and_empty_department_collide_and_the_two_keio_entry_months_stay_two_offerings", refused == ["null:refused", "empty:refused"] and offerings == 2, attempts=refused, keio_offerings=offerings)
    # a pre-existing collision stops the run and leaves the file untouched
    t2 = clone("A5")
    with closing(app_connect(t2)) as c:
        c.execute("insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values(?,?,?,?,?,?,?)", ("claude-collision", keio["university"], keio["faculty"], None, keio["admission_method"], keio["fiscal_year"], keio["exam_year"]))
        c.commit()
    b = sha(t2)
    r2 = ad.apply(t2, confirm_disposable_copy=True)
    rec("A5_an_existing_collision_stops_the_run_and_the_file_is_unchanged", r2["rolled_back"] and sha(t2) == b and "0002-g04-cycle-and-offering-identity" in r2["blocked"], blocked=r2["blocked"])
    # G-05 on the migrated clone with the real legacy records
    legacy = json.loads(Path(a.legacy_export).read_text(encoding="utf-8"))["evidence"]
    t3 = clone("A6")
    ad.apply(t3, confirm_disposable_copy=True)
    pairs = {}
    with closing(app_connect(t3)) as c:
        for n in range(1, 7):
            old = f"EV-G27C-0{n}-e1137e"
            root = f"EV-G27-0{n}-e1137e"
            pairs[old] = root
            ad.register_alias(c, old, root, "locator_corrected_copy" if n == 1 else "legacy_compat_id", "same fact delivered under a second id space (G-05)", alias_record=legacy[old])
        c.commit()
        res = {old: ad.resolve(c, old) for old in pairs}
        arts_before = {k: v for k, v in base.items() if k in ("article_versions", "article_evidence", "revised_articles", "article_heads")}
    after3 = dump(t3, skip=("schema_migrations", "evidence_aliases", "offering_sources", "revised_article_evidence", "revision_reasons", "revision_reason_corrections", "revision_reason_contract", "source_document_metadata", "source_verification_events"))
    ok_map = all(res[o]["root"] == r_ for o, r_ in pairs.items())
    corrected = res["EV-G27C-01-e1137e"]["resolved_evidence_id"]
    others_are_roots = all(res[f"EV-G27C-0{n}-e1137e"]["resolved_evidence_id"] == f"EV-G27-0{n}-e1137e" for n in range(2, 7))
    rec("A6_G05_the_six_legacy_ids_resolve_to_their_roots_01_to_the_corrected_current_head_and_no_old_row_changes", ok_map and corrected == "EV-U-8d8e1d177883" and others_are_roots and after3 == base and all(after3[k] == v for k, v in arts_before.items()),
        resolved={o: v["resolved_evidence_id"] for o, v in res.items()}, roots_ok=ok_map, old_tables_unchanged=after3 == base)
    # independent facts stay independent: the two Niigata faculties share a value and a source but are different cycles
    with closing(app_connect(t3)) as c:
        rows = c.execute("select evidence_id, case_id, record_json from facts where fact_key='postal_period' and case_id like 'niigata-%'").fetchall()
        refused = "no pair"
        if len(rows) == 2:
            (e1, c1, r1), (e2, c2, r2_) = rows
            try:
                ad.register_alias(c, "EV-claude-niigata-alias", e1, "legacy_compat_id", "must be refused", alias_record=json.loads(r2_))
                refused = "ACCEPTED"
            except ad.AliasError:
                refused = "refused_by_the_code_layer"
            try:
                c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values(?,?,?,?,?,?,?)", ("EV-claude-niigata-raw", e1, c2, "postal_period", "legacy_compat_id", "x", "t"))
                refused += "|raw:ACCEPTED"
            except sqlite3.DatabaseError:
                refused += "|raw:refused_by_the_database"
            c.rollback()
    rec("A7_G05_same_value_in_another_cycle_is_independent_never_an_alias", refused == "refused_by_the_code_layer|raw:refused_by_the_database", niigata_postal_period=refused)
    # unknown, cyclic and id-reusing aliases
    with closing(app_connect(t3)) as c:
        neg = {}
        for name, stmt in (("unknown_root", ("EV-claude-a", "EV-NO-ROOT", "case", "quota")), ("alias_of_alias", ("EV-claude-b", "EV-G27C-02-e1137e", "tsukuba-klis-general-front-2027", "online_period")), ("alias_named_like_a_real_id", ("EV-G27-03-e1137e", "EV-G27-02-e1137e", "tsukuba-klis-general-front-2027", "online_period"))):
            try:
                c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values(?,?,?,?,?,?,?)", (stmt[0], stmt[1], stmt[2], stmt[3], "legacy_compat_id", "x", "t"))
                neg[name] = "ACCEPTED"
            except sqlite3.DatabaseError:
                neg[name] = "refused"
        c.rollback()
        for stmt in ("update evidence_aliases set reason='x'", "delete from evidence_aliases"):
            try:
                c.execute(stmt); neg[stmt.split()[0]] = "ACCEPTED"
            except sqlite3.DatabaseError:
                neg[stmt.split()[0]] = "refused"
        c.rollback()
    rec("A8_G05_unknown_root_alias_of_alias_id_reuse_and_edits_of_an_alias_are_refused", all(v == "refused" for v in neg.values()), attempts=neg)
    # ---- G-02 history contract and G-09 triggers on the migrated clone (t3 holds the six aliases; use a fresh migrated clone for the rest)
    t4 = clone("B1")
    r4 = ad.apply(t4, confirm_disposable_copy=True)
    with closing(app_connect(t4)) as c:
        uv = c.execute("pragma user_version").fetchone()[0]
        hist = c.execute("select version, from_version, seq from schema_migrations order by seq").fetchall()
        last_sv = c.execute("select version from schema_versions order by rowid desc limit 1").fetchone()
    rec("B1_G02_history_user_version_and_from_version_follow_the_contract_without_an_invented_baseline",
        [h[0] for h in hist] == [m[0] for m in ad.MIGRATIONS] and uv == ad._seq(ad.MIGRATIONS[-1][0]) and hist[0][1] == (last_sv[0] if last_sv else None) and [h[1] for h in hist[1:]] == [h[0] for h in hist[:-1]] and ad.plan(t4)["drift"] == [],
        history=[(h[0], h[1]) for h in hist], user_version=uv)
    # a tampered history is detected (the throw-away clone's own protection is dropped first, as a deliberate saboteur would)
    t5 = clone("B2")
    ad.apply(t5, confirm_disposable_copy=True)
    with closing(app_connect(t5)) as c:
        c.execute("drop trigger trg_ao_schema_migrations_update")
        c.execute("update schema_migrations set checksum=? where seq=2", ("0" * 64,))
        c.commit()
    drift = ad.plan(t5)["drift"]
    try:
        ad.apply(t5, confirm_disposable_copy=True); raised = "NO ERROR"
    except ad.MigrationError as e:
        raised = "raised" if "checksum mismatch" in str(e) else str(e)
    rec("B2_G02_a_changed_checksum_is_detected_and_apply_refuses", any("checksum mismatch" in d for d in drift) and raised == "raised", drift=drift)
    with closing(app_connect(t4)) as c:
        c.row_factory = sqlite3.Row
        append_only = [t for t in ad.TABLE_CLASS["A"] if c.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone()]
        outcome = {}
        for t in append_only:
            n = c.execute(f'select count(*) from "{t}"').fetchone()[0]
            if not n:
                outcome[t] = "empty"
                continue
            col = c.execute(f'pragma table_info("{t}")').fetchone()[1]
            res = []
            for stmt in (f'update "{t}" set "{col}"="{col}"', f'delete from "{t}"'):
                try:
                    c.execute(stmt); res.append("ACCEPTED")
                except sqlite3.DatabaseError:
                    res.append("refused")
            c.rollback()
            outcome[t] = "/".join(res)
    rec("B3_G09_every_non_empty_append_only_table_of_the_real_clone_refuses_update_and_delete", all(v in ("empty", "refused/refused") for v in outcome.values()) and sum(v == "refused/refused" for v in outcome.values()) >= 8, tables=outcome)
    after_b = dump(t4, skip=("schema_migrations", "evidence_aliases", "offering_sources", "revised_article_evidence", "revision_reasons", "revision_reason_corrections", "revision_reason_contract", "source_document_metadata", "source_verification_events"))
    rec("B4_G09_the_protection_changed_no_existing_row", after_b == base)
    with closing(app_connect(t4)) as c:
        batch = c.execute("select batch_id from update_batches where state='approved' limit 1").fetchone()[0]
        res = {}
        for name, stmt in (("approved_to_candidate", "update update_batches set state='candidate' where batch_id=?"), ("rewrite_before_json", "update update_batches set before_json='{}' where batch_id=?"), ("delete_batch", "delete from update_batches where batch_id=?")):
            try:
                c.execute(stmt, (batch,)); res[name] = "ACCEPTED"
            except sqlite3.DatabaseError:
                res[name] = "refused"
        c.rollback()
        head = c.execute("select logical_id from evidence_heads limit 1").fetchone()[0]
        other = c.execute("select evidence_id from evidence_revisions where logical_id<>? limit 1", (head,)).fetchone()
        try:
            c.execute("update evidence_heads set evidence_id=? where logical_id=?", (other[0], head)); res["head_to_another_logical_id"] = "ACCEPTED"
        except sqlite3.DatabaseError:
            res["head_to_another_logical_id"] = "refused"
        c.rollback()
    rec("B5_G09_a_batch_cannot_be_reversed_or_rewritten_and_a_head_cannot_move_to_another_logical_id", all(v == "refused" for v in res.values()), attempts=res)
    # B7: any program without the write capability (a bare sqlite3 connection) is refused on the real clone's guarded tables, and a REPLACE by a SOGH connection is refused too; nothing changes
    t7 = clone("B7")
    ad.apply(t7, confirm_disposable_copy=True)
    h7 = sha(t7)
    foreign = {}
    with closing(sqlite3.connect(t7)) as c:
        for name, stmt in (("insert_or_ignore_facts", "insert or ignore into facts select * from facts"), ("replace_article_versions", "insert or replace into article_versions select * from article_versions"),
                           ("update_head", "update evidence_heads set evidence_id=evidence_id"), ("delete_heads", "delete from evidence_heads"),
                           ("approve_by_sql", "update update_batches set state='approved' where state='candidate'"), ("forged_batch", "insert or replace into update_batches select * from update_batches")):
            try:
                c.execute(stmt); foreign[name] = "ACCEPTED"
            except sqlite3.DatabaseError as e:
                foreign[name] = "refused:" + ("gate" if "sogh_write_ok" in str(e) else "append-only" if "append-only" in str(e) or "never" in str(e) else str(e)[:40])
        c.rollback()
    with closing(app_connect(t7)) as c:
        try:
            c.execute("insert or replace into facts select * from facts"); foreign["replace_facts_by_a_sogh_connection"] = "ACCEPTED"
        except sqlite3.DatabaseError:
            foreign["replace_facts_by_a_sogh_connection"] = "refused:append-only"
        c.rollback()
    rec("B7_G09_a_bare_connection_and_a_replace_are_refused_on_the_real_clone_and_nothing_changes", all(v.startswith("refused") for v in foreign.values()) and sha(t7) == h7, attempts=foreign)
    # C1/C2: G-07 and G-11 on a clone of the audited copy. The expected numbers are counted from the records themselves, not from the migration's own output.
    t8 = clone("C1")
    ad.apply(t8, confirm_disposable_copy=True)
    with closing(sqlite3.connect(f"file:{t8.as_posix()}?mode=ro", uri=True)) as c:
        revised = c.execute("select article_id, record_json from revised_articles").fetchall()
        expected = sum(len(set(json.loads(rj).get("evidence_ids") or [])) for _, rj in revised)
        rows = c.execute("select count(*) from revised_article_evidence").fetchone()[0]
        mismatch = c.execute("select count(*) from v_revised_article_evidence_mismatch").fetchone()[0]
        root_row = c.execute("select root_evidence_id from v_evidence_root where evidence_id='EV-G27-01-e1137e'").fetchone()
        impacted = ad.impacted_articles(c, "EV-G27-01-e1137e") if root_row else []
        reasons = c.execute("select count(*) from revision_reasons").fetchone()[0]
        status = dict(c.execute("select reason_status, count(*) from v_batch_reason_status group by 1").fetchall())
        missing_after = status.get("missing", 0)
        orphans = c.execute("select count(*) from v_evidence_orphans").fetchone()[0]
    rec("C1_G07_the_relation_has_exactly_one_row_per_cited_version_of_every_revised_article_and_no_mismatch", revised and rows == expected and mismatch == 0 and orphans == 0, revised_articles=len(revised), relation_rows=rows, expected_from_the_records=expected, mismatches=mismatch, orphans=orphans)
    rec("C2_G11_no_reason_was_invented_for_the_past_and_the_status_view_says_so", reasons == 0 and missing_after == 0 and status.get("not_recorded_before_the_contract", 0) > 0 and "recorded" not in status, reasons=reasons, status=status, impacted_articles_for_the_root_of_EV_G27_01=len(impacted))
    # D1/D2: G-06 and G-03 on a clone of the audited copy
    t9 = clone("D1")
    ad.apply(t9, confirm_disposable_copy=True)
    with closing(sqlite3.connect(f"file:{t9.as_posix()}?mode=ro", uri=True)) as c:
        sources = c.execute("select count(*) from source_documents").fetchone()[0]
        status = c.execute("select count(*), sum(bytes_match_recorded_sha='not_run' and stored_file_matches_record='not_run' and official_site_authenticity='not_run' and content_meaning_checked='not_run') from v_source_verification_status").fetchone()
        metadata = c.execute("select count(*) from source_document_metadata").fetchone()[0]
        events = c.execute("select count(*) from source_verification_events").fetchone()[0]
        plans = {}
        for table, col in (("evidence_revisions", "parent_evidence_id"), ("evidence_revisions", "logical_id"), ("article_evidence", "evidence_id"), ("facts", "source_sha256"), ("update_events", "batch_id"), ("batch_evidence", "evidence_id"), ("revised_article_evidence", "evidence_id")):
            plans[f"{table}.{col}"] = " ".join(r[3] for r in c.execute(f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {col} = ?", ("x",)))
        scans = [k for k, v in plans.items() if "SCAN" in v or "USING INDEX" not in v and "USING COVERING INDEX" not in v]
    rec("D1_G06_nothing_was_verified_or_given_a_date_and_every_stored_source_says_not_run_on_every_level", sources > 0 and status[0] == sources and status[1] == sources and metadata == 0 and events == 0, stored_sources=sources, all_levels_not_run=status[1], metadata_rows=metadata, verification_events=events)
    rec("D2_G03_the_seven_lookups_use_an_index_on_the_audited_copys_clone_small_data_only", not scans, scans=scans, scale="5 cases only; national-scale performance is not_run")
    # E1: M-14 on a clone of the audited copy: the replay of the recorded approvals equals the current heads, and the past before the first approval has none
    t10 = clone("E1")
    ad.apply(t10, confirm_disposable_copy=True)
    with closing(sqlite3.connect(f"file:{t10.as_posix()}?mode=ro", uri=True)) as c:
        cur = {"evidence": dict(c.execute("select logical_id, evidence_id from evidence_heads").fetchall()), "articles": dict(c.execute("select base_article_id, article_id from article_heads").fetchall())}
        events = c.execute("select count(*), min(created_at), max(created_at) from v_head_events").fetchone()
        replay_now = ad.heads_as_of(c, "9999-12-31")
        before_all = ad.heads_as_of(c, "0000-01-01")
        approvals = c.execute("select count(*) from v_head_events where event = 'approved'").fetchone()[0]
    au10 = audit(t10, baseline=src, target_kind="copied_real_db")
    rec("E1_M14_the_replay_of_the_recorded_approvals_equals_the_current_heads_of_the_real_clone", replay_now == cur and before_all == {"evidence": {}, "articles": {}} and events[0] > 0 and au10["invariants"]["DB-18"]["status"] == "pass",
        events=events[0], approvals=approvals, evidence_heads=len(cur["evidence"]), article_heads=len(cur["articles"]), db18=au10["invariants"]["DB-18"]["status"])
    # restore from a backup of the migrated clone
    t6 = out / "B6_restored.sqlite"
    with closing(sqlite3.connect(f"file:{t4.as_posix()}?mode=ro", uri=True)) as s_, closing(app_connect(t6)) as d_:
        s_.backup(d_)
    with closing(app_connect(t6)) as c:
        trg = c.execute("select count(*) from sqlite_master where type='trigger'").fetchone()[0]
        uv6 = c.execute("pragma user_version").fetchone()[0]
    rec("B6_a_backup_of_the_migrated_clone_restores_with_its_rows_triggers_and_user_version", dump(t6) == dump(t4) and trg > 10 and uv6 == ad._seq(ad.MIGRATIONS[-1][0]) and ad.plan(t6)["drift"] == [], triggers=trg, user_version=uv6)
    summary = {"source_copy_sha256": sha0, "source_copy_unchanged": sha(src) == sha0, "pass": sum(r["result"] == "PASS" for r in results), "fail": sum(r["result"] == "FAIL" for r in results), "cases": results}
    (out / "claude_additive_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}))
    for r in results:
        print(r["result"], r["case"], "" if r["result"] == "PASS" else json.dumps({k: v for k, v in r.items() if k not in ("case", "result")}, ensure_ascii=False)[:500])
    return 0 if summary["fail"] == 0 and summary["source_copy_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
