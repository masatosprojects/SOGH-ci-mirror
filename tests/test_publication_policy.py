"""docs/PUBLICATION_POLICY.md as an executable specification: the state matrix (PROPOSED: nothing is stored in any database, no note access)."""
from pathlib import Path

import pytest

from src.db_contract import publication as pub

POLICY = (Path(__file__).resolve().parents[1] / "docs" / "PUBLICATION_POLICY.md").read_text(encoding="utf-8")
ok = pub.can_transition
FLOW = [("generated", "qa_passed", "qa"), ("qa_passed", "editor_confirmed", "user"), ("editor_confirmed", "draft_save_authorized", "user"),
        ("draft_save_authorized", "note_draft_saved", "poster"), ("note_draft_saved", "note_draft_verified", "user"),
        ("note_draft_verified", "publish_approved", "user"), ("publish_approved", "published", "poster")]
VERIFIED = {"note_draft_saved": frozenset({"draft_authorization_verified"}), "published": frozenset({"publish_approval_verified"})}


def test_the_nine_states_are_distinct_and_all_in_the_policy_document():
    assert len(pub.STATES) == len(set(pub.STATES)) == 9
    for state in pub.STATES:
        assert f"`{state}`" in POLICY, state


def test_the_seven_original_state_names_are_kept():
    assert set(pub.LEGACY_STATES) <= set(pub.STATES) and len(pub.LEGACY_STATES) == 7


def test_the_adopted_order_is_the_only_forward_path():
    for src, dst, actor in FLOW:
        assert ok(src, dst, actor, permissions=VERIFIED.get(dst, frozenset()))[0], (src, dst)
    forward = {(a, b) for a, b in pub.TRANSITIONS}
    assert forward == {(s, d) for s, d, _ in FLOW}


def test_a_passing_qa_approves_nothing():
    for dst in pub.STATES:
        if dst not in ("qa_passed",):
            for actor in ("qa", "system"):
                assert not ok("qa_passed", dst, actor, permissions=VERIFIED.get(dst, frozenset()))[0], (dst, actor)


@pytest.mark.parametrize("state", pub.USER_ONLY_STATES)
def test_the_four_decisions_are_the_users_alone(state):
    prior = {"editor_confirmed": "qa_passed", "draft_save_authorized": "editor_confirmed", "note_draft_verified": "note_draft_saved", "publish_approved": "note_draft_verified"}[state]
    assert ok(prior, state, "user")[0]
    for actor in ("system", "qa", "editor", "poster"):
        assert not ok(prior, state, actor)[0], (state, actor)


def test_an_editor_may_confirm_only_after_an_explicit_future_delegation():
    assert not ok("qa_passed", "editor_confirmed", "editor")[0]
    assert ok("qa_passed", "editor_confirmed", "editor", delegated_editors=True)[0]
    assert not ok("editor_confirmed", "draft_save_authorized", "editor", delegated_editors=True)[0]  # a delegation covers the confirmation only
    assert not ok("note_draft_verified", "publish_approved", "editor", delegated_editors=True)[0]


def test_the_poster_acts_only_with_a_verified_authorisation():
    assert not ok("draft_save_authorized", "note_draft_saved", "poster")[0]
    assert ok("draft_save_authorized", "note_draft_saved", "poster", permissions=VERIFIED["note_draft_saved"])[0]
    assert not ok("publish_approved", "published", "poster")[0]
    assert ok("publish_approved", "published", "poster", permissions=VERIFIED["published"])[0]


def test_automation_other_than_the_authorised_poster_never_publishes_or_saves():
    everything = frozenset({"draft_authorization_verified", "publish_approval_verified", "retire_authorized_by_user"})
    for src in pub.STATES:
        for actor in ("system", "qa", "editor"):
            for dst in ("published", "note_draft_saved", "publish_approved"):
                assert not ok(src, dst, actor, permissions=everything)[0], (src, dst, actor)


def test_the_old_orders_are_gone_the_draft_comes_before_the_approval():
    assert not ok("editor_confirmed", "publish_approved", "user")[0]
    assert not ok("publish_approved", "note_draft_saved", "user")[0]
    assert not ok("note_draft_saved", "publish_approved", "user")[0]  # the draft must be checked first
    assert not ok("note_draft_saved", "published", "poster", permissions=VERIFIED["published"])[0]


def test_no_state_can_be_skipped():
    for src, dst in [("generated", "editor_confirmed"), ("qa_passed", "draft_save_authorized"), ("editor_confirmed", "note_draft_saved"),
                     ("draft_save_authorized", "note_draft_verified"), ("note_draft_saved", "publish_approved"), ("note_draft_verified", "published")]:
        for actor in pub.ACTORS:
            assert not ok(src, dst, actor, permissions=frozenset({"draft_authorization_verified", "publish_approval_verified"}), delegated_editors=True)[0], (src, dst, actor)


def test_correction_and_retirement_are_the_users_decision_and_not_from_generated():
    for src in pub.RETIRABLE:
        assert ok(src, "corrected_or_retired", "user")[0]
        assert not ok(src, "corrected_or_retired", "system")[0] and not ok(src, "corrected_or_retired", "editor")[0]
        assert not ok(src, "corrected_or_retired", "poster")[0]
        assert ok(src, "corrected_or_retired", "poster", permissions=frozenset({"retire_authorized_by_user"}))[0]
    assert not ok("generated", "corrected_or_retired", "user")[0]


def test_unknown_states_and_actors_are_refused():
    assert not ok("nonsense", "qa_passed", "qa")[0] and not ok("generated", "qa_passed", "robot")[0]


@pytest.mark.parametrize("state", pub.STATES)
def test_a_change_of_content_starts_a_new_version_at_generated(state):
    assert pub.reset_on_change(state) == "generated"
    with pytest.raises(ValueError):
        pub.reset_on_change("unknown")


def test_the_policy_document_states_the_adopted_flow_and_the_decisions():
    for needle in ("初期運用", "ユーザー本人", "下書き保存", "公開承認", "QA合格は公開承認ではありません", "自動公開", "当面禁止", "note_draft_verified", "draft_save_authorized"):
        assert needle in POLICY, needle
