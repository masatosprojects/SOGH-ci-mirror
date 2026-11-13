"""G-05: the same fact under two evidence ids, and the right granularity of a uniqueness key.

Negative tests: a unique key that is too coarse refuses a real fact; one that is too fine accepts a duplicate; a conflict is not an alias.
Real data (repository_sample): the six general-selection facts. Nothing is renamed, nothing deleted.
"""
import json
import re
import sqlite3
from contextlib import closing

import pytest

from src.db_contract import identity as ident
from src.db_contract.load_export import case_id_of
from src.regression.fullview import find_views
from src.regression.handoffs import INBOX, find_exports


def rec(eid, value, proofs, key="quota", sha="s" * 64):
    return {"evidence_id": eid, "fact_key": key, "value": value, "source_sha256": sha, "university": "U", "faculty": "F", "department": None,
            "admission_method": "M", "fiscal_year": 2027, "proofs": proofs}


P5 = [{"page": 5, "quote": "募集人員は16名です。"}]
P6 = [{"page": 6, "quote": "募集人員は16名です。"}]
P7 = [{"page": 7, "quote": "他の枠の募集人員は8名です。"}]
V16, V8 = {"count": 16}, {"count": 8}


def kinds(*records):
    ev = {r["evidence_id"]: r for r in records}
    return ident.find_groups(ev, case_id_of)


def test_same_value_and_same_place_is_one_fact_under_two_ids():
    g = kinds(rec("EV-A-01", V16, P5), rec("EV-B-01", V16, P5))
    assert g[0]["kinds"] == ["duplicate"] and ident.propose_aliases(g) == {"EV-B-01": "EV-A-01"}


def test_the_whitespace_and_width_of_a_quote_do_not_make_a_new_fact():
    a = rec("EV-A", V16, [{"page": 5, "quote": "募集人員は１６名です。"}])
    b = rec("EV-B", V16, [{"page": 5, "quote": "募集人員は 16名 です。"}])
    assert ident.classify(a, b) == "duplicate"


def test_same_value_at_another_position_is_the_same_fact_whose_proof_was_corrected():
    g = kinds(rec("EV-A-01", V16, P5), rec("EV-B-01", V16, P6))
    assert g[0]["kinds"] == ["same_value_moved"] and ident.propose_aliases(g, prefer=["EV-A-01"]) == {"EV-B-01": "EV-A-01"}


def test_two_real_facts_of_one_key_in_one_source_are_independent_and_get_no_alias():
    g = kinds(rec("EV-A", V16, P5), rec("EV-B", V8, P7))
    assert g[0]["kinds"] == ["independent"] and ident.propose_aliases(g) == {}


def test_two_different_statements_about_the_same_place_are_a_conflict_and_never_an_alias():
    g = kinds(rec("EV-A", V16, P5), rec("EV-B", V8, P5))
    assert g[0]["kinds"] == ["conflict"] and ident.propose_aliases(g) == {}


def test_a_group_with_a_conflict_among_duplicates_gets_no_alias_at_all():
    g = kinds(rec("EV-A", V16, P5), rec("EV-B", V16, P5), rec("EV-C", V8, P5))
    assert "conflict" in g[0]["kinds"] and ident.propose_aliases(g) == {}


def test_a_different_source_or_fact_key_or_case_is_never_grouped():
    assert kinds(rec("EV-A", V16, P5), rec("EV-B", V16, P5, sha="t" * 64)) == []
    assert kinds(rec("EV-A", V16, P5), rec("EV-B", V16, P5, key="interview")) == []
    other = rec("EV-B", V16, P5)
    other["university"] = "別の大学"
    assert kinds(rec("EV-A", V16, P5), other) == []


def test_revisions_with_a_logical_id_are_not_duplicates_of_their_parent():
    parent, child = rec("EV-A", V16, P5), rec("EV-U-1", V16, P5)
    child["logical_id"] = "notice"
    assert kinds(parent, child) == []


# ------------------------------------------------------------- what the unique key should be (an experiment, not a decision)
SQL = "CREATE TABLE facts(evidence_id TEXT PRIMARY KEY, case_id TEXT, source_sha256 TEXT, fact_key TEXT, locator TEXT, {unique})"


def table(unique):
    db = sqlite3.connect(":memory:")
    db.execute(SQL.format(unique=unique))
    return db


def insert(db, r):
    db.execute("INSERT INTO facts VALUES (?,?,?,?,?)", (r["evidence_id"], "case", r["source_sha256"], r["fact_key"], ident.locator_hash(r)))


def test_the_current_key_refuses_a_second_real_fact_of_the_same_key():
    """UNIQUE(case, source, fact_key) — today's constraint — also refuses two INDEPENDENT facts (two quotas in one guideline)."""
    with closing(table("UNIQUE(case_id, source_sha256, fact_key)")) as db:
        insert(db, rec("EV-A", V16, P5))
        with pytest.raises(sqlite3.IntegrityError):
            insert(db, rec("EV-B", V8, P7))


def test_a_key_that_includes_the_locator_stores_independent_facts_and_still_refuses_the_same_fact_twice():
    with closing(table("UNIQUE(case_id, source_sha256, fact_key, locator)")) as db:
        insert(db, rec("EV-A", V16, P5))
        insert(db, rec("EV-B", V8, P7))  # independent: accepted
        with pytest.raises(sqlite3.IntegrityError):
            insert(db, rec("EV-C", V16, P5))  # the same fact again, under a new id: refused


def test_a_locator_key_alone_does_not_catch_a_corrected_position_so_aliases_are_still_needed():
    """The corrected proof (page 5 -> 6) is a different locator: the finer key accepts it. Only the fingerprint comparison sees it."""
    with closing(table("UNIQUE(case_id, source_sha256, fact_key, locator)")) as db:
        insert(db, rec("EV-A", V16, P5))
        insert(db, rec("EV-B", V16, P6))  # accepted by the key ...
    assert ident.classify(rec("EV-A", V16, P5), rec("EV-B", V16, P6)) == "same_value_moved"  # ... and found by the comparison


# ------------------------------------------------------------- the real repository data (repository_sample)
def real():
    exports = {e.key: e.load() for e in find_exports()}
    gen = next(v for k, v in exports.items() if "general" in k)
    view = json.loads(find_views()[0].read_text(encoding="utf-8"))
    base = json.loads((INBOX / "work-updates-v2/samples/current/base-state.json").read_text(encoding="utf-8"))
    return exports, gen, view, base


def test_the_six_general_selection_facts_are_the_same_facts_under_two_id_spaces():
    exports, gen, view, base = real()
    ev = {}
    for e in [*exports.values(), view, base]:
        ev.update(e["evidence"])
    groups = ident.find_groups(ev, case_id_of)
    assert {frozenset(g["ids"]) for g in groups} == {frozenset({f"EV-G27-0{n}-e1137e", f"EV-G27C-0{n}-e1137e"}) for n in range(1, 7)}
    by_fact = {g["fact_key"]: g["kinds"] for g in groups}
    assert by_fact["quota"] == ["same_value_moved"]  # the proof position of the quota was corrected (a revision EV-U-… points at the parent EV-G27-01)
    assert all(k == ["duplicate"] for f, k in by_fact.items() if f != "quota")
    assert not any("conflict" in g["kinds"] or "independent" in g["kinds"] for g in groups)  # no real fact was blocked by the current key
    aliases = ident.propose_aliases(groups, prefer=sorted(i for i in ev if i.startswith("EV-G27-")))
    assert aliases == {f"EV-G27C-0{n}-e1137e": f"EV-G27-0{n}-e1137e" for n in range(1, 7)}


def test_no_article_cites_both_id_spaces_and_the_two_spaces_belong_to_different_deliveries():
    exports, gen, view, base = real()
    for name, data in (("general export", gen), ("view", view), ("base", base)):
        for a in data["articles"]:
            cites = set(re.findall(r"\[(EV-[\w-]+)\]", a["text"]))
            assert not (any(c.startswith("EV-G27-") for c in cites) and any(c.startswith("EV-G27C-") for c in cites)), (name, a["article_id"])
    assert any(c.startswith("EV-G27C-") for a in gen["articles"] for c in re.findall(r"\[(EV-[\w-]+)\]", a["text"]))
    assert not any("EV-G27C-" in a["text"] for a in view["articles"] + base["articles"])


def test_the_id_comes_from_the_profile_code_and_the_ordinal_not_from_the_content():
    """The cause (read from the code, not guessed): extract.py builds EV-<profile code>-<ordinal>-<sha6>; the two profiles differ in `code`."""
    pipeline = INBOX / "work-updates-v2" / "pipeline"
    assert 'f"EV-{self.profile[\'code\']}-{len(self.facts)+1:02d}-{self.profile[\'sha256\'][:6]}"' in (pipeline / "admissions_pipeline" / "extract.py").read_text(encoding="utf-8")
    profile = json.loads((pipeline / "config" / "profiles" / "tsukuba-klis-general-2027.json").read_text(encoding="utf-8"))
    assert profile["code"] == "G27C"


def test_the_correction_revision_points_at_the_old_space_so_the_old_ids_must_stay_resolvable():
    exports, gen, view, base = real()
    corrected = view["evidence"]["EV-U-8d8e1d177883"]
    assert corrected["parent_evidence_id"] == "EV-G27-01-e1137e" and "EV-G27-01-e1137e" in base["evidence"]
