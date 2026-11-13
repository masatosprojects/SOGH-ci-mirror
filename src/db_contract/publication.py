"""The publication states and who may move an article between them (docs/PUBLICATION_POLICY.md) — a SPECIFICATION in code.

PROPOSED, not applied: nothing here is in any database, and nothing here talks to note. Work has not agreed a status table
(docs/DB_SCHEMA_GAP_ANALYSIS.md G-08). It exists so the policy can be tested and so a future implementation has an executable reference.

Decisions it encodes (the user, 2026-11-01):
  * the final editor check, the permission to save a draft, the check of the draft and the final publication approval are the USER's;
  * the private note draft is saved BEFORE the final approval, and the draft is checked before it;
  * automation may generate, run QA and — only after a verified user authorisation — save a draft / publish; it never approves.
A green QA is a state of its own (`qa_passed`) and approves nothing.

Backward compatibility: the seven original state NAMES are unchanged (LEGACY_STATES); two states were added (`draft_save_authorized`,
`note_draft_verified`). The ORDER changed on purpose: the old `editor_confirmed -> publish_approved` and `publish_approved -> note_draft_saved`
are gone (approval now comes after a verified draft).
"""
from __future__ import annotations

LEGACY_STATES = ("generated", "qa_passed", "editor_confirmed", "publish_approved", "note_draft_saved", "published", "corrected_or_retired")
STATES = ("generated", "qa_passed", "editor_confirmed", "draft_save_authorized", "note_draft_saved", "note_draft_verified",
          "publish_approved", "published", "corrected_or_retired")
ACTORS = ("system", "qa", "editor", "user", "poster")  # `poster` = the authorised posting process (Work); never a decision-maker
USER_ONLY_STATES = ("editor_confirmed", "draft_save_authorized", "note_draft_verified", "publish_approved")  # a PERSON's decision: the user's
# who may perform a transition, and which VERIFIED facts (supplied by the ledger after checking signatures) must hold
TRANSITIONS: dict[tuple[str, str], dict[str, object]] = {
    ("generated", "qa_passed"): {"actors": ("qa", "system"), "needs": ()},
    ("qa_passed", "editor_confirmed"): {"actors": ("user", "editor"), "needs": ()},  # `editor` only under an explicit future delegation (see can_transition)
    ("editor_confirmed", "draft_save_authorized"): {"actors": ("user",), "needs": ()},
    ("draft_save_authorized", "note_draft_saved"): {"actors": ("poster",), "needs": ("draft_authorization_verified",)},
    ("note_draft_saved", "note_draft_verified"): {"actors": ("user",), "needs": ()},
    ("note_draft_verified", "publish_approved"): {"actors": ("user",), "needs": ()},
    ("publish_approved", "published"): {"actors": ("poster",), "needs": ("publish_approval_verified",)},
}
RETIRABLE = ("qa_passed", "editor_confirmed", "draft_save_authorized", "note_draft_saved", "note_draft_verified", "publish_approved", "published")


def can_transition(src: str, dst: str, actor: str, *, permissions: frozenset[str] = frozenset(), history: frozenset[str] = frozenset(),
                   delegated_editors: bool = False) -> tuple[bool, str]:
    """(allowed, reason). `permissions`: verified facts such as 'draft_authorization_verified'. `history`: states this article version has been in.
    `delegated_editors`: only a future, explicit delegation lets an editor confirm; the initial operation has the user alone."""
    if src not in STATES or dst not in STATES:
        return False, f"unknown state: {src!r} -> {dst!r}"
    if actor not in ACTORS:
        return False, f"unknown actor {actor!r}"
    if dst in USER_ONLY_STATES and actor != "user" and not (dst == "editor_confirmed" and actor == "editor" and delegated_editors):
        return False, f"{dst} is the user's decision: {actor!r} cannot make it (AI and automation never approve for the user)"
    if dst == "corrected_or_retired":
        if src not in RETIRABLE:
            return False, f"nothing to retire from {src!r}"
        if actor == "user" or (actor == "poster" and "retire_authorized_by_user" in permissions):
            return True, "ok"
        return False, "a correction or retirement is the user's decision (the posting process only executes it after a verified authorisation)"
    rule = TRANSITIONS.get((src, dst))
    if rule is None:
        return False, f"no such transition {src} -> {dst} (a state cannot be skipped)"
    if actor not in rule["actors"]:  # type: ignore[operator]
        return False, f"{actor!r} may not move {src} -> {dst}"
    for need in rule["needs"]:  # type: ignore[union-attr]
        if need not in permissions:
            return False, f"{src} -> {dst} needs {need}"
    return True, "ok"


def reset_on_change(state: str) -> str:
    """Any change to the text, the title or the cited evidence makes a NEW article version: it starts again at `generated`.
    No approval, confirmation, authorisation or QA result carries over to different content."""
    if state not in STATES:
        raise ValueError(state)
    return "generated"
