"""Tests of the correction-candidate check (src/integration/evidence_correction_check.py, contract docs/EVIDENCE_CORRECTION_VERSION_CONTRACT.md).

SYNTHETIC_ONLY for the always-defined tests: an invented FAQ page and an invented notice, built in memory. Two further tests read Work's real correction candidates (reports/phase3-20261102) against
the read-only audit copy and the saved sources; they are DEFINED ONLY when those files exist on this computer (absent, never skipped), so a clean CI machine does not define them.
Nothing is written; no network. Passing these tests does not apply a correction, register evidence or accept anything."""
import glob
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from src.integration import evidence_correction_check as E

SHA = "ab" * 32
PAGE = "\n".join([
    "対象の案内", "Ｑ１　出願はいつですか？", "出願は１０月です。", "Ｑ２　生成ＡＩを使った場合はどうしますか？", "引用元を明記してください。下線を引いてください。", "Ｑ３　画像はどうしますか？", "画像にも出典を付けます。",
    "令和８年１０月１日", "2026 年度の案内です。",
])
PAGES = [PAGE]
NP = E.norm(PAGE)


def _loc(idx, quote):
    start = NP.index(E.norm(quote))
    return {"proof_index": idx, "page": 1, "normalized_start": start, "normalized_end": start + len(E.norm(quote)),
            "quote_sha256": hashlib.sha256(E.norm(quote).encode()).hexdigest(), "source_page_text_sha256": hashlib.sha256(PAGE.encode()).hexdigest()}


PRED = {"source_url": "https://example.invalid/faq/", "source_sha256": SHA, "applicability": "2027年入学対象の案内", "published_date": "2026-10-01",
        "proofs": [{"section": "Ｑ１　出願はいつですか？", "page": 1}, {"section": "Ｑ１　出願はいつですか？", "page": 1}]}


def item(**over):
    base = {"predecessor_evidence_id": "EV-X", "predecessor_record_sha256": E.canonical_sha256(PRED), "source_sha256": SHA, "source_url": PRED["source_url"],
            "proposed_edits": [{"path": "/proofs/0/section", "old": PRED["proofs"][0]["section"], "proposed": "Ｑ２　生成ＡＩを使った場合はどうしますか？"}],
            "locators": [_loc(0, "引用元を明記してください。")], "new_evidence_id": None, "meaning_checked": "not_run", "requires_independent_review": True, "applied": False}
    base.update(over)
    return base


def codes(findings, level="error"):
    return sorted({f["code"] for f in findings if f["level"] == level})


def run(it, pred=PRED, pages=PAGES, sha=SHA):
    return E.check_candidate(it, pred, pages, source_sha256=sha)


def test_a_correct_section_correction_has_no_blocking_finding():
    assert E.blocking(run(item())) == []


def test_the_section_must_be_the_nearest_heading_before_the_quote():
    wrong = item(proposed_edits=[{"path": "/proofs/0/section", "old": PRED["proofs"][0]["section"], "proposed": "Ｑ１　出願はいつですか？"}])
    assert codes(run(wrong)) == ["C-SECTION"]
    a_heading_that_comes_after = item(proposed_edits=[{"path": "/proofs/0/section", "old": PRED["proofs"][0]["section"], "proposed": "Ｑ３　画像はどうしますか？"}])
    assert codes(run(a_heading_that_comes_after)) == ["C-SECTION"]
    a_heading_that_is_not_on_the_page = item(proposed_edits=[{"path": "/proofs/0/section", "old": PRED["proofs"][0]["section"], "proposed": "存在しない見出し？"}])
    assert codes(run(a_heading_that_is_not_on_the_page)) == ["C-SECTION"]


@pytest.mark.parametrize("meta", [{"applied": True}, {"new_evidence_id": "EV-NEW"}, {"meaning_checked": "pass"}, {"requires_independent_review": False}])
def test_a_proposal_that_claims_to_be_applied_or_meaning_checked_is_blocked(meta):
    assert "C-META" in codes(run(item(**meta)))


def test_a_proposal_made_against_another_record_is_blocked():
    changed = deepcopy(PRED)
    changed["applicability"] = "別の値"
    assert "C-PRED" in codes(run(item(), pred=changed))


def test_a_source_that_is_not_the_one_of_the_predecessor_is_blocked():
    assert "C-SOURCE" in codes(run(item(), sha="cd" * 32))
    assert "C-SOURCE" in codes(run(item(source_url="https://example.invalid/other/")))


def test_a_quote_hash_or_page_hash_that_does_not_match_the_saved_text_is_blocked():
    bad_quote = item()
    bad_quote["locators"][0]["quote_sha256"] = "0" * 64
    bad_page = item()
    bad_page["locators"][0]["source_page_text_sha256"] = "0" * 64
    shifted = item()
    shifted["locators"][0]["normalized_start"] += 1
    assert codes(run(bad_quote)) == codes(run(bad_page)) == codes(run(shifted)) == ["C-LOCATOR"]
    nonexistent = item()
    nonexistent["locators"][0]["page"] = 2
    assert "C-LOCATOR" in codes(run(nonexistent))  # the heading edit that is anchored to it is blocked too


def test_the_page_hash_is_the_hash_of_the_raw_extractor_text_not_of_the_normalised_text():
    raw_ok = item()
    assert raw_ok["locators"][0]["source_page_text_sha256"] == hashlib.sha256(PAGE.encode()).hexdigest() != hashlib.sha256(NP.encode()).hexdigest()
    normalised = item()
    normalised["locators"][0]["source_page_text_sha256"] = hashlib.sha256(NP.encode()).hexdigest()
    assert codes(run(normalised)) == ["C-LOCATOR"]


@pytest.mark.parametrize("path", ["/proofs/0/quote", "/proofs/0/normalized_start", "/source_sha256", "/source_url", "/fiscal_year", "/case_id", "/value", "/retrieved_at"])
def test_a_correction_may_not_change_a_quote_a_position_a_hash_the_source_or_the_scope(path):
    assert "C-PATH" in codes(run(item(proposed_edits=[{"path": path, "old": "x", "proposed": "y"}])))


def test_an_edit_whose_old_value_is_not_the_current_value_is_blocked():
    stale = item(proposed_edits=[{"path": "/applicability", "old": "古い値", "proposed": "2026年度の案内"}])
    assert "C-OLD" in codes(run(stale))
    missing = item(proposed_edits=[{"path": "/published_date", "old": "x", "proposed": None, "document_date_separate_candidate": "2026-10-01"}], )
    pred = {k: v for k, v in PRED.items() if k != "published_date"}
    assert "C-OLD" in codes(E.check_candidate({**missing, "predecessor_record_sha256": E.canonical_sha256(pred)}, pred, PAGES, source_sha256=SHA))


def test_an_applicability_with_a_year_the_source_does_not_contain_is_blocked_and_the_old_unsupported_year_is_reported():
    unsupported = item(proposed_edits=[{"path": "/applicability", "old": PRED["applicability"], "proposed": "2027年入学対象の案内"}])
    assert codes(run(unsupported)) == ["C-YEAR"]
    neutral = item(proposed_edits=[{"path": "/applicability", "old": PRED["applicability"], "proposed": "2026年度の案内。入学年度との対応は未確認。"}])
    assert E.blocking(run(neutral)) == [] and codes(run(neutral), "info") == ["C-YEAR"]  # the old '2027' is not in the source


def test_a_year_written_in_the_japanese_era_counts_as_the_same_year():
    reiwa = item(proposed_edits=[{"path": "/applicability", "old": PRED["applicability"], "proposed": "令和8年の案内。入学年度との対応は未確認。"}])
    assert E.blocking(run(reiwa)) == []


def test_the_publication_date_may_be_replaced_only_by_null_with_a_document_date_that_occurs_in_the_source():
    ok = item(proposed_edits=[{"path": "/published_date", "old": "2026-10-01", "proposed": None, "document_date_separate_candidate": "2026-10-01"}])
    assert E.blocking(run(ok)) == []  # 令和８年１０月１日 in the page = 2026-10-01
    other = item(proposed_edits=[{"path": "/published_date", "old": "2026-10-01", "proposed": None, "document_date_separate_candidate": "2026-09-15"}])
    assert codes(run(other)) == ["C-DATE"]
    no_candidate = item(proposed_edits=[{"path": "/published_date", "old": "2026-10-01", "proposed": None}])
    assert codes(run(no_candidate)) == ["C-DATE"]
    a_new_publication_date = item(proposed_edits=[{"path": "/published_date", "old": "2026-10-01", "proposed": "2026-09-15", "document_date_separate_candidate": "2026-10-01"}])
    assert codes(run(a_new_publication_date)) == ["C-DATE"]


def test_two_proofs_on_the_same_span_are_reported_as_a_warning_not_an_error():
    twin = item()
    twin["locators"].append({**twin["locators"][0], "proof_index": 1})
    assert E.blocking(run(twin)) == [] and codes(run(twin), "warning") == ["C-LOCATOR"]


def test_the_check_reads_only():
    import socket
    import sqlite3 as _sqlite

    def boom(*a, **k):
        raise AssertionError("I/O in a read-only check")
    original = (socket.socket, _sqlite.connect)
    socket.socket, _sqlite.connect = boom, boom
    try:
        run(item())
    finally:
        socket.socket, _sqlite.connect = original


# ---- the real candidates of Work (defined only where the files exist) ---------------------------------------------------------------------------------------------------

_cand = glob.glob(r"C:\Users\USER\OneDrive\*\ChatGPT\SOGH\reports\phase3-20261102\source-correction-candidates.json")
_copy = Path(os.environ.get("USERPROFILE", "")) / "SOGHRuntime" / "AuditCopies" / "work-resume-m1-a6c4474" / "v06.sqlite"
_bodies = glob.glob(r"C:\Users\USER\OneDrive\*\ChatGPT\SOGH\outputs\updates-v2\monitor\bodies")
if _cand and _copy.exists() and _bodies:
    import re
    import unicodedata
    from html.parser import HTMLParser

    class _H(HTMLParser):  # Work's extractor id: script/style only
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            self.skip += tag in ("script", "style")

        def handle_endtag(self, tag):
            self.skip = max(0, self.skip - (tag in ("script", "style")))

        def handle_data(self, d):
            if not self.skip and d.strip():
                self.out.append(d.strip())

    def _pages(path, kind):
        raw = Path(path).read_bytes()
        if kind == "html":
            h = _H()
            h.feed(raw.decode("utf-8"))
            return ["\n".join(h.out)]
        try:
            import fitz
        except ImportError:
            return None
        with fitz.open(stream=raw, filetype="pdf") as doc:
            return [p.get_text() for p in doc]

    def _real(eid):
        items = json.loads(Path(_cand[0]).read_text(encoding="utf-8"))["items"]
        it = next(i for i in items if i["predecessor_evidence_id"] == eid)
        with closing(sqlite3.connect(_copy.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rec = json.loads(db.execute("SELECT record_json FROM evidence_revisions WHERE evidence_id=?", (eid,)).fetchone()[0])
        sha = rec.get("source_pdf_sha256") or rec["source_sha256"]
        f = Path(_bodies[0]) / f"{sha}.{rec['source_kind']}"
        return it, rec, f, sha

    try:
        import fitz  # noqa: F401
        _EIDS = ["EV-U-61c185ec5771", "EV-U-b9e7fb33158b", "EV-U-2895dfe26d3b"]
    except ImportError:  # the PDF candidate needs PyMuPDF: it is not DEFINED (not skipped, not passed) where PyMuPDF is absent
        _EIDS = ["EV-U-61c185ec5771", "EV-U-b9e7fb33158b"]

    @pytest.mark.parametrize("eid", _EIDS)
    def test_works_real_correction_candidates_pass_the_check_against_the_audit_copy_and_the_saved_sources(eid):
        it, rec, f, sha = _real(eid)
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sha
        pages = _pages(f, rec["source_kind"])
        findings = E.check_candidate(it, rec, pages, source_sha256=sha)
        assert E.blocking(findings) == [], findings

    def test_the_real_faq_candidate_would_have_been_blocked_if_it_kept_the_old_heading():
        it, rec, f, sha = _real("EV-U-61c185ec5771")
        pages = _pages(f, "html")
        stale = deepcopy(it)
        for e in stale["proposed_edits"]:
            e["proposed"] = e["old"]
        assert codes(E.check_candidate(stale, rec, pages, source_sha256=sha)) == ["C-SECTION"]

    def test_the_real_keio_candidate_replaces_a_year_the_page_never_names():
        it, rec, f, sha = _real("EV-U-b9e7fb33158b")
        pages = _pages(f, "html")
        assert "2027" not in unicodedata.normalize("NFKC", pages[0]) and "2027" in rec["applicability"]
        assert codes(E.check_candidate(it, rec, pages, source_sha256=sha), "info") == ["C-YEAR"]
