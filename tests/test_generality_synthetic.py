"""Does the migrated schema keep different universities, faculties, methods and years apart? SYNTHETIC_ONLY: invented cycles driven through Work's store code (with the stage-1 patch) on the complete
migration chain. This is NOT the M1 gate g7 (a new real document format): it only shows that nothing in the identity, alias, citation, head and history model assumes one university, one method or one
year, and that an update of one cycle never leaks into another. A pass here is not a result on real data."""
import sqlite3
from contextlib import closing

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore
from src.db_contract import additive_schema as ad

CYCLES = [  # (case, university, faculty, department, method, fiscal year)
    ("c-a", "架空第一大学", "練習学部", None, "架空総合型方式", 2027),
    ("c-b", "架空第一大学", "練習学部", None, "架空総合型方式", 2028),  # the same method one year later
    ("c-c", "架空第一大学", "別の学部", "学科甲", "架空学校推薦型方式", 2027),  # another faculty, a department, another method
    ("c-d", "架空第二大学", "練習学部", "", "架空総合型方式", 2027),  # another university; an EMPTY department is the same "unspecified" as NULL
]


@pytest.fixture
def world(tmp_path):
    first = CYCLES[0]
    path = tmp_path / "multi.sqlite"
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    profiles = {}
    for i, (case, uni, fac, dep, method, year) in enumerate(CYCLES):
        profiles[case] = S.profile(university=uni, faculty=fac, method=method, fiscal_year=year, department=dep, sha="abcd"[i] * 64)
        S.ingest_cycle(store, case, profiles[case], tmp_path, eid=f"EV-{case}-1")
    with closing(sqlite3.connect(path)) as c:  # the lineage that has offerings (the real copies do): the migration then gives it the identity without the source
        c.execute("CREATE TABLE IF NOT EXISTS admission_offerings(offering_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES admission_cycles(case_id),round_name TEXT NOT NULL,entry_month INTEGER CHECK(entry_month BETWEEN 1 AND 12),scope_json TEXT NOT NULL,source_sha256 TEXT NOT NULL REFERENCES source_documents(sha256))")
        c.commit()
    r = ad.apply(path, confirm_disposable_copy=True)
    assert not r["rolled_back"], r
    return path, profiles, store, tmp_path, first


def q(path, sql, *a):
    with closing(sqlite3.connect(path)) as c:
        return c.execute(sql, a).fetchall()


def article_of(store, case):
    with store.connect() as db:
        row = db.execute("select * from article_versions where case_id=?", (case,)).fetchone()
        ev = [r[0] for r in db.execute("select evidence_id from article_evidence where article_id=?", (row["article_id"],))]
    return {"article_id": row["article_id"], "case_id": case, "input_hash": row["input_hash"], "series": row["series"], "title": row["title"], "text": row["body"], "evidence_ids": ev, "claim": S.scope(PROFILES[case])}


PROFILES: dict = {}


def approve_notice(store, profiles, case, logical, eid="EV-N-1", parent=None):
    PROFILES.update(profiles)
    rec = S.notice(profiles[case], eid=eid, logical=logical, case=case, **({"parent_evidence_id": parent} if parent else {}), sentences=[f"{case} の通知。"], value={"allowed": case})
    return S.approve(store, rec, article_of(store, case))


def test_four_cycles_of_different_universities_faculties_methods_and_years_are_four_cycles(world):
    path, profiles, store, tmp, _ = world
    assert q(path, "select count(*) from admission_cycles")[0][0] == 4 and q(path, "select count(distinct case_id) from facts")[0][0] == 4
    assert ad.plan(path)["drift"] == [] and S.audit(path)["invariants"]["DB-17"]["status"] == "pass"


def test_the_same_cycle_identity_twice_is_refused_and_an_empty_department_equals_an_unspecified_one(world):
    path, profiles, store, tmp, _ = world
    with closing(S.app_connect(path)) as c:
        for case, dep in (("dup-null", None), ("dup-empty", "")):
            with pytest.raises(sqlite3.IntegrityError):  # the same university, faculty, method and year as c-a: NULL and '' are one "unspecified" department
                c.execute("insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values(?,?,?,?,?,?,?)", (case, "架空第一大学", "練習学部", dep, "架空総合型方式", 2027, 2026))
        c.execute("insert into admission_cycles(case_id,university,faculty,department,admission_method,fiscal_year,exam_year) values('c-ok','架空第一大学','練習学部','学科乙','架空総合型方式',2027,2026)")  # a department makes it another cycle
        c.commit()
    assert q(path, "select count(*) from admission_cycles")[0][0] == 5


def test_an_update_of_one_cycle_never_changes_another_cycles_heads_or_impact_and_a_record_for_the_wrong_cycle_is_refused(world):
    path, profiles, store, tmp, _ = world
    approve_notice(store, profiles, "c-a", "notice-a")
    s2 = RevisionStore(path, tmp / "b2.sqlite")
    approve_notice(s2, profiles, "c-c", "notice-c", eid="EV-N-3")
    assert S.heads(path)["evidence"] == {"notice-a": "EV-N-1", "notice-c": "EV-N-3"}
    with closing(sqlite3.connect(path)) as c:
        a_root, c_root = ad.root_of(c, "EV-N-1"), ad.root_of(c, "EV-N-3")
        assert a_root != c_root
        impacted_a = {a for a, k, e in ad.impacted_articles(c, "EV-N-1")}
        impacted_c = {a for a, k, e in ad.impacted_articles(c, "EV-N-3")}
        assert impacted_a and impacted_c and not (impacted_a & impacted_c)  # an update of one cycle only ever finds its own articles
        arts = {r[0]: r[1] for r in c.execute("select article_id, case_id from article_versions")}
        assert all(arts.get(a, arts.get(a.split(":revision:")[0])) == "c-a" for a in impacted_a)
    s3 = RevisionStore(path, tmp / "b3.sqlite")
    wrong = S.notice(profiles["c-a"], eid="EV-N-X", logical="x", case="c-c")  # the scope of c-a under the case id of c-c
    with pytest.raises(ValueError, match="cross-cycle"):
        s3.stage([wrong], S.REGISTRY)
    assert q(path, "select count(*) from update_batches where state='candidate'")[0][0] == 0


def test_the_same_value_in_two_cycles_is_two_independent_facts_never_an_alias(world):
    path, profiles, store, tmp, _ = world
    with closing(S.app_connect(path)) as c:
        facts = c.execute("select evidence_id, case_id, fact_key, record_json from facts where case_id in ('c-a','c-b') order by case_id").fetchall()
        assert len(facts) == 2 and facts[0][2] == facts[1][2]  # the same fact_key, the same value (quota 16), two years
        with pytest.raises(sqlite3.IntegrityError):  # the second cycle's evidence cannot be registered as an alias of the first (another case)
            c.execute("insert into evidence_aliases(alias_id,root_evidence_id,case_id,fact_key,kind,reason,created_at) values('EV-ALIAS',?,?,?,'legacy_compat_id','x','t')", (facts[0][0], facts[1][1], facts[0][2]))


def test_offerings_with_the_same_round_and_month_in_different_cycles_are_different_offerings(world):
    path, profiles, store, tmp, _ = world
    sha = q(path, "select sha256 from source_documents limit 1")[0][0]
    with closing(S.app_connect(path)) as c:
        for oid, case in (("o1", "c-a"), ("o2", "c-b"), ("o3", "c-c")):
            c.execute("insert into admission_offerings values(?,?,?,?,?,?)", (oid, case, "夏秋", 4, "{}", sha))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("insert into admission_offerings values('o4','c-a','夏秋',4,'{}',?)", (sha,))  # the same offering of the same cycle (the source is not part of the identity)
        c.commit()
    assert q(path, "select count(*) from admission_offerings")[0][0] == 3 and q(path, "select count(*) from offering_sources")[0][0] == 3


def test_the_heads_of_the_past_are_kept_apart_per_logical_fact_across_cycles(world):
    path, profiles, store, tmp, _ = world
    approve_notice(store, profiles, "c-a", "notice-a")
    with closing(sqlite3.connect(path)) as c:
        t_a = c.execute("select max(created_at) from update_events").fetchone()[0]
    s2 = RevisionStore(path, tmp / "b2.sqlite")
    approve_notice(s2, profiles, "c-d", "notice-d", eid="EV-N-4")
    with closing(sqlite3.connect(path)) as c:
        assert ad.read_as_of(c, "notice-a", t_a) == "EV-N-1" and ad.read_as_of(c, "notice-d", t_a) is None  # the second cycle had no head yet at that moment
        assert ad.read_as_of(c, "notice-d", "9999-12-31") == "EV-N-4" and ad.read_as_of(c, "notice-a", "9999-12-31") == "EV-N-1"
    assert S.audit(path)["invariants"]["DB-18"]["status"] == "pass"
