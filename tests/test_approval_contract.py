"""The approval ledger (src/db_contract/approvals.py): the editing / draft / publication flow the user adopted, tested with local mocks and
synthetic data only. NOTHING here touches note; a note draft id is a string a mock invents. The twenty negative cases are numbered as in the
instruction. Passing these proves the CONTRACT, not a connection to note."""
import dataclasses
import datetime
import itertools

import pytest

from src.db_contract import approvals as ap
from src.db_contract import publication as pub

USER_KEY = b"test-key-held-by-the-verifier-only"
AI_KEY = b"a-key-the-ai-could-have-made-up"
T0 = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.timezone.utc)
CH = ap.content_hash_of("題", "本文[EV-1]", {"EV-1": "v1"})
PRIOR = {"editor_confirmed": "qa_passed", "draft_save_authorized": "editor_confirmed", "note_draft_verified": "note_draft_saved",
         "publish_approved": "note_draft_verified"}
STEPS = [("qa_passed", "qa"), ("editor_confirmed", "user"), ("draft_save_authorized", "user"), ("note_draft_saved", "poster"),
         ("note_draft_verified", "user"), ("publish_approved", "user"), ("published", "poster")]


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def iso(delta_minutes=0):
    return (T0 + datetime.timedelta(minutes=delta_minutes)).isoformat()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ledger(clock):
    return ap.Ledger("art-1", "rev-1", CH, verify_key=USER_KEY, now=clock)


def ev(ledger, new_state, actor, key=USER_KEY, **over):
    action, target = ap.ACTIONS[new_state]
    base = dict(article_id=ledger.article_id, revision_hash=ledger.revision_hash, actor=actor, action=action, approved_at=iso(),
                content_hash=ledger.content_hash, target_environment=target, prior_state=ledger.state, new_state=new_state)
    if new_state == "qa_passed":
        base["qa"] = (("passed", True), ("content_hash", ledger.content_hash), ("expires_at", iso(60)), ("registry_version", "1.7.1"))
    if new_state in ("note_draft_saved", "note_draft_verified", "publish_approved", "published"):
        base["note_draft_id"] = "MOCK-DRAFT-1"
    if new_state == "note_draft_verified":
        base["observed_content_hash"] = ledger.content_hash
    base.update(over)
    event = ap.ApprovalEvent(**base)
    return ap.sign(event, key) if actor == "user" and key is not None else event


def go(ledger, upto):
    """Drive the adopted flow up to (and including) `upto`."""
    for state, actor in STEPS:
        if state == "note_draft_saved":
            ledger.begin_attempt("save_note_draft")
        ledger.apply(ev(ledger, state, actor))
        if state == upto:
            return
    raise AssertionError(upto)


def refused(ledger, event, match=None):
    before = (ledger.state, len(ledger.history))
    with pytest.raises(ap.Rejected, match=match):
        ledger.apply(event)
    assert (ledger.state, len(ledger.history)) == before  # nothing changed


# ------------------------------------------------------------------ the adopted flow works
def test_the_whole_adopted_flow_works_in_order_and_records_every_event(ledger):
    go(ledger, "published")
    assert ledger.state == "published"
    assert [e.new_state for e in ledger.history] == [s for s, _ in STEPS]
    for e in ledger.history:
        assert all(getattr(e, f) for f in ap.REQUIRED) and e.content_hash == CH and e.revision_hash == "rev-1"
    assert [e.actor for e in ledger.history if e.new_state in pub.USER_ONLY_STATES] == ["user"] * 4


def test_the_draft_is_saved_and_checked_before_the_final_approval(ledger):
    go(ledger, "note_draft_verified")
    states = [e.new_state for e in ledger.history]
    assert states.index("note_draft_saved") < states.index("note_draft_verified") and "publish_approved" not in states


# ------------------------------------------------------------------ the twenty negative cases
def test_01_a_qa_failure_cannot_be_confirmed(ledger):
    failed = ev(ledger, "qa_passed", "qa", qa=(("passed", False), ("content_hash", CH), ("expires_at", iso(60))))
    refused(ledger, failed, "not a pass")
    refused(ledger, ev(ledger, "editor_confirmed", "user", prior_state="generated"))  # and not from `generated` either


def test_02_the_draft_cannot_be_authorised_before_the_editor_confirmation(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "draft_save_authorized", "user"))


def test_03_a_note_operation_needs_the_authorisation_event(ledger):
    go(ledger, "editor_confirmed")
    ledger.begin_attempt("save_note_draft")
    refused(ledger, ev(ledger, "note_draft_saved", "poster"))


def test_04_a_publication_approval_needs_a_saved_draft(ledger):
    go(ledger, "draft_save_authorized")
    refused(ledger, ev(ledger, "publish_approved", "user"))


def test_05_a_publication_approval_needs_the_users_check_of_the_draft(ledger):
    go(ledger, "note_draft_saved")
    refused(ledger, ev(ledger, "publish_approved", "user"))


def test_06_nothing_is_published_without_the_final_approval(ledger):
    go(ledger, "note_draft_verified")
    refused(ledger, ev(ledger, "published", "poster"))
    refused(ledger, ev(ledger, "published", "user"))  # it is the approval that makes it publishable, not the user's say-so at the end


def test_07_the_ai_cannot_forge_the_users_approval(ledger):
    go(ledger, "qa_passed")
    unsigned = dataclasses.replace(ev(ledger, "editor_confirmed", "user"), proof="")
    refused(ledger, unsigned, "valid proof")
    refused(ledger, ev(ledger, "editor_confirmed", "user", key=AI_KEY), "valid proof")  # signed with a key that is not the user's
    refused(ledger, dataclasses.replace(ev(ledger, "editor_confirmed", "user"), reason="edited after signing"), "valid proof")
    for actor in ("system", "qa", "poster", "editor"):
        refused(ledger, ev(ledger, "editor_confirmed", actor))  # any other actor name


@pytest.mark.parametrize("state", pub.USER_ONLY_STATES)
def test_07b_each_of_the_four_user_decisions_needs_the_proof(ledger, state):
    for step, actor in STEPS:
        if step == state:
            break
        if step == "note_draft_saved":
            ledger.begin_attempt("save_note_draft")
        ledger.apply(ev(ledger, step, actor))
    assert ledger.state == PRIOR[state]
    refused(ledger, dataclasses.replace(ev(ledger, state, "user"), proof="00" * 32), "valid proof")
    refused(ledger, ev(ledger, state, "user", key=AI_KEY), "valid proof")
    ledger.apply(ev(ledger, state, "user"))
    assert ledger.state == state


def test_08_an_approval_of_another_article_cannot_be_reused(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "editor_confirmed", "user", article_id="art-OTHER"), "another article")


def test_09_an_approval_of_another_revision_cannot_be_reused(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "editor_confirmed", "user", revision_hash="rev-0"), "another revision")


def test_10_a_change_after_approval_cancels_it(ledger):
    go(ledger, "publish_approved")
    approval = ledger.history[-1]
    ledger.new_version("rev-2", ap.content_hash_of("題（変更）", "本文[EV-1]", {"EV-1": "v1"}))  # the title changed
    assert ledger.state == "generated" and ledger.history == []
    refused(ledger, approval)
    refused(ledger, ev(ledger, "published", "poster", revision_hash="rev-1", content_hash=CH, prior_state="publish_approved"))
    assert len({CH, ap.content_hash_of("題", "本文（変更）[EV-1]", {"EV-1": "v1"}), ap.content_hash_of("題", "本文[EV-1]", {"EV-1": "v2"}),
                ap.content_hash_of("題（変更）", "本文[EV-1]", {"EV-1": "v1"})}) == 4  # title, body and evidence version each change the hash


def test_10b_an_event_made_for_the_old_content_does_not_apply_to_the_new(ledger):
    go(ledger, "qa_passed")
    stale = ev(ledger, "editor_confirmed", "user")
    ledger.new_version("rev-2", ap.content_hash_of("題", "別の本文", {"EV-1": "v1"}))
    refused(ledger, stale)


def test_10c_the_same_revision_hash_with_changed_content_is_also_refused(ledger):
    go(ledger, "qa_passed")
    stale = ev(ledger, "editor_confirmed", "user")
    ledger.content_hash = ap.content_hash_of("題", "revision hash を変えずに本文だけ変えた", {"EV-1": "v1"})
    refused(ledger, stale, "content changed")


def test_11_a_failure_in_the_middle_of_saving_leaves_the_authorisation_and_allows_one_retry(ledger):
    go(ledger, "draft_save_authorized")
    ledger.begin_attempt("save_note_draft")
    ledger.fail_attempt("save_note_draft")  # the save reported its failure: nothing was created
    assert ledger.state == "draft_save_authorized" and not ledger.note_draft_id
    ledger.begin_attempt("save_note_draft")  # retry
    ledger.apply(ev(ledger, "note_draft_saved", "poster"))
    assert ledger.state == "note_draft_saved"


def test_11b_a_save_that_never_reported_blocks_a_blind_retry(ledger):
    go(ledger, "draft_save_authorized")
    ledger.begin_attempt("save_note_draft")  # crash: no result, no failure
    with pytest.raises(ap.Rejected, match="never reported"):
        ledger.begin_attempt("save_note_draft")  # it might have created a draft
    assert ledger.state == "draft_save_authorized"


def test_11c_a_draft_cannot_be_recorded_without_an_attempt(ledger):
    go(ledger, "draft_save_authorized")
    refused(ledger, ev(ledger, "note_draft_saved", "poster"), "attempt must be begun")


def test_12_saving_the_draft_twice_is_refused(ledger):
    go(ledger, "note_draft_saved")
    with pytest.raises(ap.Rejected, match="already done"):
        ledger.begin_attempt("save_note_draft")
    refused(ledger, ev(ledger, "note_draft_saved", "poster", prior_state="draft_save_authorized"))


def test_13_publishing_twice_is_refused(ledger):
    go(ledger, "published")
    with pytest.raises(ap.Rejected, match="already done"):
        ledger.begin_attempt("publish")
    refused(ledger, ev(ledger, "published", "poster"))


def test_14_a_saved_draft_that_differs_from_the_local_text_is_not_verified(ledger):
    go(ledger, "note_draft_saved")
    refused(ledger, ev(ledger, "note_draft_verified", "user", observed_content_hash=ap.content_hash_of("題", "note 上で変わった本文", {"EV-1": "v1"})), "does not match")
    refused(ledger, ev(ledger, "note_draft_verified", "user", observed_content_hash=""))  # nothing observed: nothing verified


def test_15_an_unknown_draft_id_is_refused_everywhere(ledger):
    go(ledger, "draft_save_authorized")
    ledger.begin_attempt("save_note_draft")
    refused(ledger, ev(ledger, "note_draft_saved", "poster", note_draft_id=""), "id is missing")
    ledger.apply(ev(ledger, "note_draft_saved", "poster"))
    refused(ledger, ev(ledger, "note_draft_verified", "user", note_draft_id="MOCK-DRAFT-OTHER"), "not the saved draft")
    ledger.apply(ev(ledger, "note_draft_verified", "user"))
    refused(ledger, ev(ledger, "publish_approved", "user", note_draft_id="MOCK-DRAFT-OTHER"), "has not checked")
    ledger.apply(ev(ledger, "publish_approved", "user"))
    refused(ledger, ev(ledger, "published", "poster", note_draft_id="MOCK-DRAFT-OTHER"), "not the draft")


def test_16_a_published_article_cannot_be_posted_again(ledger):
    go(ledger, "published")
    for state, actor in (("note_draft_saved", "poster"), ("draft_save_authorized", "user"), ("published", "poster"), ("qa_passed", "qa")):
        refused(ledger, ev(ledger, state, actor))


def test_17_a_correction_cannot_reuse_the_approvals_of_the_old_version(ledger):
    go(ledger, "published")
    old = list(ledger.history)
    ledger.new_version("rev-corrected", ap.content_hash_of("題", "訂正した本文[EV-1]", {"EV-1": "v2"}))
    assert ledger.state == "generated" and ledger.history == [] and ledger.superseded[0]["state"] == "published"
    for e in old:
        refused(ledger, e)
    go(ledger, "published")  # the correction goes through every step again
    assert [e.revision_hash for e in ledger.history] == ["rev-corrected"] * 7


@pytest.mark.parametrize("missing", ap.REQUIRED)
def test_18_an_event_with_a_missing_field_is_refused_never_filled_in(ledger, missing):
    go(ledger, "qa_passed")
    event = ap.sign(dataclasses.replace(ev(ledger, "editor_confirmed", "user"), **{missing: ""}), USER_KEY)
    refused(ledger, event, "missing")


def test_18b_a_time_without_an_offset_or_in_the_future_or_not_a_time_is_refused(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "editor_confirmed", "user", approved_at="2026-11-01T12:00:00"), "no UTC offset")
    refused(ledger, ev(ledger, "editor_confirmed", "user", approved_at="yesterday"), "not a time")
    refused(ledger, ev(ledger, "editor_confirmed", "user", approved_at=iso(600)), "future")


def test_19_an_expired_qa_result_cannot_support_a_confirmation(ledger, clock):
    go(ledger, "qa_passed")
    clock.t = T0 + datetime.timedelta(minutes=61)
    refused(ledger, ev(ledger, "editor_confirmed", "user", approved_at=clock.t.isoformat()), "expired")


def test_19b_a_qa_result_already_expired_without_expiry_or_for_other_content_is_not_accepted(ledger):
    base = dict(passed=True, content_hash=CH, expires_at=iso(-5), registry_version="1.7.1")
    refused(ledger, ev(ledger, "qa_passed", "qa", qa=tuple(base.items())), "expired")
    refused(ledger, ev(ledger, "qa_passed", "qa", qa=tuple({**base, "expires_at": ""}.items())), "expiry")
    refused(ledger, ev(ledger, "qa_passed", "qa", qa=tuple({**base, "expires_at": iso(60), "content_hash": "other"}.items())), "not a pass for this content")


def test_20_every_transition_that_is_not_in_the_matrix_is_refused():
    allowed = set(pub.TRANSITIONS)
    verified = frozenset({"draft_authorization_verified", "publish_approval_verified"})
    for src, dst in itertools.product(pub.STATES, repeat=2):
        for actor in pub.ACTORS:
            ok, _ = pub.can_transition(src, dst, actor, permissions=verified)
            if (src, dst) not in allowed and dst != "corrected_or_retired":
                assert not ok, (src, dst, actor)


# ------------------------------------------------------------------ the rest of the contract
def test_an_editor_cannot_confirm_in_the_initial_operation(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ap.sign(ev(ledger, "editor_confirmed", "editor"), USER_KEY))


def test_the_action_and_the_environment_must_match_the_state(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "editor_confirmed", "user", action="approve_publication"), "does not belong")
    refused(ledger, ev(ledger, "editor_confirmed", "user", target_environment="note_public"), "acts on")


def test_the_event_must_start_from_the_current_state(ledger):
    go(ledger, "qa_passed")
    refused(ledger, ev(ledger, "editor_confirmed", "user", prior_state="generated"), "not 'generated'")


def test_retirement_is_the_users_decision_and_the_poster_alone_cannot_do_it(ledger):
    go(ledger, "published")
    refused(ledger, ev(ledger, "corrected_or_retired", "poster"))
    ledger.apply(ev(ledger, "corrected_or_retired", "user"))
    assert ledger.state == "corrected_or_retired"


def test_the_idempotency_key_depends_on_the_version_the_action_and_the_target():
    a = ap.idempotency_key("art-1", "rev-1", CH, "save_note_draft", "note_draft")
    assert a == ap.idempotency_key("art-1", "rev-1", CH, "save_note_draft", "note_draft")
    assert len({a, ap.idempotency_key("art-2", "rev-1", CH, "save_note_draft", "note_draft"), ap.idempotency_key("art-1", "rev-2", CH, "save_note_draft", "note_draft"),
                ap.idempotency_key("art-1", "rev-1", "x", "save_note_draft", "note_draft"), ap.idempotency_key("art-1", "rev-1", CH, "publish", "note_public")}) == 5


def test_nothing_in_the_contract_can_reach_note():
    import inspect
    source = inspect.getsource(ap) + inspect.getsource(pub)
    for forbidden in ("import requests", "import urllib", "playwright", "selenium", "httpx", "import socket", "subprocess"):
        assert forbidden not in source, forbidden
