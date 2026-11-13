"""Approval events and the ledger that applies them (docs/PUBLICATION_POLICY.md) — a SPECIFICATION with local mocks, not an implementation.

PROPOSED: no database holds this, and NOTHING here connects to note: `note_draft_id` is just a string a mock hands back. It makes the
policy testable: who may do what, to WHICH version, when, and what a change of content cancels.

Principles
* A STATE says where an article version is. An EVENT says who decided what, when, about which version. The two are checked together.
* An event is bound to one article, one revision hash and one content hash. Nothing carries over to different content.
* The user's decisions (editor check, draft-save authorisation, draft check, final publication approval) must carry a PROOF that only the
  user can make: an HMAC over the event's fields with a key the AI, the QA and the posting process do not hold (its custody is not in this
  repository). An event that names `actor="user"` without a valid proof is refused — a typed name is not an approval.
* A missing time, actor or hash is never filled in: the event is refused.
* Saving a draft and publishing are idempotent: the same version is not saved or published twice; an attempt that started and never
  reported is `unresolved` and blocks a blind retry (it might have created a draft).
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import hmac
import json
from typing import Any, Callable

from src.db_contract import publication as pub

REQUIRED = ("article_id", "revision_hash", "actor", "action", "approved_at", "content_hash", "target_environment", "prior_state", "new_state")
#: new state -> (action name, target environment)
ACTIONS: dict[str, tuple[str, str]] = {
    "qa_passed": ("qa_pass", "local"),
    "editor_confirmed": ("editor_confirm", "local"),
    "draft_save_authorized": ("authorize_draft_save", "note_draft"),
    "note_draft_saved": ("save_note_draft", "note_draft"),
    "note_draft_verified": ("verify_note_draft", "note_draft"),
    "publish_approved": ("approve_publication", "note_public"),
    "published": ("publish", "note_public"),
    "corrected_or_retired": ("correct_or_retire", "note_public"),
}


class Rejected(ValueError):
    """The event was refused. Nothing changed."""


@dataclasses.dataclass(frozen=True)
class ApprovalEvent:
    article_id: str = ""
    revision_hash: str = ""
    actor: str = ""
    action: str = ""
    approved_at: str = ""  # ISO 8601 with a UTC offset
    content_hash: str = ""
    target_environment: str = ""
    prior_state: str = ""
    new_state: str = ""
    note_draft_id: str = ""  # the id the (mock) note returned when the draft was saved
    observed_content_hash: str = ""  # what the user saw in the saved draft (verify_note_draft)
    reason: str = ""
    qa: tuple[tuple[str, Any], ...] = ()  # the QA result for qa_pass: (passed, content_hash, expires_at, registry_version)
    proof: str = ""  # HMAC of the fields, made with the user's key (user events only)

    def fields(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d.pop("proof")
        d["qa"] = [list(x) for x in self.qa]
        return d


def canonical(event: ApprovalEvent) -> bytes:
    return json.dumps(event.fields(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign(event: ApprovalEvent, key: bytes) -> ApprovalEvent:
    """What only the holder of the user's key can do. Automation must never have this key."""
    return dataclasses.replace(event, proof=hmac.new(key, canonical(event), hashlib.sha256).hexdigest())


def proof_is_valid(event: ApprovalEvent, key: bytes) -> bool:
    return bool(event.proof) and hmac.compare_digest(event.proof, hmac.new(key, canonical(event), hashlib.sha256).hexdigest())


def content_hash_of(title: str, body: str, evidence: dict[str, str]) -> str:
    """The hash an approval is bound to: title, body and the evidence versions it cites. Any change gives a different hash."""
    return hashlib.sha256(json.dumps([title, body, sorted(evidence.items())], ensure_ascii=False).encode()).hexdigest()


def idempotency_key(article_id: str, revision_hash: str, content_hash: str, action: str, target: str) -> str:
    return hashlib.sha256("|".join([article_id, revision_hash, content_hash, action, target]).encode()).hexdigest()


def _parse_time(text: str) -> datetime.datetime:
    try:
        when = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        raise Rejected(f"approved_at {text!r} is not a time") from None
    if when.tzinfo is None:
        raise Rejected("approved_at has no UTC offset: a time is never assumed")
    return when


class Ledger:
    """One article VERSION's approval record. `verify_key` is held by the verifier only (never by the generator, the QA or the poster)."""

    def __init__(self, article_id: str, revision_hash: str, content_hash: str, *, verify_key: bytes,
                 now: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.timezone.utc)) -> None:
        self.article_id, self.revision_hash, self.content_hash = article_id, revision_hash, content_hash
        self._key, self._now = verify_key, now
        self.state = "generated"
        self.history: list[ApprovalEvent] = []
        self.note_draft_id = ""
        self.qa_expires_at: datetime.datetime | None = None
        self.done: set[str] = set()  # idempotency keys of the save / publish that succeeded
        self.attempts: list[dict[str, str]] = []
        self.superseded: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ versions
    def new_version(self, revision_hash: str, content_hash: str) -> None:
        """The text, the title or the evidence changed: a NEW version, from `generated`. Nothing carries over."""
        self.superseded.append({"revision_hash": self.revision_hash, "content_hash": self.content_hash, "state": self.state, "events": len(self.history)})
        self.revision_hash, self.content_hash = revision_hash, content_hash
        self.state, self.history, self.note_draft_id, self.qa_expires_at = pub.reset_on_change(self.state), [], "", None
        self.done, self.attempts = set(), []

    # ------------------------------------------------------------------ attempts (a save that may have half-happened)
    def begin_attempt(self, action: str) -> str:
        key = idempotency_key(self.article_id, self.revision_hash, self.content_hash, action, ACTIONS["note_draft_saved" if action == "save_note_draft" else "published"][1])
        if key in self.done:
            raise Rejected(f"{action} was already done for this version: no second one")
        if any(a["action"] == action and a["status"] == "started" for a in self.attempts):
            raise Rejected(f"an earlier {action} started and never reported: it may have created something — reconcile it first, do not retry blindly")
        self.attempts.append({"action": action, "status": "started"})
        return key

    def fail_attempt(self, action: str) -> None:
        for a in reversed(self.attempts):
            if a["action"] == action and a["status"] == "started":
                a["status"] = "failed"
                return
        raise Rejected(f"no {action} attempt is running")

    # ------------------------------------------------------------------ events
    def _verified_before(self, new_state: str) -> bool:
        return any(e.new_state == new_state and e.content_hash == self.content_hash and e.revision_hash == self.revision_hash for e in self.history)

    def apply(self, event: ApprovalEvent) -> ApprovalEvent:
        d = event.fields()
        missing = [f for f in REQUIRED if not d.get(f)]
        if missing:
            raise Rejected(f"missing {missing}: a time, an actor or a hash is never filled in")
        when = _parse_time(event.approved_at)
        if when > self._now() + datetime.timedelta(minutes=5):
            raise Rejected("approved_at is in the future")
        if event.new_state not in ACTIONS or event.action != ACTIONS[event.new_state][0]:
            raise Rejected(f"action {event.action!r} does not belong to the state {event.new_state!r}")
        if event.target_environment != ACTIONS[event.new_state][1]:
            raise Rejected(f"{event.new_state} acts on {ACTIONS[event.new_state][1]!r}, not {event.target_environment!r}")
        if event.article_id != self.article_id:
            raise Rejected("this event is about another article")
        if event.revision_hash != self.revision_hash:
            raise Rejected("this event is about another revision: an approval is never reused for a new version")
        if event.content_hash != self.content_hash:
            raise Rejected("the content changed since this event: the approval no longer applies")
        if event.prior_state != self.state:
            raise Rejected(f"the article is in {self.state!r}, not {event.prior_state!r}")
        if event.actor == "user" and not proof_is_valid(event, self._key):
            raise Rejected("a user event without a valid proof is refused: a name typed into an event is not the user's approval")
        verified: set[str] = set()
        if event.new_state == "note_draft_saved" and self._verified_before("draft_save_authorized"):
            verified.add("draft_authorization_verified")
        if event.new_state == "published" and self._verified_before("publish_approved"):
            verified.add("publish_approval_verified")
        ok, why = pub.can_transition(event.prior_state, event.new_state, event.actor, permissions=frozenset(verified))
        if not ok:
            raise Rejected(why)
        # ---- state-specific rules
        if event.new_state == "qa_passed":
            qa = dict(event.qa)
            if qa.get("passed") is not True or qa.get("content_hash") != self.content_hash:
                raise Rejected("the QA result is not a pass for this content")
            if not qa.get("expires_at"):
                raise Rejected("a QA result without an expiry is not accepted")
            expiry = _parse_time(str(qa["expires_at"]))
            if expiry <= self._now():
                raise Rejected("the QA result has expired")
            self.qa_expires_at = expiry
        if event.new_state == "editor_confirmed" and (self.qa_expires_at is None or self.qa_expires_at <= self._now()):
            raise Rejected("the QA result this confirmation rests on has expired: run the QA again")
        if event.new_state in ("note_draft_saved", "published"):
            key = idempotency_key(self.article_id, self.revision_hash, self.content_hash, event.action, event.target_environment)
            if key in self.done:
                raise Rejected(f"{event.action} was already done for this version")
            if event.new_state == "note_draft_saved" and not event.note_draft_id:
                raise Rejected("the saved draft's id is missing: an unknown draft is not accepted")
            if event.new_state == "published" and (not event.note_draft_id or event.note_draft_id != self.note_draft_id):
                raise Rejected("this is not the draft that was saved and checked")
            if not any(a["action"] == event.action and a["status"] == "started" for a in self.attempts) and event.new_state == "note_draft_saved":
                raise Rejected("an attempt must be begun before a draft is saved (so a crash is visible)")
        if event.new_state == "note_draft_verified":
            if not self.note_draft_id or event.note_draft_id != self.note_draft_id:
                raise Rejected("this is not the saved draft")
            if event.observed_content_hash != self.content_hash:
                raise Rejected("the saved draft does not match the local text: it was not verified")
        if event.new_state == "publish_approved":
            if not self._verified_before("note_draft_verified") or event.note_draft_id != self.note_draft_id:
                raise Rejected("the user has not checked the saved draft: no publication approval")
        if event.new_state == "corrected_or_retired" and event.actor == "poster" and "retire_authorized_by_user" not in verified:
            raise Rejected("only the user retires or corrects; the poster needs a verified authorisation")
        # ---- commit
        if event.new_state == "note_draft_saved":
            self.note_draft_id = event.note_draft_id
            self.done.add(idempotency_key(self.article_id, self.revision_hash, self.content_hash, event.action, event.target_environment))
            next(a for a in reversed(self.attempts) if a["action"] == event.action and a["status"] == "started")["status"] = "succeeded"
        if event.new_state == "published":
            self.done.add(idempotency_key(self.article_id, self.revision_hash, self.content_hash, event.action, event.target_environment))
        self.state = event.new_state
        self.history.append(event)
        return event
