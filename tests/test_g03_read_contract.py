"""Independent tests of the M1.g3 formal read contract (`src/db_contract/historical_read.py`, docs/G03_READ_CONTRACT_2026-11-07.md).

Every database here is SYNTHETIC (an invented cycle, invented facts, a temporary file); nothing touches a real database, a source file or Work's product.
A pass here is a pass of the CONTRACT's reference reader on synthetic data. It is NOT a pass of Work's product path (not connected: NOT_RUN) and NOT the M1.g3 acceptance.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.db_contract import additive_schema as ad
from src.db_contract import historical_read as hr

CASE, OTHER_CASE = "fiction-case", "fiction-other-case"
A, B, C = "a" * 64, "b" * 64, "c" * 64
EV, EV2, EV_OTHER = "EV-1", "EV-2", "EV-OTHER"
SCOPE = "department_and_method"
CYCLE = {"university": "fiction university", "faculty": "faculty", "department": "department", "admission_method": "method", "fiscal_year": 2027}

BASE_DDL = """
CREATE TABLE admission_cycles(case_id TEXT PRIMARY KEY, university TEXT NOT NULL, faculty TEXT NOT NULL, department TEXT, admission_method TEXT NOT NULL, fiscal_year INTEGER NOT NULL);
CREATE TABLE source_documents(sha256 TEXT PRIMARY KEY, url TEXT NOT NULL);
CREATE TABLE facts(evidence_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, fact_key TEXT NOT NULL, value_json TEXT NOT NULL, record_json TEXT NOT NULL);
CREATE TABLE evidence_revisions(evidence_id TEXT PRIMARY KEY, logical_id TEXT NOT NULL, case_id TEXT NOT NULL, fact_key TEXT NOT NULL, source_sha256 TEXT NOT NULL, parent_evidence_id TEXT, record_json TEXT NOT NULL);
CREATE TABLE evidence_heads(logical_id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL);
CREATE TABLE article_versions(article_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE article_evidence(article_id TEXT NOT NULL, evidence_id TEXT NOT NULL, PRIMARY KEY(article_id, evidence_id));
CREATE TABLE revised_articles(article_id TEXT PRIMARY KEY, base_article_id TEXT NOT NULL);
CREATE TABLE revised_article_evidence(article_id TEXT NOT NULL, evidence_id TEXT NOT NULL, case_id TEXT NOT NULL, PRIMARY KEY(article_id, evidence_id));
"""
LOOSE_HISTORY_DDL = """
CREATE TABLE restore_events(restore_id, kind, archive_sha256, source_db_sha256, approved_by, approved_at, approval_ref);
CREATE TABLE restore_revocations(restore_id, revoked_by, revoked_at, reason);
CREATE TABLE restored_articles(article_id, restore_id);
CREATE TABLE evidence_history_versions(version_id, evidence_id, case_id, source_sha256, row_json, row_digest, archive_row_sha256, restore_id);
CREATE TABLE article_history_pins(article_id, evidence_id, version_id, case_id, scope, source_sha256, row_digest, restore_id);
"""


def record(**over):
    rec = {"scope": SCOPE, "locator": "page 6", "value": {"quota": 16}, **CYCLE}
    rec.update(over)
    return rec


def make_row(evidence_id=EV, case_id=CASE, source=A, value='{"quota":16}', **over_record):
    return {"evidence_id": evidence_id, "case_id": case_id, "fact_key": "quota", "source_sha256": source, "value_json": value,
            "record_json": json.dumps(record(**over_record), ensure_ascii=False, sort_keys=True)}


def put_version(db, row, version_id="HV-1", restore_id="R-1", article="art-old", scope=SCOPE, pin=True):
    digest = hr.digest_of(row)
    db.execute("INSERT INTO evidence_history_versions VALUES (?,?,?,?,?,?,?,?)",
               (version_id, row["evidence_id"], row["case_id"], row["source_sha256"], hr.canonical(row), digest, "f" * 64, restore_id))
    if pin:
        db.execute("INSERT INTO article_history_pins VALUES (?,?,?,?,?,?,?,?)", (article, row["evidence_id"], version_id, row["case_id"], scope, row["source_sha256"], digest, restore_id))
    return digest


def build(tmp_path: Path, *, name="g3.sqlite", wal=False, append_only=True, loose=False, history=True, restored=True) -> Path:
    """One cycle; the CURRENT fact EV says 20 (source B, page 8); the old article `art-old` cited the OLD EV (16, source A, page 6) which exists only as a stored
    history version; `art-plain` is an ordinary article citing EV2."""
    path = tmp_path / name
    with closing(sqlite3.connect(path)) as db:
        if wal:
            db.execute("PRAGMA journal_mode=WAL")
        db.executescript(BASE_DDL)
        if history:
            db.executescript(LOOSE_HISTORY_DDL if loose else hr.history_ddl(append_only=append_only))
        for case in (CASE, OTHER_CASE):
            db.execute("INSERT INTO admission_cycles VALUES (?,?,?,?,?,?)", (case, CYCLE["university"], CYCLE["faculty"], CYCLE["department"],
                                                                              CYCLE["admission_method"] if case == CASE else "other method", 2027))
        for sha in (A, B, C):
            db.execute("INSERT INTO source_documents VALUES (?,?)", (sha, f"https://example.ac.jp/{sha[:4]}.pdf"))
        cur = record(locator="page 8", value={"quota": 20})
        db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?)", (EV, CASE, B, "quota", '{"quota":20}', json.dumps(cur, ensure_ascii=False, sort_keys=True)))
        db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?)", (EV2, CASE, B, "deadline", '{"d":"2027-01-01"}', json.dumps(record(locator="page 2", value={"d": "2027-01-01"}), sort_keys=True)))
        db.execute("INSERT INTO article_versions VALUES ('art-old', ?, 'old body')", (CASE,))
        db.execute("INSERT INTO article_versions VALUES ('art-plain', ?, 'plain body')", (CASE,))
        db.execute("INSERT INTO article_evidence VALUES ('art-old', ?)", (EV,))
        db.execute("INSERT INTO article_evidence VALUES ('art-plain', ?)", (EV2,))
        if history and restored:
            db.execute("INSERT INTO restore_events VALUES ('R-1','f2_recovery',?,?,'the user','2026-11-07','issue-55#approval')", ("1" * 64, "2" * 64))
            db.execute("INSERT INTO restored_articles VALUES ('art-old','R-1')")
            put_version(db, make_row())
        db.commit()
    return path


def sql(path: Path, statement: str, *args):
    with closing(sqlite3.connect(path)) as db:
        db.execute(statement, args)
        db.commit()


def rewrite(path: Path, evidence=EV, **changes):
    """Change the stored old row AND keep its digest consistent in the version and the pin: isolates one check at a time."""
    with closing(sqlite3.connect(path)) as db:
        row = json.loads(db.execute("SELECT row_json FROM evidence_history_versions WHERE evidence_id=?", (evidence,)).fetchone()[0])
        rec_changes = changes.pop("record", None)
        row.update(changes)
        if rec_changes is not None:
            rec = json.loads(row["record_json"])
            rec.update(rec_changes)
            row["record_json"] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        digest = hr.digest_of(row)
        db.execute("UPDATE evidence_history_versions SET row_json=?, row_digest=? WHERE evidence_id=?", (hr.canonical(row), digest, evidence))
        db.execute("UPDATE article_history_pins SET row_digest=? WHERE evidence_id=?", (digest, evidence))
        db.commit()


def read(path: Path, article="art-old", evidence=EV, **kw):
    with closing(sqlite3.connect(path)) as db:
        return hr.read_cited_evidence(db, article, evidence, **kw)


def refused(path: Path, code: str, article="art-old", evidence=EV, **kw):
    with pytest.raises(hr.ReadContractError) as e:
        read(path, article, evidence, **kw)
    assert e.value.code == code, str(e.value)
    return e.value


# ---- item 1: a normal (ordinary) article is read as before ----------------------------------------------------------------------------------
def test_item1_an_ordinary_article_is_read_as_the_row_its_relation_names_and_needs_no_restore_record(tmp_path):
    p = build(tmp_path, history=False)  # a database that has no history tables at all
    c = read(p, "art-plain", EV2)
    assert c.kind == "current_citation" and c.version_id is None and c.provenance is None and c.evidence_id == EV2 and c.case_id == CASE
    assert c.row["value_json"] == '{"d":"2027-01-01"}' and c.source_sha256 == B and c.row_digest == hr.digest_of(dict(c.row))
    with closing(sqlite3.connect(p)) as db:
        assert ad.cited_version(db, "art-plain", EV2)["cited_evidence_id"] == c.evidence_id  # the old function and the new reader name the same evidence


def test_item1_an_ordinary_citation_never_follows_a_head_even_after_the_evidence_was_revised(tmp_path):
    p = build(tmp_path)
    sql(p, "INSERT INTO evidence_revisions VALUES ('EV-2-rev','lg','fiction-case','deadline',?, 'EV-2', '{}')", B)
    sql(p, "INSERT INTO evidence_heads VALUES ('lg','EV-2-rev')")
    assert read(p, "art-plain", EV2).evidence_id == EV2


def test_item1_a_revised_article_is_found_through_its_base_article(tmp_path):
    p = build(tmp_path)
    sql(p, "INSERT INTO article_versions VALUES ('art-base', ?, 'b')", CASE)
    sql(p, "INSERT INTO revised_articles VALUES ('art-rev','art-base')")
    sql(p, "INSERT INTO revised_article_evidence VALUES ('art-rev', ?, ?)", EV2, CASE)
    c = read(p, "art-rev", EV2)
    assert c.kind == "current_citation" and c.article_id == "art-rev" and c.case_id == CASE


# ---- item 2: a formally restored old article is read at its fixed version -----------------------------------------------------------------
def test_item2_a_restored_article_returns_the_old_row_not_the_current_one_and_carries_its_provenance(tmp_path):
    p = build(tmp_path)
    c = read(p)
    assert c.kind == "restored_history" and c.version_id == "HV-1"
    assert c.row["value_json"] == '{"quota":16}' and c.source_sha256 == A and c.record()["locator"] == "page 6" and c.scope == SCOPE
    assert c.provenance["restore_id"] == "R-1" and c.provenance["approved_by"] == "the user" and c.provenance["approval_ref"] == "issue-55#approval"
    assert c.provenance["archive_sha256"] == "1" * 64 and c.provenance["archive_row_sha256"] == "f" * 64
    with closing(sqlite3.connect(p)) as db:
        current = db.execute("SELECT value_json, source_sha256 FROM facts WHERE evidence_id=?", (EV,)).fetchone()
    assert current == ('{"quota":20}', B) and (c.row["value_json"], c.source_sha256) != current


def test_item2_the_reader_writes_nothing_and_works_on_a_read_only_connection(tmp_path):
    p = build(tmp_path)
    with closing(sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        before = db.total_changes
        c = hr.read_cited_evidence(db, "art-old", EV)
        assert db.total_changes == before and not db.in_transaction and c.kind == "restored_history"


# ---- item 3: a missing old version or correspondence is refused; nothing falls back to the current row -------------------------------------
@pytest.mark.parametrize("breaker,code", [
    ("DELETE FROM evidence_history_versions", "history_version_missing"),
    ("DELETE FROM article_history_pins", "pin_missing"),
    ("DELETE FROM restore_events", "restore_unavailable"),
    ("INSERT INTO restore_revocations VALUES ('R-1','the user','2026-11-08','withdrawn')", "restore_unavailable"),
    ("DELETE FROM article_evidence WHERE article_id='art-old'", "citation_missing"),
], ids=["version-deleted", "pin-deleted", "event-deleted", "event-revoked", "citation-deleted"])
def test_item3_a_missing_part_of_a_restored_article_is_an_error_and_the_current_row_is_never_returned(tmp_path, breaker, code):
    p = build(tmp_path, append_only=False)  # triggers off: simulates a damaged file
    sql(p, breaker)
    refused(p, code)  # the current row of EV exists the whole time (value 20): it is not returned


def test_item3_a_restored_article_is_never_downgraded_when_its_registration_exists_but_the_history_tables_do_not(tmp_path):
    p = build(tmp_path, history=False)
    sql(p, "CREATE TABLE restored_articles(article_id TEXT PRIMARY KEY, restore_id TEXT NOT NULL)")
    sql(p, "INSERT INTO restored_articles VALUES ('art-old','R-1')")
    refused(p, "schema_unavailable")


def test_item3_history_pins_without_a_registration_are_not_read_as_an_ordinary_article(tmp_path):
    p = build(tmp_path, append_only=False)
    sql(p, "DELETE FROM restored_articles")
    refused(p, "registry_inconsistent")


@pytest.mark.parametrize("breaker,code", [
    ("INSERT INTO article_history_pins SELECT * FROM article_history_pins", "pin_duplicated"),
    ("INSERT INTO evidence_history_versions SELECT * FROM evidence_history_versions", "history_version_duplicated"),
    ("INSERT INTO restored_articles SELECT * FROM restored_articles", "registry_ambiguous"),
    ("INSERT INTO restore_events SELECT * FROM restore_events", "restore_unavailable"),
], ids=["pin", "version", "registration", "event"])
def test_item3_a_duplicated_pin_version_registration_or_event_is_an_error_never_a_choice(tmp_path, breaker, code):
    p = build(tmp_path, loose=True)
    sql(p, breaker)
    refused(p, code)


def test_item3_a_second_stored_version_of_the_same_evidence_in_the_same_restore_is_an_error_even_with_another_version_id(tmp_path):
    p = build(tmp_path, loose=True)  # no UNIQUE(restore_id, evidence_id) here: a damaged or hand-edited file
    with closing(sqlite3.connect(p)) as db:
        put_version(db, make_row(value='{"quota":17}'), version_id="HV-1b", pin=False)
        db.commit()
    refused(p, "history_version_duplicated")


def test_item3_a_citation_listed_twice_is_an_error(tmp_path):
    p = build(tmp_path)
    sql(p, "INSERT INTO revised_articles VALUES ('art-old','art-old')")
    sql(p, "INSERT INTO revised_article_evidence VALUES ('art-old', ?, ?)", EV, CASE)
    refused(p, "citation_duplicated")


def test_item3_an_unknown_article_cycle_or_a_blank_input_is_refused(tmp_path):
    p = build(tmp_path)
    refused(p, "article_unknown", article="nope")
    refused(p, "bad_input", article=" ")
    refused(p, "bad_input", evidence="")
    sql(p, "DELETE FROM admission_cycles WHERE case_id=?", CASE)
    refused(p, "cycle_unknown")


# ---- item 4: the same evidence id with a different value, body, source or version --------------------------------------------------------
def test_item4_a_changed_value_in_the_stored_row_is_caught_by_the_digest(tmp_path):
    p = build(tmp_path, append_only=False)
    with closing(sqlite3.connect(p)) as db:
        row = json.loads(db.execute("SELECT row_json FROM evidence_history_versions").fetchone()[0])
        row["value_json"] = '{"quota":17}'
        db.execute("UPDATE evidence_history_versions SET row_json=?", (hr.canonical(row),))  # the stored digest is left as it was
        db.commit()
    refused(p, "digest_mismatch")


@pytest.mark.parametrize("change", [{"record": {"locator": "page 7"}}, {"record": {"value": {"quota": 16, "note": "x"}}}, {"fact_key": "other_key"}])
def test_item4_a_row_that_differs_from_the_pinned_digest_in_a_locator_a_value_or_a_key_is_refused_even_with_the_same_source(tmp_path, change):
    p = build(tmp_path, append_only=False)
    with closing(sqlite3.connect(p)) as db:
        row = json.loads(db.execute("SELECT row_json FROM evidence_history_versions").fetchone()[0])
    new = dict(row)
    new.update({k: v for k, v in change.items() if k != "record"})
    if "record" in change:
        rec = json.loads(new["record_json"])
        rec.update(change["record"])
        new["record_json"] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    # a forger who rewrites the row and its own digest, but not the digest the PIN holds
    sql(p, "UPDATE evidence_history_versions SET row_json=?, row_digest=?", hr.canonical(new), hr.digest_of(new))
    refused(p, "digest_mismatch")


def test_item4_a_pin_that_points_to_a_version_of_another_evidence_id_is_refused(tmp_path):
    p = build(tmp_path, append_only=False)
    with closing(sqlite3.connect(p)) as db:
        other = make_row(evidence_id=EV_OTHER)
        d = put_version(db, other, version_id="HV-2", pin=False)
        db.execute("UPDATE article_history_pins SET version_id='HV-2', row_digest=?", (d,))
        db.commit()
    refused(p, "binding_mismatch")


def test_item4_the_source_must_be_the_same_in_the_row_the_version_and_the_pin_and_must_be_a_registered_source(tmp_path):
    p = build(tmp_path, append_only=False)
    sql(p, "UPDATE article_history_pins SET source_sha256=?", C)
    refused(p, "source_mismatch")
    p2 = build(tmp_path, name="g3b.sqlite", append_only=False)
    sql(p2, "DELETE FROM source_documents WHERE sha256=?", A)
    refused(p2, "source_unregistered")
    p3 = build(tmp_path, name="g3c.sqlite", append_only=False)
    rewrite(p3, record={"source_pdf_sha256": C})
    refused(p3, "source_mismatch")


def test_item4_a_pin_registered_under_another_restore_event_is_refused(tmp_path):
    p = build(tmp_path, append_only=False)
    sql(p, "UPDATE article_history_pins SET restore_id='R-2'")
    refused(p, "binding_mismatch")


@pytest.mark.parametrize("row_json", ["not json", "[]", json.dumps({"evidence_id": EV}), json.dumps({**make_row(), "extra": 1}), json.dumps({**make_row(), "case_id": 7})])
def test_item4_a_malformed_stored_row_is_refused(tmp_path, row_json):
    p = build(tmp_path, append_only=False)
    sql(p, "UPDATE evidence_history_versions SET row_json=?", row_json)
    refused(p, "row_malformed")


# ---- item 5: case / scope mismatches ------------------------------------------------------------------------------------------------------
def test_item5_a_case_that_differs_between_the_article_the_pin_the_version_or_the_record_is_refused(tmp_path):
    p = build(tmp_path, append_only=False)
    sql(p, "UPDATE article_versions SET case_id=? WHERE article_id='art-old'", OTHER_CASE)
    refused(p, "case_mismatch")
    p2 = build(tmp_path, name="b.sqlite", append_only=False)
    sql(p2, "UPDATE article_history_pins SET case_id=?", OTHER_CASE)
    refused(p2, "case_mismatch")
    p3 = build(tmp_path, name="c.sqlite", append_only=False)
    rewrite(p3, record={"case_id": OTHER_CASE})
    refused(p3, "case_mismatch")
    p4 = build(tmp_path, name="d.sqlite", append_only=False)
    sql(p4, "UPDATE evidence_history_versions SET case_id=?", OTHER_CASE)
    refused(p4, "case_mismatch")


def test_item5_an_ordinary_citation_of_another_cases_evidence_is_refused(tmp_path):
    p = build(tmp_path)
    sql(p, "UPDATE facts SET case_id=? WHERE evidence_id=?", OTHER_CASE, EV2)
    refused(p, "case_mismatch", article="art-plain", evidence=EV2)


@pytest.mark.parametrize("value", [None, "", "UNKNOWN", " unknown ", 7])
def test_item5_a_scope_that_is_missing_or_unknown_is_refused_never_inferred(tmp_path, value):
    p = build(tmp_path, append_only=False)
    rewrite(p, record={"scope": value})
    refused(p, "scope_unknown")


def test_item5_a_missing_scope_key_is_refused_too(tmp_path):
    p = build(tmp_path, append_only=False)
    with closing(sqlite3.connect(p)) as db:
        row = json.loads(db.execute("SELECT row_json FROM evidence_history_versions").fetchone()[0])
        rec = json.loads(row["record_json"])
        rec.pop("scope")
        row["record_json"] = json.dumps(rec)
        d = hr.digest_of(row)
        db.execute("UPDATE evidence_history_versions SET row_json=?, row_digest=?", (hr.canonical(row), d))
        db.execute("UPDATE article_history_pins SET row_digest=?", (d,))
        db.commit()
    refused(p, "scope_unknown")


def test_item5_a_scope_or_cycle_dimension_that_differs_from_the_pin_or_the_cycle_is_refused(tmp_path):
    p = build(tmp_path, append_only=False)
    sql(p, "UPDATE article_history_pins SET scope='target_admission_cycle'")
    refused(p, "scope_mismatch")
    for key, bad in (("fiscal_year", 2026), ("university", "another university"), ("admission_method", "another method"), ("faculty", "x"), ("department", "y")):
        q = build(tmp_path, name=f"{key}.sqlite", append_only=False)
        rewrite(q, record={key: bad})
        refused(q, "scope_mismatch")


# ---- the consumer's own record (expect) ----------------------------------------------------------------------------------------------------
def test_expect_accepts_a_consumer_record_that_matches_and_refuses_each_difference(tmp_path):
    p = build(tmp_path)
    c = read(p)
    good = {"case_id": CASE, "scope": SCOPE, "source_sha256": A, "row_digest": c.row_digest, "record_subset": {"locator": "page 6"}}
    assert read(p, expect=good).row_digest == c.row_digest
    for k, bad in (("case_id", OTHER_CASE), ("scope", "target_admission_cycle"), ("source_sha256", B), ("row_digest", "0" * 64), ("record_subset", {"locator": "page 8"})):
        refused(p, "expectation_mismatch", expect={**good, k: bad})
    refused(p, "bad_input", expect={"nonsense": 1})


def test_the_four_cases_work_found_that_the_active_view_export_lets_through_are_all_refused_by_the_contract_reader(tmp_path):
    """Work's probe (bcea29d): a different locator on the same source, a different case, a different scope, and a citation that is not in the article's relation."""
    p = build(tmp_path, history=False)
    ok = {"case_id": CASE, "scope": SCOPE, "source_sha256": B, "record_subset": {"locator": "page 2"}}
    assert read(p, "art-plain", EV2, expect=ok).evidence_id == EV2
    refused(p, "expectation_mismatch", article="art-plain", evidence=EV2, expect={**ok, "record_subset": {"locator": "page 8"}})  # same source, other locator
    refused(p, "expectation_mismatch", article="art-plain", evidence=EV2, expect={**ok, "case_id": "fiction-other"})
    refused(p, "expectation_mismatch", article="art-plain", evidence=EV2, expect={**ok, "scope": "target_admission_cycle"})
    refused(p, "citation_missing", article="art-plain", evidence=EV)  # EV exists, but art-plain does not cite it
    refused(p, "citation_missing", article="art-plain", evidence="fiction-unlinked")


# ---- routing: the old function and the flags ------------------------------------------------------------------------------------------------
def test_the_old_cited_version_refuses_a_restored_article_and_is_unchanged_for_an_ordinary_one(tmp_path):
    p = build(tmp_path)
    with closing(sqlite3.connect(p)) as db:
        with pytest.raises(ad.AliasError, match="restored article"):
            ad.cited_version(db, "art-old", EV)
        assert ad.cited_version(db, "art-plain", EV2) == {"article_id": "art-plain", "article_kind": "base", "cited_evidence_id": EV2, "root": EV2, "follows_head": False}


def test_require_restored_states_the_route_and_a_wrong_belief_is_refused(tmp_path):
    p = build(tmp_path)
    assert read(p, require_restored=True).kind == "restored_history"
    refused(p, "restored_article_on_ordinary_route", require_restored=False)
    assert read(p, "art-plain", EV2, require_restored=False).kind == "current_citation"
    refused(p, "not_restored", article="art-plain", evidence=EV2, require_restored=True)


def test_an_evidence_id_used_by_both_current_tables_is_ambiguous_not_a_choice(tmp_path):
    p = build(tmp_path)
    sql(p, "INSERT INTO evidence_revisions VALUES (?,?,?,?,?,NULL,'{}')", EV2, "lg", CASE, "deadline", B)
    refused(p, "evidence_ambiguous", article="art-plain", evidence=EV2)
    p2 = build(tmp_path, name="m.sqlite")
    sql(p2, "DELETE FROM facts WHERE evidence_id=?", EV2)
    refused(p2, "current_evidence_missing", article="art-plain", evidence=EV2)


# ---- item 6: one consistent snapshot while the database changes during the read ------------------------------------------------------------
class Hooked(sqlite3.Connection):
    fire_at = 0
    hook = None
    calls = 0

    after = ""

    def execute(self, *a):
        result = super().execute(*a)
        self.calls += 1
        if self.hook is not None and self.calls == self.fire_at:
            hook, self.hook = self.hook, None
            self.after = str(a[0])
            hook()
        return result


def damage(path: Path):
    """Everything another connection could do mid-read: revoke the restore, delete the pin and the version, change the current fact, move a head."""
    with closing(sqlite3.connect(path, timeout=0)) as other:
        other.execute("INSERT INTO restore_revocations VALUES ('R-1','x','2026-11-08','y')")
        other.execute("DELETE FROM article_history_pins")
        other.execute("DELETE FROM evidence_history_versions")
        other.execute("UPDATE facts SET value_json='{\"quota\":99}', source_sha256=?", (C,))
        other.execute("INSERT INTO evidence_revisions VALUES ('EV-1-rev','lg',?,?,?,?, '{}')", (CASE, "quota", C, EV))
        other.execute("INSERT OR REPLACE INTO evidence_heads VALUES ('lg','EV-1-rev')")
        other.commit()


@pytest.mark.parametrize("mode", ["wal", "delete"])
def test_item6_a_change_at_any_point_of_the_read_never_mixes_the_before_and_the_after(tmp_path, mode):
    baseline = read(build(tmp_path, name=f"base-{mode}.sqlite", append_only=False, wal=(mode == "wal")))
    compared = 0
    for at in range(2, 24):
        p = build(tmp_path, name=f"{mode}-{at}.sqlite", append_only=False, wal=(mode == "wal"))
        outcome = {}

        def attack(path=p):
            try:
                damage(path)
                outcome["wrote"] = True
            except sqlite3.OperationalError as exc:
                outcome["wrote"] = False
                outcome["why"] = str(exc)

        with closing(sqlite3.connect(p, factory=Hooked)) as db:
            db.fire_at, db.hook = at, attack
            try:
                got = hr.read_cited_evidence(db, "art-old", EV)
            except hr.ReadContractError:
                got = None
            fired = db.hook is None
            db_after = db.after
            assert not db.in_transaction
        if not fired:  # the read finished before call number `at`: nothing to compare
            continue
        # the reader's snapshot began with its first read; a change after it is invisible to it (WAL) or is held off (rollback journal)
        assert got is not None and got.to_export() == baseline.to_export(), f"mixed or changed result when the database changed after statement {at} ({mode}): {outcome}"
        if db_after.startswith("ROLLBACK"):
            continue  # fired after the snapshot ended: the result was complete before the change
        compared += 1
        if mode == "delete":
            assert outcome["wrote"] is False and "locked" in outcome["why"]  # held off, not merely unnoticed
        else:
            assert outcome["wrote"] is True
    assert compared >= 12, "the change was injected at too few points of the read for this test to mean anything"


def test_item6_a_snapshot_taken_before_the_damage_is_still_a_valid_read_and_a_new_read_after_it_is_refused(tmp_path):
    p = build(tmp_path, append_only=False, wal=True)
    first = read(p)
    damage(p)
    refused(p, "restore_unavailable")  # the revocation is seen by every NEW read
    assert first.kind == "restored_history"


def test_item6_the_reader_leaves_the_callers_transaction_alone(tmp_path):
    p = build(tmp_path)
    with closing(sqlite3.connect(p)) as db:
        db.execute("BEGIN")
        c = hr.read_cited_evidence(db, "art-old", EV)
        assert db.in_transaction and c.kind == "restored_history"
        db.execute("ROLLBACK")
        hr.read_cited_evidence(db, "art-old", EV)
        assert not db.in_transaction
        with pytest.raises(hr.ReadContractError):
            hr.read_cited_evidence(db, "art-old", "nothing")
        assert not db.in_transaction  # a refusal leaves no transaction open


# ---- item 7: version, source and provenance reach display / export, and cannot be swapped on the way ----------------------------------------
def render(c: dict) -> str:
    """A stand-in for a display / export step: it uses ONLY the exported citation it is given."""
    hr.verify_export(c)
    prov = c["provenance"]
    return f"{c['evidence_id']} v={c['version_id']} src={c['source_sha256'][:8]} scope={c['scope']} value={json.loads(c['row']['value_json'])['quota']}" + (f" restore={prov['restore_id']}" if prov else "")


def test_item7_display_shows_the_old_value_version_source_and_restore_event(tmp_path):
    p = build(tmp_path)
    text = render(read(p).to_export())
    assert text == f"EV-1 v=HV-1 src=aaaaaaaa scope={SCOPE} value=16 restore=R-1"


def test_item7_display_and_export_pass_with_every_read_of_evidence_tables_forbidden_and_a_second_lookup_is_denied_by_sqlite(tmp_path):
    p = build(tmp_path)
    with closing(sqlite3.connect(p)) as db:
        exported = hr.read_cited_evidence(db, "art-old", EV).to_export()
        with hr.forbid_current_evidence_reads(db):
            assert "value=16" in render(exported)  # uses the bound payload only
            for lookup in ("SELECT * FROM facts WHERE evidence_id='EV-1'", "SELECT * FROM evidence_heads",
                           "SELECT * FROM article_history_pins", "SELECT * FROM article_evidence", "SELECT * FROM evidence_history_versions"):
                with pytest.raises(sqlite3.DatabaseError):
                    db.execute(lookup).fetchall()
        assert db.execute("SELECT count(*) FROM facts").fetchone()[0] == 2  # the tool is off again outside the block


def test_item7_a_consumer_that_looks_the_current_evidence_up_again_is_caught_by_the_same_tool(tmp_path):
    p = build(tmp_path)

    def wrong_display(db, c):
        return db.execute("SELECT value_json FROM facts WHERE evidence_id=?", (c.evidence_id,)).fetchone()[0]  # re-fetch by id: shows 20, not 16

    with closing(sqlite3.connect(p)) as db:
        c = hr.read_cited_evidence(db, "art-old", EV)
        assert wrong_display(db, c) == '{"quota":20}'  # without the tool the mistake is silent
        with hr.forbid_current_evidence_reads(db), pytest.raises(sqlite3.DatabaseError):
            wrong_display(db, c)


@pytest.mark.parametrize("tamper", [
    lambda d: d["row"].update(value_json='{"quota":20}'),
    lambda d: d.update(source_sha256=B),
    lambda d: d.update(version_id="HV-9"),
    lambda d: d.update(version_id=None),
    lambda d: d["provenance"].update(approved_by="someone else"),
    lambda d: d.update(provenance=None),
    lambda d: d.update(scope="target_admission_cycle"),
    lambda d: d.update(case_id=OTHER_CASE),
    lambda d: d.update(kind="current_citation"),
    lambda d: d.update(evidence_id="EV-2"),
    lambda d: d.update(row_digest="0" * 64),
    lambda d: d.update(extra="x"),
    lambda d: d.pop("bound_digest"),
    lambda d: d.update(row="not a row"),
], ids=["value", "source", "version", "no-version", "approver", "no-provenance", "scope", "case", "kind", "evidence", "digest", "extra-field", "no-bound-digest", "row-type"])
def test_item7_an_exported_citation_changed_after_the_read_is_refused(tmp_path, tamper):
    d = copy.deepcopy(read(build(tmp_path)).to_export())
    assert hr.verify_export(d) is d
    tamper(d)
    with pytest.raises(hr.ReadContractError) as e:
        hr.verify_export(d)
    assert e.value.code == "export_tampered"


def test_item7_an_ordinary_citation_exports_without_a_restored_version_and_cannot_claim_one(tmp_path):
    d = read(build(tmp_path), "art-plain", EV2).to_export()
    assert hr.verify_export(d)["kind"] == "current_citation" and d["version_id"] is None and d["provenance"] is None
    d2 = copy.deepcopy(d)
    d2["version_id"] = "HV-1"
    with pytest.raises(hr.ReadContractError):
        hr.verify_export(d2)


# ---- the proposed storage is append-only --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("table", hr.APPEND_ONLY_TABLES)
def test_the_proposed_history_tables_refuse_update_and_delete(tmp_path, table):
    p = build(tmp_path)
    if table == "restore_revocations":
        sql(p, "INSERT INTO restore_revocations VALUES ('R-1','x','2026-11-08','y')")
    with closing(sqlite3.connect(p)) as db:
        col = db.execute(f"SELECT name FROM pragma_table_info('{table}') LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute(f"UPDATE {table} SET {col}={col}")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute(f"DELETE FROM {table}")
