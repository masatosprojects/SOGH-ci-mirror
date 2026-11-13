"""The forbidden-claim guard must refuse an ASSERTION and must let a DENIAL through: the product has to say 'this is not the real interview' in words that contain the claim's own phrase.
Found while reviewing Work's PR #109 preview: its disclaimer '実際の面接と同じ進行や合格可能性は保証しません' was flagged. SYNTHETIC_ONLY. A denial is allowed only when it negates the claim in the same clause."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import guards  # noqa: E402

ASSERTIONS = [
    "合格できます。", "この練習で合格間違いなしです。", "合格保証つきです。", "合格が確実です。合格確実です。",
    "これは実際の面接と同じ形式です。", "実際の入試そのままの練習です。", "完全に再現しています。", "必ず出題される質問です。", "必ず聞かれる質問を練習します。", "この質問は出題されます。",
    "合格できますが、保証はしません。",  # the comma ends the clause: the first clause still asserts
    "実際の面接と同じです。合否には関係しません。",  # the denial is in another sentence
    "大学公認の対策です。", "合格率80%です。", "再現度95です。",
    "合格率は 80% です。", "合格率が約80％です。", "合格確率はおよそ９割…ではなく80%です。", "合格可能性は 70 です。",  # a particle / 約 between the word and the number (found re-reviewing PR #109)
]
DENIALS = [
    "実際の面接と同じ進行や合格可能性は保証しません。", "実際の面接と同じとは限りません。", "実際の入試そのままではありません。", "完全に再現するものではありません。", "必ず聞かれるとは限りません。",
    "この質問が出題されることを意味しません。", "合格できるとは言えません。合格保証はしません。", "大学公認でもありません。", "合格が確実だと言うことはできません。",
]


@pytest.mark.parametrize("text", ASSERTIONS)
def test_an_assertion_is_still_refused(text):
    assert guards.forbidden_claims_in(text), text


@pytest.mark.parametrize("text", DENIALS)
def test_a_denial_of_the_claim_is_allowed(text):
    assert guards.forbidden_claims_in(text) == [], text


def test_the_sandboxs_own_limits_and_disclaimers_pass_the_guard():
    from interview_sandbox.feedback import LIMITS
    for text in LIMITS:
        guards.assert_clean(text)
