"""Behaviour of the STR-101 (H3=B) scope-evidence guard (inside the second patch, patches/g2-faq/work-faq-g2-unconfirmed-section.patch): binding a FAQ page to ONE year / faculty / method needs an INDEPENDENT official
evidence (an evidence id and the SHA-256 of a source other than the FAQ page, with the quote that states the year and the faculty); a missing, self-referencing, inconsistent or unsupported evidence is an error and
nothing is bound. The D03 finding it answers: removing `scope_status` from a spec used to rebind the same page to the 2027 cycle (a property of the CONFIGURATION, not of the page).
Run by tests/test_g2_unconfirmed_patch.py inside a COPY of Work's pipeline that carries BOTH patches, with tests/behaviour_g2_faq.py as fixtures. SELF_TEST; synthetic FAQ page only."""
import copy

import pytest

from admissions_pipeline.faq_policy import extract_conditions, structured_record
from admissions_pipeline.scope_evidence import check_scope_evidence
from test_behaviour_g2_faq import CASE, CYCLE, SCOPE_EVIDENCE, spec_for, world  # noqa: F401  (world is a fixture)


def bound(world, **ev):
    record, sha, _ = world
    spec = spec_for(sha, unknown=False)
    spec["scope_evidence"] = {**copy.deepcopy(SCOPE_EVIDENCE), **ev}
    return record, spec


def test_a_binding_with_an_independent_official_evidence_is_accepted(world):
    record, spec = bound(world)
    rec = structured_record(extract_conditions(record, spec, copy.deepcopy(CYCLE)), None, "fixture-g2")
    assert rec["case_id"] == CASE


def test_removing_scope_status_does_not_rebind_the_page_to_the_2027_cycle_any_more(world):
    record, sha, _ = world
    spec = spec_for(sha, unknown=True)
    spec.pop("scope_status"); spec.pop("section_headings"); spec["case_id"] = CASE; spec["fiscal_year"] = 2027  # the D03 probe q1_04: a configuration edit, no evidence
    with pytest.raises(ValueError, match="not proven"):
        extract_conditions(record, spec, copy.deepcopy(CYCLE))


def test_a_binding_without_scope_evidence_is_refused(world):
    record, sha, _ = world
    spec = spec_for(sha, unknown=False)
    spec.pop("scope_evidence")
    with pytest.raises(ValueError, match="not proven"):
        extract_conditions(record, spec, copy.deepcopy(CYCLE))


@pytest.mark.parametrize("over, match", [
    (dict(source_sha256="zz"), "SHA-256"),
    (dict(evidence_id=" "), "evidence id"),
    (dict(fiscal_year=2028), "consistent"),
    (dict(case_id="other-case"), "consistent"),
    (dict(faculty="人文学群"), "another faculty"),
    (dict(quote="令和9年度 アドミッションセンター入試 学生募集要項"), "year and the faculty"),
    (dict(quote="知識情報・図書館学類 学生募集要項"), "year and the faculty"),
])
def test_an_inconsistent_or_unsupported_evidence_is_refused(world, over, match):
    record, spec = bound(world, **over)
    with pytest.raises(ValueError, match=match):
        extract_conditions(record, spec, copy.deepcopy(CYCLE))


def test_the_faq_page_itself_is_not_an_independent_source(world):
    record, sha, _ = world
    record, spec = bound(world, source_sha256=sha)  # the page's own SHA
    with pytest.raises(ValueError, match="not independent"):
        extract_conditions(record, spec, copy.deepcopy(CYCLE))


def test_with_a_store_lookup_the_evidence_must_be_registered_with_the_same_source_and_quote(world):
    record, spec = bound(world)
    ok = {"source_sha256": SCOPE_EVIDENCE["source_sha256"], "text": SCOPE_EVIDENCE["quote"] + " その他の本文"}
    assert check_scope_evidence(spec, record, CYCLE, lambda eid: ok)["store_checked"] is True
    for found in (None, dict(ok, source_sha256="f" * 64), dict(ok, text="別の本文")):
        with pytest.raises(ValueError, match="not registered"):
            check_scope_evidence(spec, record, CYCLE, lambda eid, f=found: f)


def test_an_unknown_scope_page_never_needs_nor_gets_an_evidence(world):
    record, sha, _ = world
    rec = structured_record(extract_conditions(record, spec_for(sha, unknown=True), None), None, "fixture-g2")
    assert rec["case_id"] is None and rec["scope_status"] == "unknown"
