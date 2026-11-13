"""Personal information typed into an answer must not come back out of the sandbox: not in the stored text, not in a follow-up question, not in the feedback, not in a notice.
SYNTHETIC_ONLY (every value is invented). The first probe found that only ASCII e-mail addresses and hyphen/space phone numbers were masked: full-width '＠' and digits, '(at)', '+81',
links and account names, and postal codes were stored unmasked and quoted back in the feedback. Names and street addresses are NOT detected (a school name such as 大阪府立大学 must stay
readable); that limit is stated in sandbox/README.md and in the notice shown to the person."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from evaluation.clarity_cases import run_answers  # noqa: E402
from interview_sandbox import guards  # noqa: E402

# (label, text containing personal data, the fragments that must not survive)
LEAKS = [
    ("email_ascii", "連絡先は taro.yamada@example.com です。", ["taro", "example.com"]),
    ("email_fullwidth_at", "連絡先は taro.yamada＠example.com です。", ["taro", "example.com"]),
    ("email_spelled_at", "連絡先は taro.yamada (at) example.com です。", ["taro", "example.com"]),
    ("email_fullwidth_letters", "連絡先は ｔａｒｏ＠example.com です。", ["ｔａｒｏ", "example.com"]),
    ("phone_hyphen", "電話は090-1234-5678です。", ["090", "1234", "5678"]),
    ("phone_plain", "電話は09012345678です。", ["09012345678"]),
    ("phone_spaces", "電話は090 1234 5678です。", ["1234", "5678"]),
    ("phone_fullwidth", "電話は０９０－１２３４－５６７８です。", ["０９０", "１２３４", "５６７８"]),
    ("phone_international", "電話は+81 90 1234 5678です。", ["1234", "5678"]),
    ("phone_international_fullwidth", "電話は＋８１ ９０ １２３４ ５６７８です。", ["１２３４", "５６７８"]),
    ("link", "SNSは https://twitter.com/taro_y です。", ["twitter", "taro_y"]),
    ("link_www", "ページは www.example.org/me です。", ["example.org"]),
    ("account_name", "アカウントは @taro_y です。", ["taro_y"]),
    ("account_name_fullwidth", "アカウントは ＠taro_y です。", ["taro_y"]),
    ("postal_code", "住所は〒100-0001です。", ["100-0001"]),
    ("postal_code_fullwidth", "住所は〒１００－０００１です。", ["１００－０００１"]),
]
FILLER = "私は部活で研究に取り組みました。"


@pytest.mark.parametrize("label,text,fragments", LEAKS, ids=[x[0] for x in LEAKS])
def test_personal_information_never_comes_back_in_any_output(label, text, fragments):
    answer = text + FILLER
    session, feedback = run_answers((answer, "調査を担当しました。"))
    stored = session.candidate_turns()[0].text
    emitted = {"stored answer": stored, "follow-up": " ".join(t.text for t in session.turns if t.role == "interviewer"),
               "feedback": feedback.text(), "notices": " ".join(n.text for n in session.notices)}
    for where, out in emitted.items():
        for fragment in fragments:
            assert fragment not in out, f"{label}: {fragment!r} survived in the {where}"
    assert "personal_info_masked" in {n.code for n in session.notices}
    assert guards.has_personal(answer) and not guards.has_personal(stored)  # what is stored no longer looks like personal information


@pytest.mark.parametrize("text", [
    "令和9年度の募集人員は5名で、第1次選考は10月1日です。",
    "2026-10-27 までに到着する必要があります。",
    "大阪府立大学と京都府立大学のオープンキャンパスに参加しました。",
    "研究では50人にアンケートを行い、回収率は0.8でした。",
    "年収1000万円の家庭という話は聞いていません。",
    "探究活動は週3回、1回あたり90分でした。",
    "私は2027年4月に入学したいです。",
    "https が使われている理由を調べました。",
    "A@B のような記号の書き方を学びました。",
])
def test_ordinary_numbers_dates_and_school_names_are_not_masked(text):
    assert guards.mask_personal(text) == text and not guards.has_personal(text)


def test_names_and_street_addresses_are_not_detected_and_that_limit_is_stated():
    """Documented limit: a name or a street address cannot be told from ordinary text without false alarms (a university's name, a school's name). The screen and the notice tell people not to enter them."""
    text = "山田太郎と申します。東京都千代田区千代田1-1に住んでいます。"
    assert guards.mask_personal(text) == text
    readme = (ROOT / "sandbox" / "README.md").read_text(encoding="utf-8")
    assert "氏名" in readme and "住所" in readme and "自動では" in readme
    from interview_sandbox.engine import InterviewSession  # the notice text names the same limit
    import inspect
    assert "氏名や住所は自動では伏せられない" in inspect.getsource(InterviewSession)


def test_masking_is_idempotent_and_keeps_the_rest_of_the_answer():
    text = "連絡先 taro@example.com と 090-1234-5678、https://example.com/x、〒100-0001、@taro_y です。私は研究をしました。"
    once = guards.mask_personal(text)
    assert once == "連絡先 [メール] と [電話番号]、[リンク]、[郵便番号]、[アカウント名] です。私は研究をしました。"
    assert guards.mask_personal(once) == once
