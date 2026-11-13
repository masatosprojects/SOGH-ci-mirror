"""Real-source integration and negative tests; no API calls or publishing."""
import copy
import hashlib
import json
import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from admissions_pipeline.__main__ import run_pipeline
from admissions_pipeline.articles import build_article, validate_article, verify_pack
from admissions_pipeline.extract import Extractor, ExtractionError, PROFILES, extract_pdf, normalize
from admissions_pipeline.legacy import compare, inspect_legacy, integrate_legacy
from admissions_pipeline.store import EvidenceStore, canonical

ROOT = Path(__file__).resolve().parents[1]
SOURCES = Path(os.environ.get("SOGH_SOURCE_ROOT", ROOT / "night_output"))
LEGACY = Path(os.environ.get("SOGH_LEGACY_DB", ROOT / "inputs/db_v02/38756fceed2048d8/admission_media_v0_2.sqlite"))
COLLAB = Path(os.environ.get("SOGH_CLAUDE_ROOT", ROOT.parent / "SOGH-collab"))
AVAILABLE = all((SOURCES / (p["sha256"] + ".pdf")).exists() for p in PROFILES.values())
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="inspected official PDF editions are not present locally")


@pytest.fixture(scope="module")
def extracted():
    return {case: extract_pdf(case, SOURCES / (p["sha256"] + ".pdf")) for case, p in PROFILES.items()}


@pytest.fixture
def packs(tmp_path, extracted):
    store = EvidenceStore(tmp_path / "admissions.sqlite")
    result = []
    for case, data in extracted.items():
        store.ingest(data, "2026-11-01")
        result.append(store.pack(case, data.profile["sha256"]))
    return store, result


def test_real_source_quota_scope_and_deadlines(packs):
    _, data = packs
    tsu = {f["key"]: f for f in data[0]["facts"]}
    keio = {f["key"]: f for f in data[1]["facts"]}
    assert tsu["quota"]["value"]["count"] == 5
    assert tsu["quota"]["scope"] == "department_and_method"
    assert keio["quota"]["value"]["count"] == 150
    assert keio["quota"]["scope"] == "faculty_annual_AO_aggregate"
    assert keio["quota"]["value"]["summer_autumn_only_count"] is None
    assert tsu["online_period"]["value"]["end"] == "2026-09-02T09:00:00+09:00"
    assert keio["online_period"]["value"]["end"] == "2026-09-01T15:00:00+09:00"
    assert keio["postal_period"]["value"]["qualifier"] == "日本国内は締切日消印有効、海外は締切日必着"
    assert keio["online_period"]["related_keys"] == ["maintenance"]


def test_different_eligibility_logic_and_interview_time_types(packs):
    _, data = packs
    tsu = {f["key"]: f["value"] for f in data[0]["facts"]}
    keio = {f["key"]: f["value"] for f in data[1]["facts"]}
    assert tsu["eligibility"]["logic"] == "any_of_1_to_3"
    assert keio["eligibility"]["logic"] == "all_of_1_to_4"
    assert tsu["common_test"]["required"] is False
    assert keio["interview"]["type"] == "allocated_time_window_not_net_question_time"
    assert keio["second_stage_date"]["selection"] == "one_of_not_both"


def test_writing_limits_are_chars_and_pages_not_english_word_count(packs):
    _, data = packs
    tsu = {f["key"]: f["value"] for f in data[0]["facts"]}
    keio = {f["key"]: f["value"] for f in data[1]["facts"]}
    assert tsu["statement_length"]["max_characters"] == 800
    assert tsu["recommendation_format"]["cover_and_activity_report"] == "specified_forms"
    assert keio["personal_statement"]["essay_max_en_chars"] == 4000
    assert keio["personal_statement"]["free_format_a4_pages_max"] == 2
    assert keio["referees"]["evaluators_required"] == 2


def test_all_saved_quotes_resolve_to_exact_original_pages(extracted):
    for data in extracted.values():
        for fact in data.facts:
            for proof in fact["proofs"]:
                assert proof["quote"] in data.pages[proof["page"] - 1]
                assert normalize(proof["quote"]) == proof["quote_normalized"]


def test_changed_pdf_hash_is_rejected_before_parsing(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-fixture-not-the-reviewed-edition")
    with pytest.raises(ExtractionError, match="hash changed"):
        extract_pdf(next(iter(PROFILES)), path)


def test_missing_quota_exception_fails_closed(extracted):
    data = extracted["tsukuba-klis-ac-2027"]
    pages = list(data.pages)
    pages[4] = pages[4].replace("この入試の合格者にふさわしい志願者がいない", "removed exception")
    with pytest.raises(ExtractionError):
        Extractor(data.case_id, pages).tsukuba()


@pytest.mark.parametrize("mutation", ["number", "year", "source_url", "remove_fact"])
def test_forged_db_or_json_flags_do_not_bypass_original_validation(packs, mutation):
    _, data = packs
    pack = copy.deepcopy(data[0])
    if mutation == "number":
        pack["facts"][0]["value"]["count"] = 999
    elif mutation == "year":
        pack["cycle"]["fiscal_year"] = 2028
    elif mutation == "source_url":
        pack["source"]["url"] = "https://example.com/forged.pdf"
    else:
        pack["facts"].pop()
    assert verify_pack(pack)
    with pytest.raises(ValueError):
        build_article(pack, "overview", date(2026, 11, 1))


@pytest.mark.parametrize("mutation", ["wrong_number", "unknown_citation", "new_deadline", "publish", "scope"])
def test_article_mutation_is_rejected(packs, mutation):
    _, data = packs
    pack = data[1]
    article = build_article(pack, "overview", date(2026, 11, 1))
    assert validate_article(article, pack) == []
    if mutation == "wrong_number":
        article["text"] = article["text"].replace("150名", "999名")
    elif mutation == "unknown_citation":
        article["text"] += "[EV-INVENTED]"
    elif mutation == "new_deadline":
        article["text"] += "締切は2027年2月29日です。"
    elif mutation == "publish":
        article["publish_allowed"] = True
    else:
        article["claim"]["faculty"] = "総合政策学部"
    assert validate_article(article, pack)


def test_idempotent_ingest_and_immutable_article_versions(packs, extracted):
    store, data = packs
    for item in extracted.values():
        store.ingest(item, "2026-11-01")
    assert store.counts()["facts"] == 30
    article = build_article(data[0], "overview", date(2026, 11, 1))
    store.save_article(article, Path("draft.md"))
    store.save_article(article, Path("draft.md"))
    assert store.counts()["article_versions"] == 1
    article["text"] += "modified without a version change"
    with pytest.raises(ValueError, match="immutable article"):
        store.save_article(article, Path("draft.md"))


@pytest.mark.skipif(not LEGACY.exists(), reason="user-supplied legacy DB not available")
def test_legacy_27_claims_link_to_originals_without_promoting_summary_hashes(packs):
    store, data = packs
    before = hashlib.sha256(LEGACY.read_bytes()).hexdigest()
    report = integrate_legacy(store, LEGACY, data)
    assert report["records_preserved"] == 121
    assert report["reconciliation_counts"] == {"matched_saved_original": 20, "matched_with_added_context": 7, "needs_review": 0, "conflict": 0}
    assert report["summary_hashes_used_as_pdf_hashes"] is False
    assert report["old_verified_flags_promoted"] is False
    assert hashlib.sha256(LEGACY.read_bytes()).hexdigest() == before
    report2 = integrate_legacy(store, LEGACY, data)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM legacy_records").fetchone()[0] == 121
        assert db.execute("SELECT count(*) FROM legacy_fact_links").fetchone()[0] == 27


@pytest.mark.skipif(not LEGACY.exists(), reason="user-supplied legacy DB not available")
def test_legacy_wrong_quota_or_scope_is_a_conflict(packs):
    _, data = packs
    facts = inspect_legacy(LEGACY)["records"]["fact_claims"]
    row = copy.deepcopy(next(f for f in facts if f["id"] == "fact_k01"))
    current = next(f for f in data[1]["facts"] if f["key"] == "quota")
    v = json.loads(row["value_json"])
    v["scope"] = "2026夏秋AO単独"
    row["value_json"] = canonical(v)
    assert compare(row, current)[0] == "conflict"
    v["scope"] = "2026年度実施AO入試の合計・4月/9月入学"
    v["value"] = 999
    row["value_json"] = canonical(v)
    assert compare(row, current)[0] == "conflict"


@pytest.mark.skipif(not COLLAB.exists() or not LEGACY.exists(), reason="Claude QA repository or legacy DB unavailable")
def test_full_real_pdf_sqlite_drafts_claude_flow_and_rerun(tmp_path):
    report = run_pipeline(SOURCES, tmp_path / "state", tmp_path / "out", COLLAB,
                          as_of=date(2026, 11, 1), legacy_db=LEGACY)
    assert report["success"] is True
    assert report["new_registered_facts"] == 30
    assert report["new_drafts"] == 4 and report["claude_quality_success"] is True
    assert report["final_snapshot_integrity"] == ["ok"]
    assert report["final_snapshot_foreign_keys"] == []
    assert report["legacy_v0_2"]["integrated"] is True
    with sqlite3.connect(report["database_snapshot"]) as db:
        assert db.execute("SELECT count(*) FROM qa_runs WHERE success=1").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM article_evidence").fetchone()[0] > 0
    for case in report["case_results"]:
        for path in case["drafts"]:
            assert Path(path).is_file()
    rerun = run_pipeline(SOURCES, tmp_path / "state", tmp_path / "out", COLLAB,
                         as_of=date(2026, 11, 1), legacy_db=LEGACY)
    assert rerun["success"]
    assert rerun["new_registered_facts"] == 0 and rerun["new_article_versions"] == 0
