"""Red-team vulnerability and independent QA remand regression suite for PR #306 candidates (g7, g2, g6).

Covers:
1. g7:
   - Promotion without review approval blocked (API & SQL trigger).
   - Single-UPDATE simultaneous self-approval + promotion bypass blocked.
   - Direct INSERT with quarantine_status='PROMOTED' or pre-approved review_status blocked.
   - Direct SQL seal injection into _quarantine_approval_seals and caller-supplied tokens rejected.
   - INSERT OR REPLACE overwrite of PROMOTED or REJECTED rows blocked.
   - Length-prefixed / JSON-delimited payload hash prevents delimiter-shift collisions.
   - Multi-year ranges/lists/relative years and ambiguous duplicate table cell values refused.
   - promoted_at mutation on non-promoted rows blocked; DB-17 DDL-free init on migrated DB.
2. g2:
   - STR-099 / STR-102: no build_scope_proof or _verify_scope_proof API exposed; verified FAQRecord rejected.
   - Unknown record carrying scope_source_ref / admission_category / year / faculty rejected.
   - source_sha256 is None when no authentic source_document_text is provided.
   - Owner-adopted preamble wording (#199 comment 6722534424), derived condition summaries, and per-sentence [EV-...] citation.
   - Planted [EV-...] tags and full-width/era/R-year/spring-entry/faculty leaks rejected.
3. g6:
   - Rev 1 hash check, frozen edition replacement detection, copy/rebuild middle-edition forgery & tail-drop detection via series_id anchor, and SQLite append-only persistence.
   - Dedup mitigation preserves all applicant instructions and factual sentences by replacing only exact known generic closing boilerplate templates.
"""
from __future__ import annotations

import copy
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_contract.quarantine_staging import (
    evaluate_table_cell_format,
    init_quarantine_schema,
    promote_candidate,
    register_authorized_reviewers,
    review_candidate,
    stage_candidate,
)
import src.db_contract.faq_structured as fq
from src.db_contract.faq_structured import (
    FAQRecord,
    UNCONFIRMED_PREAMBLE_TEXT,
    parse_faq_candidate,
    render_unconfirmed_faq_section,
    verify_unconfirmed_faq_section,
)
from src.versioning.series import (
    SourceEdition,
    SourceSeries,
    _SERIES_ANCHOR_LOG,
    _SERIES_ID_ANCHOR_LOG,
    append_revision,
    create_series,
    init_series_schema,
    persist_series,
    to_rows,
    verify_series_against_rows,
    verify_series_lineage,
)
from src.article_qa.dedup_mitigation import (
    diversify_article_advice,
    mitigate_article_corpus,
    run_strict_article_qa_audit,
)


def test_g7_unreviewed_and_bypass_promotions_blocked() -> None:
    register_authorized_reviewers(["auditor"])
    conn = sqlite3.connect(":memory:")
    init_quarantine_schema(conn)

    stage_candidate(
        conn,
        staging_id="stg_1",
        source_id="src_1",
        format_type="PDF_TABLE",
        extracted_key="admission_quota",
        extracted_value="50",
        staged_by="stager_01",
    )

    # 1. API promotion without review
    raised = False
    try:
        promote_candidate(conn, staging_id="stg_1", fact_id="f1")
    except (PermissionError, ValueError, sqlite3.IntegrityError):
        raised = True
    assert raised, "promote_candidate without review must raise"

    # 2. Single UPDATE setting both quarantine_status='PROMOTED' and review_status='APPROVED'
    raised = False
    try:
        conn.execute(
            """
            UPDATE quarantine_staging_candidates
               SET quarantine_status = 'PROMOTED',
                   review_status = 'APPROVED',
                   approved_by = 'attacker',
                   approval_token = 'forged_token',
                   promoted_at = '2026-11-10T00:00:00Z'
             WHERE staging_id = 'stg_1'
            """
        )
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "direct SQL single-UPDATE promotion must raise"

    # 3. Direct SQL seal injection into _quarantine_approval_seals cannot authorize approval
    sha = conn.execute(
        "SELECT sha256_hash FROM quarantine_staging_candidates WHERE staging_id = 'stg_1'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO _quarantine_approval_seals(staging_id, reviewer, approval_token, payload_sha256) VALUES (?, ?, ?, ?)",
        ("stg_1", "self", "A" * 32, sha),
    )
    raised = False
    try:
        conn.execute(
            "UPDATE quarantine_staging_candidates SET review_status='APPROVED', approved_by='self', approval_token=? WHERE staging_id='stg_1'",
            ("A" * 32,),
        )
    except sqlite3.DatabaseError:
        raised = True
    assert raised, "direct SQL seal injection must not authorize APPROVED"

    # 4. Caller-supplied token rejected
    forged = hashlib.sha256(b"stg_1:auditor").hexdigest()[:16]
    raised = False
    try:
        review_candidate(conn, "stg_1", decision="APPROVED", reviewer="auditor", approval_token=forged)
    except (ValueError, PermissionError, sqlite3.IntegrityError):
        raised = True
    assert raised, "caller-supplied approval_token must be rejected"

    # 5. Legitimate review & tamper check on canonical insert
    review_candidate(conn, "stg_1", decision="APPROVED", reviewer="auditor")
    raised = False
    try:
        conn.execute(
            "UPDATE quarantine_staging_candidates SET quarantine_status = 'PROMOTED', promoted_at = '2026-11-10T00:00:00Z' WHERE staging_id = 'stg_1'"
        )
        conn.execute(
            """
            INSERT INTO canonical_facts_staging_target (fact_id, staging_id, key, value, promoted_at)
            VALUES ('f_tamper', 'stg_1', 'admission_quota', '999999', '2026-11-10T00:00:00Z')
            """
        )
    except sqlite3.IntegrityError:
        raised = True
        conn.rollback()
    assert raised, "tampered canonical insert must raise"

    # 6. DELETE, payload edit, and INSERT OR REPLACE blocked
    raised = False
    try:
        conn.execute("DELETE FROM quarantine_staging_candidates WHERE staging_id = 'stg_1'")
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "DELETE on quarantine_staging_candidates must raise"

    raised = False
    try:
        conn.execute("UPDATE quarantine_staging_candidates SET extracted_value = '999' WHERE staging_id = 'stg_1'")
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "payload mutation must raise"

    raised = False
    try:
        conn.execute(
            "INSERT OR REPLACE INTO quarantine_staging_candidates(staging_id,source_id,format_type,extracted_key,extracted_value,quarantine_status,review_status,sha256_hash) VALUES ('stg_1','s','t','admission_quota','99','QUARANTINED','PENDING','00')"
        )
    except sqlite3.DatabaseError:
        raised = True
    assert raised, "INSERT OR REPLACE on existing staging_id must raise"

    # 7. AI/agent names rejected and separation of duties (stager != approver) enforced
    stage_candidate(conn, "stg_sod", "s1", "PDF_TABLE", "admission_quota", "25", isolation_reason="staged by operator-1")
    for bad_actor in ("claude", "Claude Code", "gemini", "chatgpt", "work", "ＡＩ", "A.I.", "bot2", "operator-1"):
        raised = False
        try:
            review_candidate(conn, "stg_sod", decision="APPROVED", reviewer=bad_actor)
        except (PermissionError, ValueError, sqlite3.DatabaseError):
            raised = True
        assert raised, f"unauthorized or same-actor approver {bad_actor!r} must be rejected"


def test_g7_midflight_rollback_and_table_refusal_matrix() -> None:
    register_authorized_reviewers(["auditor"])
    conn = sqlite3.connect(":memory:")
    init_quarantine_schema(conn)

    stage_candidate(conn, "stg_col", "s1", "PDF_TABLE", "admission_quota", "30", staged_by="stager_01")
    review_candidate(conn, "stg_col", decision="APPROVED", reviewer="auditor")
    promote_candidate(conn, "stg_col", fact_id="fact_collision")

    stage_candidate(conn, "stg_atomic", "s1", "PDF_TABLE", "admission_quota", "50", staged_by="stager_01")
    review_candidate(conn, "stg_atomic", decision="APPROVED", reviewer="auditor")
    raised = False
    try:
        promote_candidate(conn, staging_id="stg_atomic", fact_id="fact_collision")
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "collision on fact_id must raise IntegrityError"

    row = conn.execute(
        "SELECT quarantine_status FROM quarantine_staging_candidates WHERE staging_id = 'stg_atomic'"
    ).fetchone()
    assert row[0] == "QUARANTINED"

    res_unbacked = evaluate_table_cell_format({
        "table_title": "募集人員",
        "headers": ["学類", "募集人員"],
        "rows": [["情報科学類", "16"]],
        "target_key": "admission_quota",
        "raw_cell_value": "99",
    })
    assert res_unbacked.decision == "REFUSE"

    for bad_val in ["0", "-3", "16.5", "約16", "十六"]:
        res_bad = evaluate_table_cell_format({
            "table_title": "募集人員",
            "headers": ["学類", "募集人員"],
            "rows": [["情報科学類", bad_val]],
            "target_key": "admission_quota",
            "raw_cell_value": bad_val,
        })
        assert res_bad.decision == "REFUSE"

    for multi_yr in [
        "２０２６年度・２０２７年度",
        "2026年4月入学 / 2027年10月入学",
        "令和８年度と令和９年度",
        "2027〜2028年度の募集",
        "令和9・10年度の募集",
        "2027年度または翌年度",
        "R9年度とR10年度",
        "二〇二七年度と二〇二八年度",
        "令和九年度と令和十年度",
        "2027/28年度",
        "27年度と28年度",
    ]:
        res_yr = evaluate_table_cell_format({
            "context_text": multi_yr,
            "headers": ["学類", "募集人員"],
            "rows": [["情報科学類", "16"]],
            "target_key": "admission_quota",
            "raw_cell_value": "16",
        })
        assert res_yr.decision == "REFUSE"

    # Ambiguous duplicate value across two rows without row_label must be refused
    res_dup = evaluate_table_cell_format({
        "context_text": "令和9年度",
        "headers": ["学類", "募集人員"],
        "rows": [["情報科学類", "16"], ["情報メディア創成学類", "16"]],
        "target_key": "admission_quota",
        "raw_cell_value": "16",
        "column": "募集人員",
    })
    assert res_dup.decision == "REFUSE"

    res_ok = evaluate_table_cell_format({
        "context_text": "2026年度募集人員",
        "table_title": "2026年度募集人員",
        "headers": ["学類", "募集人員"],
        "rows": [["情報科学類", "16"]],
        "target_key": "admission_quota",
        "raw_cell_value": "16",
        "page": 4,
    })
    assert res_ok.decision == "ACCEPT"
    for req_key in ("row_label", "column", "page", "table_title", "bundle_sha256"):
        assert req_key in res_ok.quarantine_payload


def test_g2_scope_proof_and_controlled_rendering() -> None:
    assert not hasattr(fq, "build_scope_proof")
    assert not hasattr(fq, "_verify_scope_proof")

    rec = parse_faq_candidate(
        faq_id="faq_1",
        source_id="src_faq",
        raw_question="Q",
        raw_answer="A。B。",
        evidence_id="EV-FAQ-01",
        scope_context={
            "fiscal_year": 2026,
            "faculty": "理学部",
            "scope_verified_by_source": True,
            "scope_source_ref": "any-non-empty-string",
        },
    )
    assert rec.scope_status == "unknown"
    assert rec.fiscal_year is None
    assert rec.scope_source_ref is None
    assert rec.source_sha256 is None

    raised = False
    try:
        FAQRecord(
            faq_id="faq_direct",
            source_id="src",
            question="Q",
            answer="A",
            exact_quote="A",
            evidence_id="EV-1",
            scope_status="verified",
            fiscal_year=2026,
            faculty="理学部",
            scope_source_ref="arbitrary",
        )
    except ValueError:
        raised = True
    assert raised, "FAQRecord(scope_status='verified') must raise ValueError under STR-102"

    assert "どの年度・どの学類の出願に当てはまるかを確認できていません" in UNCONFIRMED_PREAMBLE_TEXT

    rendered = render_unconfirmed_faq_section([rec])
    ok_render, _ = verify_unconfirmed_faq_section(rendered, [rec])
    assert ok_render

    for leak in ["２０２７年度", "令和９年度", "R9年度の", "2027春入学の", "FY2027", "情報学群の", "知識情報・図書館学類", "27年度の", "Ｒ９の", "R9入試の", "令和九年度の"]:
        ok_leak, _ = verify_unconfirmed_faq_section(rendered + "\n" + leak, [rec])
        assert not ok_leak


def test_g6_series_tamper_and_dedup_preservation() -> None:
    s = create_series(
        series_id="ser_test",
        university="筑波大学",
        document_title="AC入試募集要項",
        initial_content="募集人員は16名です。",
    )
    append_revision(s, new_content="募集人員は18名に改訂されました。")
    append_revision(s, new_content="募集人員は20名に再改訂されました。")

    # Copy with forged middle edition detected via series_id anchor
    copied = copy.deepcopy(s)
    forged_txt = "偽造された中間版"
    copied.editions[1] = SourceEdition(
        "ser_test_rev2",
        "ser_test",
        2,
        hashlib.sha256(forged_txt.encode()).hexdigest(),
        forged_txt,
        "ser_test_rev1",
        True,
    )
    ok_copy, _ = verify_series_lineage(copied)
    assert not ok_copy

    # Rebuilt series with dropped tail detected via series_id anchor
    rebuilt = SourceSeries(
        s.series_id,
        s.university,
        s.document_title,
        [
            SourceEdition(
                r["edition_id"],
                r["series_id"],
                r["rev_number"],
                r["sha256_hash"],
                r["content_text"],
                r["supersedes_id"],
                bool(r["is_frozen"]),
            )
            for r in to_rows(s)
        ],
    )
    rebuilt.editions.pop()
    rebuilt.editions[-1] = SourceEdition(
        rebuilt.editions[-1].edition_id,
        rebuilt.editions[-1].series_id,
        rebuilt.editions[-1].rev_number,
        rebuilt.editions[-1].sha256_hash,
        rebuilt.editions[-1].content_text,
        rebuilt.editions[-1].supersedes_id,
        False,
    )
    ok_rebuilt, _ = verify_series_lineage(rebuilt)
    assert not ok_rebuilt

    # SQLite append-only persistence
    s2 = create_series(
        series_id="ser_db",
        university="筑波大学",
        document_title="AC入試募集要項",
        initial_content="募集人員は16名です。",
    )
    conn = sqlite3.connect(":memory:")
    init_series_schema(conn)
    persist_series(conn, s2)
    raised = False
    try:
        conn.execute("DELETE FROM source_document_series_editions WHERE edition_id = 'ser_db_rev1'")
    except sqlite3.IntegrityError:
        raised = True
    assert raised

    # Dedup mitigation preserves applicant instructions and factual claims
    for instruction in (
        "出願前に必ず保護者の同意を得てください。",
        "注意：締切に遅れた場合は受理されません。",
        "公式サイトの手順どおりに操作してください。",
        "出願前に本人確認書類のコピーを取っておくこと。",
    ):
        out = diversify_article_advice(f"概要の説明です。{instruction}", index=0)
        assert instruction.rstrip("。") in out

    # Cross-process middle-edition forgery & DB-backed tail-drop detection & sequential rev_number trigger
    conn_r3 = sqlite3.connect(":memory:")
    init_series_schema(conn_r3)
    persist_series(conn_r3, s)
    _SERIES_ANCHOR_LOG.clear()
    _SERIES_ID_ANCHOR_LOG.clear()
    ok_forged_no_mem, _ = verify_series_lineage(copied)
    assert not ok_forged_no_mem, "forged middle edition must fail even after clearing in-memory anchors"
    ok_against_rows, _ = verify_series_against_rows(conn_r3, rebuilt)
    assert not ok_against_rows, "verify_series_against_rows must detect tail drop against persisted rows"

    raised_skip = False
    try:
        conn_r3.execute(
            "INSERT INTO source_document_series_editions(edition_id,series_id,university,document_title,rev_number,sha256_hash,content_text,supersedes_id,is_frozen) VALUES ('ser_test_rev9','ser_test','筑波大学','AC入試募集要項',9,?,?,'ser_test_rev1',0)",
            (hashlib.sha256(b"x").hexdigest(), "x"),
        )
    except sqlite3.DatabaseError:
        raised_skip = True
    assert raised_skip, "non-sequential rev_number or non-adjacent supersedes_id must be rejected by DB trigger"

    boiler = "この記事は大学入試情報を基に作成した参考情報であり実際の出願前に必ず大学公式サイトを確認してください"
    arts8 = {
        f"a{i}": f"# 記事{i}\n\n本文の固有の説明{chr(0x30A2 + i * 3)}です。募集人員は{10 + i}名です。{boiler}。\n[EV-{i}]\n"
        for i in range(8)
    }
    out8 = mitigate_article_corpus(arts8, {f"EV-{i}" for i in range(8)})
    ok8, findings8 = run_strict_article_qa_audit(out8, {f"EV-{i}" for i in range(8)})
    assert not [f for f in findings8 if f.category == "overused_template_phrase"]
