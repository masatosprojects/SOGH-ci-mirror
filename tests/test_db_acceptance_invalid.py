"""DB acceptance B — invalid data. Target kind: synthetic. Each case is rejected either by Work's store code (ValueError, nothing written)
or, when the damage is in the file itself, by the independent audit (the named invariant fails and no other)."""
import hashlib
import json
from contextlib import closing
import sqlite3

import pytest

from tests import db_support as S
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.notice_articles import revise_article  # noqa: E402
from admissions_pipeline.store import canonical  # noqa: E402
from datetime import date  # noqa: E402


@pytest.fixture
def world(tmp_path):
    path, p = S.make_native(tmp_path)
    store = RevisionStore(path, tmp_path / "backup.sqlite")
    return path, p, store, tmp_path


NOTHING = {"evidence": {}, "articles": {}}


def test_a_reference_to_a_university_or_method_that_has_no_cycle_is_rejected(world):
    path, p, store, _ = world
    for field, value in (("university", "存在しない大学"), ("admission_method", "存在しない方式"), ("faculty", "存在しない学部")):
        with pytest.raises(ValueError, match="cross-cycle"):
            store.stage([S.notice(p, **{field: value})], S.REGISTRY)
    with pytest.raises(ValueError):  # a case id that does not exist
        store.stage([S.notice(p, case="no-such-case")], S.REGISTRY)
    assert S.heads(path) == NOTHING


def test_a_year_mix_up_is_rejected(world):
    path, p, store, _ = world
    with pytest.raises(ValueError, match="cross-cycle"):
        store.stage([S.notice(p, fiscal_year=2026)], S.REGISTRY)


def test_another_universitys_quota_cannot_be_registered_into_this_cycle(world):
    path, p, store, tmp = world
    other = S.profile(university="別の大学", sha="c" * 64)
    S.ingest_cycle(S.EvidenceStore(path), "case-b", other, tmp, count=99)
    with pytest.raises(ValueError, match="cross-cycle"):
        store.stage([S.notice(other, case="case")], S.REGISTRY)  # the other university's scope under this case id


def test_an_article_cannot_cite_evidence_that_is_unknown_or_belongs_to_another_cycle(world):
    path, p, store, tmp = world
    S.ingest_cycle(S.EvidenceStore(path), "case-b", S.profile(university="別の大学", sha="c" * 64), tmp, count=99)
    batch = store.stage([S.notice(p)], S.REGISTRY)
    revised = revise_article(S.base_article(store), store.effective_records(batch), date(2026, 11, 1))
    for text in (revised["text"] + "\n募集人員は99名[EV-case-b-1]です。", revised["text"] + "\n募集人員は1名[EV-GHOST]です。"):
        bad = dict(revised, text=text, evidence_ids=sorted(set(revised["evidence_ids"]) | {t for t in ("EV-case-b-1", "EV-GHOST") if t in text}))
        qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical([bad]).encode()).hexdigest()}
        with pytest.raises(ValueError):
            store.finalize(batch, [bad], qa, S.REGISTRY)
    assert S.heads(path) == NOTHING


def test_an_unregistered_fact_key_a_wrong_value_type_and_a_bad_stage_in_the_file_fail_the_registry_invariant(world):
    path, p, store, _ = world
    with closing(sqlite3.connect(path)) as db:
        for i, (key, value, extra) in enumerate([("brand_new_key", {"x": 1}, {}), ("quota", {"count": "sixteen", "unit": "名"}, {}),
                                                  ("interview", {"minutes": 30, "type": "t"}, {"stage": 3})]):
            rec = json.loads(db.execute("SELECT record_json FROM facts").fetchone()[0])
            rec.update(evidence_id=f"EV-bad-{i}", fact_key=key, key=key, value=value, **extra)
            db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", (f"EV-bad-{i}", "case", "a" * 64, key + str(i), json.dumps(value), json.dumps(rec), "source_checked_for_saved_version"))
        db.commit()
    problems = S.failing(path)["DB-11"]["problems"]
    kinds = " ".join(x["what"] for x in problems)
    assert "unregistered_fact_key" in kinds and "value_type_mismatch" in kinds and "stage_invalid" in kinds


def test_a_source_hash_that_disagrees_with_the_record_fails(world):
    path, *_ = world
    S.sql(path, "INSERT INTO source_documents VALUES (?,?,?,?,?)", "e" * 64, "https://example.ac.jp/other", "x", "2026-11-01", "c")
    S.sql(path, "UPDATE facts SET source_sha256=? WHERE evidence_id='EV-case-1'", "e" * 64)
    assert set(S.failing(path)) == {"DB-04"}


def test_a_quote_that_is_not_on_the_stored_page_fails(world):
    path, *_ = world
    S.sql(path, "UPDATE source_pages SET text='全く別の文章です。', text_sha256=?", hashlib.sha256("全く別の文章です。".encode()).hexdigest())
    assert set(S.failing(path)) == {"DB-12"}


def test_the_same_evidence_id_with_different_content_is_rejected(world):
    path, p, store, _ = world
    S.approve(store, S.notice(p), S.base_article(store))
    with pytest.raises(ValueError, match="immutable"):
        store.stage([S.notice(p, value={"allowed": "別の内容"})], S.REGISTRY)
    with pytest.raises(ValueError):  # and the original fact cannot be overwritten through ingest either
        S.ingest_cycle(S.EvidenceStore(path), "case", S.profile(), world[3], count=17)


def test_a_condition_stated_with_an_exception_that_contradicts_it_is_a_qa_matter_not_a_db_one(world):
    """Documented boundary: whether a sentence contradicts its value is the article QA (registry assertions), not a database invariant."""
    from src.verify.qualitative import check_qualitative
    ev = {"EV-C": {"evidence_id": "EV-C", "fact_key": "common_test", "value": {"required": True}}}
    assert check_qualitative("# t\n\n大学入学共通テストの受験は不要です[EV-C]。\n", ev)
