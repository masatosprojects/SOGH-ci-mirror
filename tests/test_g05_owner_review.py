"""G-05 owner review (2026-11-07, Claude as contract owner): the code layer of alias registration (`additive_schema.register_alias`) after the review of Work's two questions in Issue #55
(the proof boundary of an ordinary registration vs the "01" registration that is bound to one approved version; and a head that moves between the check and the write).
See docs/G05_OWNER_REVIEW_2026-11-07.md. SYNTHETIC_ONLY: disposable synthetic databases in a temporary directory; no real rows, no real database. This is Claude's own contract and its tests (SELF_VALIDATED);
it is NOT the G-05 registration path of Work's product, not an acceptance of the 01 registration and not the M1.g1 acceptance: M1 stays 2/8, NOT ACCEPTED."""
import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from src.db_contract import additive_schema as ad
from src.db_contract import identity
from tests import db_support as dbs
from tests import test_additive_schema as T

CORRECTED = [{"page": 6, "quote": "訂正後の位置にある同じ文"}]
SECOND = [{"page": 6, "quote": "二度目の訂正後の位置"}]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, skip=()):
    with closing(dbs.app_connect(path)) as c:
        out = {}
        for (name,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall():
            if name not in skip:
                out[name] = c.execute(f'select * from "{name}" order by rowid').fetchall()
        return out


@pytest.fixture
def world(tmp_path):
    path = T.build(tmp_path)
    root = T.facts(path)[0]["evidence_id"]
    ad.apply(path, confirm_disposable_copy=True)
    return path, root


def fact_and_record(path, root):
    f = next(x for x in T.facts(path) if x["evidence_id"] == root)
    with closing(dbs.app_connect(path)) as c:
        cyc = c.execute("select university,faculty,department,admission_method,fiscal_year from admission_cycles where case_id=?", (f["case_id"],)).fetchone()
    rec = json.loads(f["record_json"])
    base = copy.deepcopy(rec)
    base.update(fact_key=f["fact_key"], university=cyc[0], faculty=cyc[1], department=cyc[2], admission_method=cyc[3], fiscal_year=cyc[4], value=json.loads(f["value_json"]))
    return f, rec, base


def add_revision(path, root, head_id, proofs, parent=None, logical="quota-root", make_head=True):
    """A revision of the native fact with the given locator; approved in its own batch; optionally the head (inserted directly: synthetic)."""
    f, rec, _ = fact_and_record(path, root)
    r = copy.deepcopy(rec)
    r.update(evidence_id=head_id, logical_id=logical, parent_evidence_id=parent or root, proofs=proofs)
    with closing(dbs.app_connect(path)) as c:
        c.execute("insert into evidence_revisions values(?,?,?,?,?,?,?)", (head_id, logical, f["case_id"], f["fact_key"], f["source_sha256"], parent or root, dbs.canonical(r)))
        c.execute("insert into update_batches values(?,?,?,?,?,?,?,?)", ("b-" + head_id, (head_id.encode().hex() + "0" * 64)[:64], "approved", T.NOW, "{}", "{}", ("r" * 64), "{}"))
        c.execute("insert into batch_evidence values(?,?)", ("b-" + head_id, head_id))
        if make_head:
            c.execute("insert into evidence_heads values(?,?)", (logical, head_id))
        c.commit()


def move_head(path, new_id, logical="quota-root"):
    """Another connection commits a legitimate new head for the same logical id."""
    with closing(dbs.app_connect(path)) as c:
        c.create_function("sogh_write_ok", 0, lambda: 1)
        c.execute("update evidence_heads set evidence_id=? where logical_id=?", (new_id, logical))
        c.commit()


def register(path, alias_id, root, record, kind="legacy_compat_id", **kw):
    with closing(dbs.app_connect(path)) as c:
        ad.register_alias(c, alias_id, root, kind, "owner review test", alias_record=record, **kw)
        c.commit()


def aliases(path):
    with closing(dbs.app_connect(path)) as c:
        return c.execute("select alias_id, pinned_evidence_id from evidence_aliases order by alias_id").fetchall()


def legacy_with(base, proofs):
    r = copy.deepcopy(base)
    r["proofs"] = copy.deepcopy(proofs)
    return r


# ------------------------------------------------------------------ 1. ordinary registration: what it must prove
def test_an_explicit_case_id_that_is_not_the_roots_is_refused_and_the_roots_own_is_accepted(world):
    path, root = world
    f, _, base = fact_and_record(path, root)
    before = sha(path)
    for wrong in ("another-case", "", None, 7):
        with pytest.raises(ad.AliasError, match="case"):
            register(path, "EV-A-" + str(wrong), root, {**base, "case_id": wrong})
    assert aliases(path) == [] and sha(path) == before  # nothing written, not a byte changed
    register(path, "EV-A-ok", root, {**base, "case_id": f["case_id"]})
    assert [a for a, _ in aliases(path)] == ["EV-A-ok"]
    register(path, "EV-A-omitted", root, base)  # omitting it is allowed: the case is derived from the root, never from the record
    assert len(aliases(path)) == 2


@pytest.mark.parametrize("bad", ["__missing__", None, [], {}, "x", [{}], [5], ["page 6"], [None]])
def test_a_record_without_a_stated_locator_is_refused(world, bad):
    path, root = world
    _, _, base = fact_and_record(path, root)
    record = copy.deepcopy(base)
    if bad == "__missing__":
        record.pop("proofs")
    else:
        record["proofs"] = bad
    before = sha(path)
    with pytest.raises(ad.AliasError, match="locator"):
        register(path, "EV-NOLOC", root, record)
    assert aliases(path) == [] and sha(path) == before


def test_field_proofs_alone_are_not_a_locator_and_valid_field_proofs_beside_proofs_are_accepted(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    only_field = {k: v for k, v in base.items() if k != "proofs"}
    only_field["field_proofs"] = {"value": {"proof_indices": [0]}}
    with pytest.raises(ad.AliasError, match="locator"):
        register(path, "EV-FIELD-ONLY", root, only_field)  # Work's review of PR #191 (item 6): the locator is `proofs`; field proofs only point into it
    register(path, "EV-FIELD-OK", root, {**base, "field_proofs": {"value": {"proof_indices": [0], "actor": "x"}}})
    for bad_fp in ({}, [], "x", {"value": "not an object"}, {"value": {"proof_indices": [5]}}, {"value": {"proof_indices": ["0"]}}, {"value": {"proof_indices": True}}):
        with pytest.raises(ad.AliasError, match="locator"):
            register(path, "EV-FIELD-BAD", root, {**base, "field_proofs": bad_fp})


@pytest.mark.parametrize("proofs", [
    [{"x": 1}], [{"page": 6}], [{"quote": "q"}], [{"page": 0, "quote": "q"}], [{"page": -1, "quote": "q"}], [{"page": "6", "quote": "q"}], [{"page": True, "quote": "q"}],
    [{"page": 6.0, "quote": "q"}], [{"page": 6, "quote": ""}], [{"page": 6, "quote": "   "}], [{"page": 6, "quote": 5}], [{"page": 6, "quote": "q"}, {"x": 1}], {"page": 6, "quote": "q"},
], ids=lambda x: str(x)[:38])
def test_an_arbitrary_proofs_object_is_not_a_locator_a_page_and_a_quote_are_required(world, proofs):
    path, root = world
    _, _, base = fact_and_record(path, root)
    before = sha(path)
    with pytest.raises(ad.AliasError, match="locator"):
        register(path, "EV-SHAPE", root, {**base, "proofs": proofs})
    assert aliases(path) == [] and sha(path) == before


@pytest.mark.parametrize("key,bad", [("university", "__missing__"), ("university", None), ("faculty", ""), ("admission_method", None), ("fiscal_year", "2027"), ("fiscal_year", True), ("fiscal_year", 2028), ("fact_key", "__missing__"), ("value", "__missing__")])
def test_a_missing_blank_or_mistyped_scope_value_or_fact_key_is_refused(world, key, bad):
    path, root = world
    _, _, base = fact_and_record(path, root)
    record = copy.deepcopy(base)
    if bad == "__missing__":
        record.pop(key)
    else:
        record[key] = bad
    before = sha(path)
    with pytest.raises(ad.AliasError):
        register(path, "EV-SCOPE", root, record)
    assert aliases(path) == [] and sha(path) == before


def test_for_a_cycle_whose_department_is_unspecified_the_record_may_state_null_or_omit_it_but_never_invent_one(world):
    """G-04 = A (user decision 2026-11-05): an empty department is accepted as 'not stated in the source'. The synthetic cycle here has department NULL."""
    path, root = world
    _, _, base = fact_and_record(path, root)
    assert base["department"] is None
    register(path, "EV-D-null", root, {**base, "department": None})
    omitted = {k: v for k, v in base.items() if k != "department"}
    register(path, "EV-D-omitted", root, omitted)
    for invented in ("", "ある学科"):
        with pytest.raises(ad.AliasError):
            register(path, "EV-D-x", root, {**base, "department": invented})


@pytest.mark.parametrize("change,expected_error", [({"value": {"different": 1}}, "classified"), ({"source_sha256": "9" * 64}, "source"), ({"fiscal_year": 2099}, "cycle"), ({"faculty": "別の学部"}, "cycle"), ({"fact_key": "online_period"}, "fact_key")])
def test_independent_or_foreign_facts_are_still_refused_with_no_effect(world, change, expected_error):
    path, root = world
    _, _, base = fact_and_record(path, root)
    record = {**copy.deepcopy(base), **change}
    record.pop("source_pdf_sha256", None)
    before = sha(path)
    with pytest.raises(ad.AliasError):
        register(path, "EV-IND", root, record)
    assert aliases(path) == [] and sha(path) == before


# ------------------------------------------------------------------ 2. an ordinary alias follows the head; ambiguity is an error, never a guess
def test_a_root_with_two_heads_refuses_a_new_ordinary_alias_at_registration_and_an_older_alias_fails_at_resolution_but_a_pinned_one_resolves(world):
    path, root = world
    T.revise(path, root, head_id="EV-U-a", logical="L-a")
    _, _, base = fact_and_record(path, root)
    register(path, "EV-FOLLOWS", root, base)  # one head: fine
    register(path, "EV-PINNED", root, base, pinned_evidence_id="EV-U-a", approved_head_id="EV-U-a")
    T.revise(path, root, head_id="EV-U-b", logical="L-b")  # now the root has two heads
    before = sha(path)
    with pytest.raises(ad.AliasError, match="heads"):
        register(path, "EV-NEW", root, base)  # Work's review (item 9): ambiguity is refused at registration, not first at resolution
    assert sha(path) == before and "EV-NEW" not in [a for a, _ in aliases(path)]
    with closing(dbs.app_connect(path)) as c:
        with pytest.raises(ad.AliasError, match="ambiguous head|heads"):
            ad.resolve(c, "EV-FOLLOWS")
        with pytest.raises(ad.AliasError, match="heads"):
            ad.current_head_of(c, root)
        assert ad.resolve(c, "EV-PINNED")["resolved_evidence_id"] == "EV-U-a" and ad.resolve(c, "EV-PINNED")["cited_version_fixed"] is True


# ------------------------------------------------------------------ 2b. a pin needs the approved registration (Work's review of PR #191, item 2)
def test_a_pinned_version_without_an_approved_head_is_refused_before_anything_is_written(world):
    path, root = world
    T.revise(path, root, head_id="EV-U-a", logical="L-a")
    _, _, base = fact_and_record(path, root)
    before = sha(path)
    for pin in ("EV-U-a", root, "EV-U-nope"):
        with pytest.raises(ad.AliasError, match="approved registration"):
            register(path, "EV-SNEAK", root, base, pinned_evidence_id=pin)
    assert aliases(path) == [] and sha(path) == before
    register(path, "EV-OK", root, base, pinned_evidence_id="EV-U-a", approved_head_id="EV-U-a")  # the approved registration is the one way to pin
    assert aliases(path) == [("EV-OK", "EV-U-a")]


# ------------------------------------------------------------------ 2c. the scope LABEL is not the five cycle dimensions (Work's review, item 10)
@pytest.fixture
def labelled_world(tmp_path):
    path = T.build(tmp_path)
    root = T.facts(path)[0]["evidence_id"]
    with closing(sqlite3.connect(path)) as c:
        rec = json.loads(c.execute("select record_json from facts where evidence_id=?", (root,)).fetchone()[0])
        rec["scope"] = "department_and_method"
        c.execute("update facts set record_json=? where evidence_id=?", (dbs.canonical(rec), root))
        c.commit()
    ad.apply(path, confirm_disposable_copy=True)
    return path, root


@pytest.mark.parametrize("label", [None, "", "  ", "UNKNOWN", "unknown", 7, ["department_and_method"], "target_admission_cycle"])
def test_a_scope_label_that_is_null_empty_unknown_or_not_the_roots_is_refused(labelled_world, label):
    path, root = labelled_world
    _, _, base = fact_and_record(path, root)
    before = sha(path)
    with pytest.raises(ad.AliasError, match="scope"):
        register(path, "EV-LABEL", root, {**base, "scope": label})
    assert aliases(path) == [] and sha(path) == before


def test_a_missing_scope_label_is_not_read_as_the_roots_and_the_roots_own_label_is_accepted(labelled_world):
    path, root = labelled_world
    _, _, base = fact_and_record(path, root)
    assert base["scope"] == "department_and_method"
    no_label = {k: v for k, v in base.items() if k != "scope"}
    with pytest.raises(ad.AliasError, match="scope label"):
        register(path, "EV-NOLABEL", root, no_label)
    register(path, "EV-LABEL-OK", root, base)
    assert [a for a, _ in aliases(path)] == ["EV-LABEL-OK"]


def test_when_the_root_states_no_scope_label_an_alias_may_not_invent_one(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    assert "scope" not in base
    register(path, "EV-NONE", root, base)  # neither states one: accepted (G-04 and the five cycle dimensions are unchanged)
    with pytest.raises(ad.AliasError, match="scope"):
        register(path, "EV-INVENTED", root, {**base, "scope": "department_and_method"})




# ------------------------------------------------------------------ 3. the "01" case: a legacy record that only the CURRENT HEAD carries
def prepare_01(path, root):
    """The root has the old locator; the current head carries the corrected one; the legacy record states the corrected one."""
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", CORRECTED)
    return legacy_with(base, CORRECTED), base


def test_the_01_record_is_a_moved_locator_against_the_root_and_a_duplicate_of_the_head(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    f = T.facts(path)[0]
    assert identity.classify(legacy, base) == "same_value_moved"
    head_record = {**json.loads(next(r for r in _revisions(path))[1]), "fact_key": base["fact_key"], **{k: base[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}}
    assert identity.classify(legacy, head_record) == "duplicate" and f["evidence_id"] == root


def _revisions(path):
    with closing(dbs.app_connect(path)) as c:
        return c.execute("select evidence_id, record_json from evidence_revisions order by evidence_id").fetchall()


def test_an_approved_registration_pins_exactly_the_approved_head_and_keeps_it_when_the_head_later_moves(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    add_revision(path, root, "EV-U-head2", SECOND, parent="EV-U-head", make_head=False)
    register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    register(path, "EV-LEGACY-02", root, base)  # an ordinary alias of the same root, registered in the ordinary way
    move_head(path, "EV-U-head2")  # a later, legitimate head change
    with closing(dbs.app_connect(path)) as c:
        r1, r2 = ad.resolve(c, "EV-LEGACY-01"), ad.resolve(c, "EV-LEGACY-02")
    assert r1["resolved_evidence_id"] == "EV-U-head" and r1["cited_version_fixed"] is True and r1["resolution"] == "pinned_version"  # the approved version, even though the head moved on
    assert r2["resolved_evidence_id"] == "EV-U-head2" and r2["cited_version_fixed"] is False  # the existing contract: no pin, follows the head


def test_an_approval_given_for_an_older_head_is_not_reused_after_the_head_moved(world):
    path, root = world
    legacy, _ = prepare_01(path, root)
    add_revision(path, root, "EV-U-head2", SECOND, parent="EV-U-head", make_head=False)
    move_head(path, "EV-U-head2")  # B committed before A started
    before = sha(path)
    with pytest.raises(ad.AliasError, match="head changed since the approval"):
        register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == [] and sha(path) == before
    # a fresh review of the NEW head: the legacy record does not carry its locator, so it is refused for that version too
    with pytest.raises(ad.AliasError, match="exactly this record"):
        register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head2", approved_head_id="EV-U-head2")
    assert aliases(path) == []


def test_a_head_that_moves_between_the_check_and_the_write_is_caught_by_the_write_itself_and_nothing_is_registered(world):
    """THE two-connection test (the hole measured at master 88c2fed: an alias was registered although another connection had committed a different head in between). Connection B commits the move from inside the
    second `identity.classify` call, i.e. after A has read the head and compared the record, and before A's insert."""
    path, root = world
    legacy, _ = prepare_01(path, root)
    add_revision(path, root, "EV-U-head2", SECOND, parent="EV-U-head", make_head=False)
    real = identity.classify
    calls = []

    def classify_then_b_moves_the_head(a, b):
        out = real(a, b)
        calls.append(out)
        if len(calls) == 2:  # the comparison with the head: A has read the head already
            move_head(path, "EV-U-head2")
        return out

    with patch.object(identity, "classify", classify_then_b_moves_the_head):
        with pytest.raises(ad.AliasError, match="between the check and the write"):
            register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert len(calls) == 2 and aliases(path) == []  # B's committed head stands, A wrote nothing
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select evidence_id from evidence_heads").fetchall() == [("EV-U-head2",)]


def test_a_control_with_an_unmoved_head_succeeds(world):
    path, root = world
    legacy, _ = prepare_01(path, root)
    register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == [("EV-LEGACY-01", "EV-U-head")]


def test_a_second_head_that_appears_between_the_check_and_the_write_is_caught(tmp_path):
    path = T.build(tmp_path, "race.sqlite")
    root = T.facts(path)[0]["evidence_id"]
    ad.apply(path, confirm_disposable_copy=True)
    legacy, _ = prepare_01(path, root)
    add_revision(path, root, "EV-U-other", SECOND, logical="L-other", make_head=False)
    real = identity.classify
    calls = []

    def classify_then_b_adds_a_head(a, b):
        out = real(a, b)
        calls.append(out)
        if len(calls) == 2:
            with closing(dbs.app_connect(path)) as c:
                c.execute("insert into evidence_heads values(?,?)", ("L-other", "EV-U-other"))
                c.commit()
        return out

    with patch.object(identity, "classify", classify_then_b_adds_a_head):
        with pytest.raises(ad.AliasError, match="between the check and the write"):
            register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == []


def test_an_approved_registration_refuses_a_pin_to_another_version_a_record_the_version_does_not_carry_and_a_root_without_revision(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    add_revision(path, root, "EV-U-old", [{"page": 5, "quote": "古い改訂"}], make_head=False)
    before = sha(path)
    with pytest.raises(ad.AliasError, match="exactly the approved version"):
        register(path, "EV-X1", root, legacy, pinned_evidence_id="EV-U-old", approved_head_id="EV-U-head")  # pinned to a revision that is not the approved head
    with pytest.raises(ad.AliasError, match="exactly the approved version"):
        register(path, "EV-X2", root, legacy, pinned_evidence_id=None, approved_head_id="EV-U-head")
    with pytest.raises(ad.AliasError, match="exactly this record"):
        register(path, "EV-X3", root, base, pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")  # the record states the OLD locator: the head does not carry it
    with pytest.raises(ad.AliasError, match="classified as"):  # a record with another value is not the same fact at all: refused by the ordinary identity check before the approved version is even compared
        register(path, "EV-X4", root, {**legacy, "value": {"different": 3}}, pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == [] and sha(path) == before


def test_an_approved_registration_for_a_root_that_was_never_revised_is_refused(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    with pytest.raises(ad.AliasError, match="no revision"):
        register(path, "EV-NOREV", root, base, pinned_evidence_id=root, approved_head_id=root)


# ------------------------------------------------------------------ 4. no spill: the exception is per alias, never per root, case, kind or cycle
def test_the_approved_registration_does_not_make_any_other_alias_pinned_or_change_another_roots_resolution(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    f = T.facts(path)[0]
    with closing(dbs.app_connect(path)) as c:  # a second root in the same case (another fact_key) with its own revision
        c.execute("insert into facts(evidence_id,case_id,source_sha256,fact_key,value_json,record_json,verification) values(?,?,?,?,?,?,?)",
                  ("EV-case-2", f["case_id"], f["source_sha256"], "other_key", f["value_json"], json.dumps({**json.loads(f["record_json"]), "fact_key": "other_key"}), f["verification"]))
        c.commit()
    T.revise(path, "EV-case-2", head_id="EV-U-case2", logical="case2-root")
    other = {**base, "fact_key": "other_key"}
    register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    register(path, "EV-LEGACY-02", "EV-case-2", other)  # the second root, same case: ordinary
    register(path, "EV-LEGACY-03", root, base, kind="locator_corrected_copy")  # the SAME kind as the 01 alias, same root, but not approved: not pinned
    rows = dict(aliases(path))
    assert rows == {"EV-LEGACY-01": "EV-U-head", "EV-LEGACY-02": None, "EV-LEGACY-03": None}
    with closing(dbs.app_connect(path)) as c:
        assert ad.resolve(c, "EV-LEGACY-02")["resolved_evidence_id"] == "EV-U-case2" and ad.resolve(c, "EV-LEGACY-03")["resolved_evidence_id"] == "EV-U-head"
        assert ad.resolve(c, "EV-LEGACY-03")["cited_version_fixed"] is False
    with pytest.raises(sqlite3.DatabaseError):  # the database itself refuses to pin an alias of one root to another root's revision
        with closing(dbs.app_connect(path)) as c:
            c.create_function("sogh_write_ok", 0, lambda: 1)
            c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,pinned_evidence_id,kind,reason,created_at) values(?,?,?,?,?,?,?,?)",
                      ("EV-CROSS", "EV-case-2", f["case_id"], "other_key", "EV-U-head", "legacy_compat_id", "x", T.NOW))


# ------------------------------------------------------------------ 5. what registration must never touch
def test_registering_aliases_changes_no_other_table_and_an_alias_row_once_written_never_changes(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    before = dump(path, skip=("evidence_aliases",))
    register(path, "EV-LEGACY-02", root, base)
    first = aliases(path)
    register(path, "EV-LEGACY-01", root, legacy, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert dump(path, skip=("evidence_aliases",)) == before  # facts, revisions, heads, articles, citations, history: row for row the same
    assert set(first) <= set(aliases(path))
    for stmt in ("update evidence_aliases set reason='x'", "delete from evidence_aliases"):
        with pytest.raises(sqlite3.DatabaseError):
            with closing(dbs.app_connect(path)) as c:
                c.create_function("sogh_write_ok", 0, lambda: 1)
                c.execute(stmt)
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select count(*) from evidence_aliases").fetchone()[0] == 2


def test_a_refused_registration_never_leaves_a_transaction_or_a_partial_row(world):
    path, root = world
    legacy, base = prepare_01(path, root)
    with closing(dbs.app_connect(path)) as c:
        with pytest.raises(ad.AliasError):
            ad.register_alias(c, "EV-X", root, "legacy_compat_id", "x", alias_record={**base, "case_id": "nope"})
        assert c.in_transaction is False and c.execute("select count(*) from evidence_aliases").fetchone()[0] == 0
        with pytest.raises(ad.AliasError):
            ad.register_alias(c, "EV-Y", root, "legacy_compat_id", "x", alias_record=legacy, pinned_evidence_id="EV-U-head", approved_head_id="EV-U-nope")
        assert c.in_transaction is False and c.execute("select count(*) from evidence_aliases").fetchone()[0] == 0


# ------------------------------------------------------------------ 6. the approved registration pins the EXACT position, offsets included (Work's review, item 6)
OFFSETS = [{"page": 6, "quote": "訂正後の位置にある同じ文", "start": 706, "end": 726}]
SHIFTED = [{"page": 6, "quote": "訂正後の位置にある同じ文", "start": 721, "end": 723}]


def test_an_approved_registration_refuses_a_changed_offset_that_the_ordinary_identity_cannot_see(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", OFFSETS)
    same, shifted = legacy_with(base, OFFSETS), legacy_with(base, SHIFTED)
    assert identity.classify(shifted, {**base, "proofs": OFFSETS}) == "duplicate"  # the ordinary identity compares page and normalised quote only: it cannot tell
    before = sha(path)
    with pytest.raises(ad.AliasError, match="position"):
        register(path, "EV-OFFSET", root, shifted, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == [] and sha(path) == before
    register(path, "EV-EXACT", root, same, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == [("EV-EXACT", "EV-U-head")]


def test_field_proofs_are_part_of_the_exact_position_of_an_approved_registration(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", OFFSETS)
    legacy = legacy_with(base, OFFSETS)
    with closing(dbs.app_connect(path)) as c:
        r = json.loads(c.execute("select record_json from evidence_revisions where evidence_id='EV-U-head'").fetchone()[0])
    assert "field_proofs" not in r  # the head states no field proof, the record does: not the same position
    with pytest.raises(ad.AliasError, match="position"):
        register(path, "EV-FP", root, {**legacy, "field_proofs": {"value": {"proof_indices": [0]}}}, kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert aliases(path) == []


# ------------------------------------------------------------------ 2d. the ORDINARY registration is atomic too (Work's re-check of PR #191 at 558d2f9: 10 PASS / 1 FAIL)
def _second_head_after_the_check(path, ordinary_call):
    """Run `ordinary_call` and, right after register_alias has done its head check, let ANOTHER connection commit a second head for the same root."""
    real = ad.current_head_of
    fired = []

    def check_then_race(db, root):
        out = real(db, root)
        if not fired:
            fired.append(1)
            T.revise(path, root, head_id="EV-U-b", logical="L-b")  # B commits a second head after A's check and before A's write
        return out

    with patch.object(ad, "current_head_of", side_effect=check_then_race):
        try:
            ordinary_call()
            raised = None
        except ad.AliasError as e:
            raised = e
    assert fired, "the race was not injected: the test is void"
    return raised


def test_a_second_head_committed_between_the_check_and_the_write_of_an_ordinary_alias_stores_nothing(world):
    path, root = world
    T.revise(path, root, head_id="EV-U-a", logical="L-a")  # one head: the check passes
    _, _, base = fact_and_record(path, root)
    err = _second_head_after_the_check(path, lambda: register(path, "EV-RACE", root, base))
    assert err is not None and "more than one head" in str(err)
    assert aliases(path) == []  # not stored: it would be refused at the very next resolution
    with closing(dbs.app_connect(path)) as c:
        assert c.execute("select count(*) from evidence_heads").fetchone()[0] == 2  # B's head really was committed


def test_without_the_race_an_ordinary_alias_is_stored_for_a_root_with_one_head_and_for_a_root_with_none(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    register(path, "EV-NOHEAD", root, base)  # no revision at all: still fine
    T.revise(path, root, head_id="EV-U-a", logical="L-a")
    register(path, "EV-ONEHEAD", root, base)
    assert [a for a, _ in aliases(path)] == ["EV-NOHEAD", "EV-ONEHEAD"]


# ------------------------------------------------------------------ 6b. a refused position names the KEYS that differ, so that each difference can be classified with evidence (never loosened first)
def test_a_refused_position_reports_which_keys_differ_and_nothing_else(world):
    path, root = world
    _, _, base = fact_and_record(path, root)
    add_revision(path, root, "EV-U-head", OFFSETS)
    ancillary = [{**OFFSETS[0], "extractor": "v9"}]
    with pytest.raises(ad.AliasError, match="extractor") as e:
        register(path, "EV-ANC", root, legacy_with(base, ancillary), kind="locator_corrected_copy", pinned_evidence_id="EV-U-head", approved_head_id="EV-U-head")
    assert "訂正後の位置にある同じ文" not in str(e.value)  # key names and the page only: never the quote or a value
    assert ad.position_differences(legacy_with(base, ancillary), {**base, "proofs": OFFSETS}) == [{"page": 6, "only_in_alias": ["extractor"], "only_in_head": [], "value_differs": []}]
    shifted = [{**OFFSETS[0], "start": 1}]
    assert ad.position_differences(legacy_with(base, shifted), {**base, "proofs": OFFSETS}) == [{"page": 6, "only_in_alias": [], "only_in_head": [], "value_differs": ["start"]}]
    assert ad.position_differences(legacy_with(base, OFFSETS), {**base, "proofs": OFFSETS}) == []
    assert ad.position_differences(legacy_with(base, OFFSETS), {**base, "proofs": SECOND})[0].get("unpaired") in ("alias", "head")
    assert aliases(path) == []
