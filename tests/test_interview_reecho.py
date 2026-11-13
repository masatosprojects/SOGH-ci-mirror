"""SELF_TEST (Claude, the author): nothing the person typed that looks like a SECRET, and nothing they said about the university that is not a verified official fact, is repeated back to them - not in a
follow-up question, not in the feedback (evidence, examples), not in a retry - while ordinary quotes of their own words are kept.  SYNTHETIC_ONLY (every "secret" below is an invented, obviously fake value),
deterministic, no network.  NOT an independent QA: Work's independent QA of PR #254 (issue comments 6714059321 / 6714212287) found the two failures this file is written against; the re-test belongs to someone else.

Work's two findings (7 PASS / 2 FAIL at 041e7cc and again at db2e7fd): a synthetic key-shaped string ("sk-" + words) and an unverified quota ("募集人員は987人です") were quoted in the follow-up.  The profile side
already refused official wording (PR #251); the answer side did not.  The causes and the fixes:
  * guards.mask_personal knew e-mail / link / account / postal code / phone, but no secret shapes  -> _SECRET patterns, masked at input (so the stored answer, the follow-up and the feedback all see the placeholder);
  * engine.analysable (which feeds the follow-up AND the feedback evidence) excluded sensitive sentences only  -> it also excludes a sentence that states an unverified official fact (guards.official_claim_in, shared with the profile).
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.dont_write_bytecode = True

from interview_sandbox import InterviewSession, compare_text, get_case, guards  # noqa: E402
from interview_sandbox import profile as prof  # noqa: E402

PLAIN = "図書館の活動で本の紹介を担当しました。"


def play(first_answer, *, case="fiction-ac-1", profile=None, more=("掲示を作り直しました。", "情報の探し方を学びたいです。")):
    s = InterviewSession(get_case(case), profile=profile)
    q = s.start()
    r = s.answer(q.turn_id, first_answer, 10)
    turn = r.next_turn
    for a in more:
        if turn is None or s.state != "in_progress":
            break
        turn = s.answer(turn.turn_id, a, 10).next_turn
    if s.state != "ended":
        s.end("user")
    return s, r


def shown(s):
    """Everything the practising person is shown EXCEPT their own typed turns: the interviewer's questions, the briefing, the whole feedback, its repr, the notices."""
    report = s.feedback()
    parts = [t.text for t in s.turns if t.role == "interviewer"] + [s.briefing().text(), report.text(), repr(report)] + [n.text for n in s.notices]
    return "\n".join(parts)


def shown_with_retry(s):
    report = s.feedback()
    again = s.retry(report)
    again.start()
    out = [shown(s), again.briefing().text(), compare_text(report, report, report.items[0])]
    return "\n".join(out) + "\n" + "\n".join(t.text for t in again.turns)


SECRETS = [
    "sk-FAKE-EXAMPLE-TEST",                                   # Work's value
    "sk-proj-FAKEFAKEFAKE1234",
    "pk_test_FAKE0123456789",
    "AKIAFAKEFAKEFAKE0123",
    "ghp_FAKEFAKEFAKEFAKEFAKEFAKE0123456789",
    "github_pat_FAKEFAKEFAKEFAKEFAKE_0123",
    "xoxb-0000-FAKE-FAKEFAKE",
    "eyJFAKEFAKE0.eyJFAKEFAKE1.FAKESIG0",
    "api_key=FAKE0123abcd",
    "password: FAKEpass0123",
    "パスワード：FAKEpass0123",
    "token = FAKEtoken0123",
    "-----BEGIN RSA PRIVATE KEY-----",
    "sk‐FAKE‐EXAMPLE‐TEST",                    # Unicode hyphens instead of "-"
    "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0",               # a long unbroken token
    # found by Work's independent QA of #260 (6 FAIL at 782427c): other ways of writing the same secret
    "ｓｋ－ＦＩＣＴＩＯＮＡＬ",                                  # full-width letters and hyphen
    "ｓｋ-ＦＩＣＴＩＯＮＡＬ０１２３",
    "SK-FICTIONAL-DUMMY", "Sk-FICTIONAL-DUMMY",               # upper / mixed case prefix
    "s k - FICTIONAL-DUMMY", "s　k‐FICTIONAL-DUMMY",  # split prefix
    "s​k-FICTIONAL-DUMMY",                               # zero-width character inside
    "Bearer FictionalAuthToken", "bearer fictionalAuth0token", "BEARER ABCDEF123456",
    "ＡＫＩＡＦＡＫＥＦＡＫＥＦＡＫＥ０１２３",                 # full-width AWS key id
    # found by Work's independent re-QA of #260 at a04870e (3 PASS / 5 FAIL)
    "s\t\tk - FICTIONAL-ALPHA", "s \t k_FICTIONAL-ALPHA",     # prefix split by tabs / mixed blanks
    "エスケー-FICTIONAL-ALPHA", "ピーケー_FICTIONAL0123", "アールケイ-FICTIONAL-ALPHA",   # the prefix spelled in katakana
]


@pytest.mark.parametrize("secret", SECRETS)
@pytest.mark.parametrize("form", ["{s} を利用しました。", "活動に参加しました。私は担当でした。メモには {s} と書きました。", "{s}\n図書館の活動で案内を作りました。"])
def test_R1_a_secret_shaped_string_is_never_repeated_anywhere_and_the_person_is_told(secret, form):
    s, r = play(form.format(s=secret))
    core = secret.split(": ")[-1].split("：")[-1].split("= ")[-1].split("=")[-1]
    out = shown_with_retry(s)
    assert secret not in out and core not in out
    tail = secret.split()[-1]                                             # the token after "Bearer " / "s k - " / "password: "
    assert "-----" in tail or len(tail) < 9 or tail not in out
    assert core not in " ".join(t.text for t in s.turns)                  # not even in the stored copy of the answer: it was masked at input
    assert "personal_info_masked" in [n.code for n in r.notices]
    assert guards.SECRET_PLACEHOLDER in " ".join(t.text for t in s.turns if t.role == "candidate")


QUOTA_CLAIMS = [
    "募集人員は987人です", "募集人数は50人と聞きました", "募集定員は30名だそうです", "入学定員は100名です", "倍率は3倍だと思います", "競争率が高く5倍くらいです", "志願者数は200人でした",
    "出願期間は11月1日からです", "締切は12月です", "締め切りは来週です", "受験料は17000円です", "面接は10分です", "面接時間は15分程度です", "選考の日程は11月3日です", "入試は2月に行われます",
    "公式発表では枠が増えました", "募集要項に書いてありました", "合格最低点は60点です", "試験日は1月です",
    # found by Work's independent QA of #260: the same kind of statement in other words (kanji numerals)
    "大学が受け入れるのは九百八十七名です", "願書は十一月九日まで受け付けます", "学部の合格者は三十名ほどだと聞きました", "出願の期限は十二月五日です", "この学類の選考では百二十人が選ばれるそうです",
    "大学が入学者として受け入れる人数は50名です",
    # found by Work's independent re-QA of #260 at a04870e: other nouns for the same quota / deadline, circled digits
    "この学部が迎える新入生は七十七名です", "願書は⑪月⑨日まで受け付けます", "大学の新入生は毎年百名だそうです", "学類の入学者は例年六十名と聞きました", "出願の締切は⑫月⑤日です", "大学の枠は二十名と聞きました", "願書は郵送で、十一月十日必着です",
]


@pytest.mark.parametrize("claim", QUOTA_CLAIMS)
@pytest.mark.parametrize("form", ["{c}。", "{c}。私は図書館の活動で案内を作りました。", "図書館の活動で案内を作りました。{c}。"])
def test_R2_an_unverified_statement_about_the_university_is_not_repeated_and_the_ordinary_part_still_is(claim, form):
    s, r = play(form.format(c=claim))
    out = shown_with_retry(s)
    assert claim not in out
    key = claim.replace("です", "").replace("だそうです", "")
    assert key not in out                                                       # not as a shortened quote either
    assert "official_claim_not_repeated" in [n.code for n in r.notices]
    if "案内を作りました" in form:
        asked = " ".join(t.text for t in s.turns if t.role == "interviewer" and t.origin == "follow_up_to_the_answer") + s.feedback().text()
        assert "図書館の活動で案内を作りました" in asked or "私は図書館の活動で案内を作りました" in asked    # the ordinary sentence next to it is still quoted: nothing is erased that need not be


NORMAL = [
    "公式戦に出場して、チームの記録係を務めました。", "部員を30人集めて新入生の歓迎会を開きました。", "ボランティアを募集して30人が集まりました。", "定期試験で90点を取るために毎日勉強しました。",
    "入試に向けて3か月、図書館で勉強しました。", "面接の練習を週3回しました。", "秘密鍵は大事だと学びました。", "トークンの仕組みを調べて発表しました。", "ask-me-anything という企画を開きました。",
    "大学のオープンキャンパスに3回参加しました。", "大学の先生と30分話しました。", "大学の見学で3人の先生に会いました。", "大学のサークルで新入生を募集して30人集めました。", "大学の入試説明会に友達と3人で参加しました。",
    "塾の合格者報告会で30人の先輩が話してくれました。", "志望校を3つに絞りました。",
    # Work's independent re-QA of #260 at a04870e: the person's own experience that mentions the university and a number (one of them was wrongly removed)
    "大学の見学で先生三人に質問しました。", "大学出願の準備で参考書を三冊読みました。", "大学出願の準備を三か月続けました。", "大学主催の選考で私は三人を支援しました。",
    "大学の新入生歓迎会を手伝って三人を案内しました。", "新入生を迎える係として三人を案内しました。", "出願の準備に三日かけました。", "大学の合格者報告会に三人の先輩が来ました。", "十一月に出願する予定です。", "出願を十一月九日に済ませました。", "塾の新入生は三十名でした。", "選考に残るために毎日3時間勉強しました。", "出願のために先生と3回面談しました。", "大学の授業を二回見学して研究の面白さを知りました。", "学部の先輩に三人話を聞きました。",
    "Bearer という英単語を辞書で調べました。", "skate-park の清掃活動を担当しました。", "ask-me-anything-session の運営をしました。", "sk という略称の意味を調べました。",
    "disk-based の記録を整理しました。", "state-of-the-art-information-retrieval-evaluation-methods の論文を読みました。", "task-force の担当として会議を進めました。", "パスワードの管理について調べました。",
]


@pytest.mark.parametrize("sentence", NORMAL)
def test_R3_ordinary_experience_is_not_erased_or_masked(sentence):
    s, r = play(sentence)
    assert guards.mask_personal(sentence) == sentence and not guards.official_claim_in(sentence) and not guards.has_personal(sentence)
    assert [t.text for t in s.turns if t.role == "candidate"][0] == sentence                  # stored exactly as typed
    assert not {"personal_info_masked", "official_claim_not_repeated"} & {n.code for n in r.notices}
    assert guards.SECRET_PLACEHOLDER not in shown(s)
    assert any(x.evidence and sentence.rstrip("。")[:20] in x.evidence.text for x in s.feedback().items) or any(sentence.rstrip("。")[:10] in t.text for t in s.turns if t.role == "interviewer")


def test_R4_a_secret_and_a_quota_together_in_one_answer_with_an_ordinary_sentence():
    text = "sk-FAKE-EXAMPLE-TEST を使いました。募集人員は987人です。私は図書館の活動で案内を作りました。"
    s, r = play(text)
    out = shown_with_retry(s)
    assert "sk-FAKE" not in out and "987" not in out and "募集人員" not in out
    assert {"personal_info_masked", "official_claim_not_repeated"} <= {n.code for n in r.notices}
    assert "図書館の活動で案内を作りました" in out                                                   # the ordinary sentence is still the one that is quoted


@pytest.mark.parametrize("case", ["fiction-ac-1", "fiction-rec-2", "fiction-gen-3"])
def test_R5_every_case_behaves_the_same_way(case):
    s, _r = play("sk-FAKE-EXAMPLE-TEST を使いました。募集人員は987人です。", case=case)
    out = shown_with_retry(s)
    assert "sk-FAKE" not in out and "987" not in out


def test_R6_the_profile_side_keeps_both_out_of_the_document_based_questions():
    p = prof.build_profile("私は sk-FAKE-EXAMPLE-TEST の設定を調べました。募集人数は50人です。情報の届け方に関心があります。", [{"title": "api_key=FAKE0123abcd の勉強会", "description": "締切は12月です。案内を作りました。"}])
    assert "sk-FAKE" not in p.motivation and "FAKE0123abcd" not in p.activities[0].title
    s, _r = play("掲示を作りました。", profile=p)
    out = shown_with_retry(s)
    assert "sk-FAKE" not in out and "FAKE0123" not in out and "50人" not in out and "締切" not in out
    assert "情報の届け方" in out


def test_R7_the_output_gate_that_works_uses_also_sees_a_secret():
    assert guards.has_personal("sk-FAKE-EXAMPLE-TEST") and guards.has_personal("password: abcd1234") and not guards.has_personal(PLAIN)


def test_R8_masking_is_idempotent_and_leaves_the_corpus_of_ordinary_text_unchanged():
    for t in [PLAIN, *NORMAL, "探究活動で地域の課題を調べ、担当は聞き取りでした。理由は現場の声を知りたかったからです。大学では社会調査を学びたいです。", "私は地域の図書館で子どもの読み聞かせを手伝った経験から、情報の届け方に関心を持ちました。"]:
        assert guards.mask_personal(t) == t
    once = guards.mask_personal("sk-FAKE-EXAMPLE-TEST と password: abcd1234 と fixture@example.invalid")
    assert guards.mask_personal(once) == once and "FAKE" not in once and "abcd1234" not in once and "example.invalid" not in once


def test_R9_the_new_patterns_are_fast_on_their_worst_inputs_at_the_answer_limit():
    n = guards.MAX_ANSWER_CHARS
    worst = ["sk-" * (n // 3), "sk-" + "a" * n, "A1" * (n // 2), "a" * n, "1" * n, "password:" * (n // 9), "token = " * (n // 8), "eyJ" + "a" * n, "ghp_" + "a" * n, "-----BEGIN " + " " * n, "AKIA" * (n // 4),
             "api_key" + " " * n, "api-key " * (n // 8), "-" * n, "0aA" * (n // 3), "募集人員" * (n // 4), "面接は" * (n // 3), "面接は" + "あ" * n + "分", "公式" * (n // 2)]
    for text in worst:
        text = text[:n]
        for fn in (guards.mask_personal, guards.has_personal, guards.official_claim_in, guards.forbidden_claims_in):
            began = time.perf_counter()
            fn(text)
            assert time.perf_counter() - began < 5.0, (fn.__name__, text[:12])


# ------------------------------------------------------------------ folding: the detection sees through full-width / invisible characters, the masking changes only the secret
def test_R10_folded_detection_masks_only_the_secret_and_leaves_the_rest_of_the_original_text_alone():
    cases = {
        "前置き ｓｋ－ＦＩＣＴＩＯＮＡＬ 後ろ": "前置き " + guards.SECRET_PLACEHOLDER + " 後ろ",
        "ＡＢＣ１２３と全角ｱｲｳは保たれます。": "ＡＢＣ１２３と全角ｱｲｳは保たれます。",
        "x SK-FICTIONAL-DUMMY を、Bearer FictionalAuthToken を": "x " + guards.SECRET_PLACEHOLDER + " を、" + guards.SECRET_PLACEHOLDER + " を",   # Japanese text ends the English phrase after a secret
        "x SK-FICTIONAL-DUMMY y z": "x " + guards.SECRET_PLACEHOLDER,                                                                            # English words that follow a secret on the same line are part of it (a key can go on after a blank)
        "s​k-FICTIONAL-DUMMY": guards.SECRET_PLACEHOLDER,
    }
    for given, expected in cases.items():
        assert guards.mask_personal(given) == expected, given
    assert guards.has_personal("ｓｋ－ＦＩＣＴＩＯＮＡＬ") and not guards.has_personal("ＡＢＣ１２３と全角ｱｲｳ")


def test_R11_the_statement_rule_needs_all_three_parts_and_does_not_fire_on_two():
    assert guards.official_claim_in("大学が受け入れるのは九百八十七名です")           # university + admission + quantity
    assert not guards.official_claim_in("大学の見学で3人の先生に会いました")          # no admission term
    assert not guards.official_claim_in("ボランティアを募集して30人集まりました")      # no university term
    assert not guards.official_claim_in("大学が受け入れてくれる環境を探しました")      # no quantity


def test_R12_the_folded_secret_view_and_the_statement_rule_are_fast_on_their_worst_inputs_at_the_answer_limit():
    n = guards.MAX_ANSWER_CHARS
    worst = ["s " * (n // 2), "s k - " * (n // 6), "bearer " * (n // 7), "ｓｋ－" * (n // 3), "Ａ１" * (n // 2), "一" * n, "一二三" * (n // 3) + "あ", "大学受け入れ" * (n // 6), "十" * (n // 2) + " " * (n // 2),
             "​" * n, "ｓ​ｋ" * (n // 3), "SK-" + "-" * n, "sk" + " " * n, "Bearer " + "A" * n]
    for text in worst:
        text = text[:n]
        for fn in (guards.mask_personal, guards.has_personal, guards.official_claim_in):
            began = time.perf_counter()
            fn(text)
            took = time.perf_counter() - began
            assert took < 5.0, (fn.__name__, text[:10], took)


# ------------------------------------------------------------------ the rule, shown by minimal pairs: the same words, the number bound to an institutional noun (caught) or to the person's own action (kept)
PAIRS = [   # (a statement about the university, the person's own experience with the same words)
    ("大学の新入生は七十七名です", "大学の新入生を三人案内しました"),
    ("学部の合格者は三十名です", "学部の合格者に三人会いました"),
    ("大学が受け入れるのは百名です", "大学が受け入れてくれた友人を三人手伝いました"),
    ("願書は11月9日まで受け付けます", "願書を11月に書きました"),
    ("出願の期限は12月5日です", "出願の準備に三日かけました"),
    ("この学類の選考では百二十人が選ばれます", "この学類の選考で百二十冊の資料を調べました"),
]


@pytest.mark.parametrize("claim,own", PAIRS)
def test_R13_the_same_words_are_a_statement_when_the_number_is_bound_to_the_institution_and_experience_when_it_is_not(claim, own):
    assert guards.official_claim_in(claim) and not guards.official_claim_in(own)
    s, r = play(own + "。")
    assert not {"official_claim_not_repeated"} & {n.code for n in r.notices}
    assert own[:10] in shown(s)                                                          # the person's own sentence is still the one that is quoted
    s, r = play(claim + "。")
    assert "official_claim_not_repeated" in [n.code for n in r.notices] and claim not in shown_with_retry(s)


def test_R14_circled_and_full_width_digits_are_read_as_digits_when_judging_a_statement():
    assert guards.official_claim_in("願書は⑪月⑨日まで受け付けます") and guards.official_claim_in("願書は１１月９日まで受け付けます")


# ------------------------------------------------------------------ found by Work's independent re-QA of #260 at 7f3602c (31 + 14 PASS kept; 3 new: 1 PASS / 2 FAIL)
# 1. a key split by a blank ("sk-FICTIONAL ALPHAREMAINDER"): the second half was quoted.  2. the prefix written with a letter of another script ("ѕk-" with a Cyrillic ѕ).
# The patterns can only know the shapes they were written for, so there are three layers: (a) a finite table of ASCII look-alikes is folded before the patterns run, (b) after a secret the rest of that English
# phrase is masked too, (c) whatever no pattern recognises is still not QUOTED if it is machine-like (guards.opaque_token_in).
SPLIT_AND_DISGUISED = [
    "sk-FICTIONAL ALPHAREMAINDER", "sk-FICTIONAL  ALPHA  REMAINDER", "sk-AAAAAA BBBBBB CCCCCC", "ѕk-FICTIONAL-ALPHA", "ѕk−FICTIONAL-ALPHA", "sк-FICTIONAL-ALPHA",
    "рk-FICTIONAL-ALPHA", "ЅK-FICTIONAL-ALPHA", "Bearer FictionalAuth Token", "password: FAKEpass0123 and more",
]


@pytest.mark.parametrize("secret", SPLIT_AND_DISGUISED)
def test_R15_a_split_or_look_alike_secret_is_masked_to_its_end_and_never_quoted(secret):
    s, r = play(secret + " を利用しました。")
    out = shown_with_retry(s)
    for part in secret.replace("-", " ").replace("−", " ").replace(":", " ").split():
        if len(part) >= 8:
            assert part not in out, (secret, part)
    assert "personal_info_masked" in [n.code for n in r.notices]
    assert "を利用しました" in " ".join(t.text for t in s.turns if t.role == "candidate")             # the Japanese that follows is not swallowed


UNRECOGNISED_MACHINE_LIKE = [
    "A9f3KQ7xLm2Zp8Vt", "ALPHAREMAINDER", "XK-9921-QZ-ABC", "2023-report-final-v2", "kеyеd", "Ρython", "OpenAIGymEnvironment", "ab_cd_ef_gh_ij_kl", "AbCdEfGhIjKl",
]


@pytest.mark.parametrize("token", UNRECOGNISED_MACHINE_LIKE)
def test_R16_a_machine_like_token_that_no_pattern_knows_is_still_not_quoted_but_the_ordinary_sentence_next_to_it_is(token):
    s, r = play(token + " を入力しました。私は図書館の活動で案内を作りました。")
    out = shown_with_retry(s)
    assert token not in out
    assert "opaque_token_not_repeated" in [n.code for n in r.notices]
    assert "図書館の活動で案内を作りました" in out


@pytest.mark.parametrize("sentence", [
    "Human-Computer-Interaction の授業を見学しました。", "Information-Retrieval-Systems について発表しました。", "Telecommunications の仕組みを調べました。", "ChatGPT の使い方を後輩に教えました。",
    "Python でデータ整理のプログラムを書きました。", "TOEFL の勉強を続けました。", "InformationRetrieval の授業を見学しました。", "state-of-the-art-information-retrieval-evaluation-methods の論文を読みました。", "internationalization について調べました。",
])
def test_R17_plain_english_terms_are_still_quoted(sentence):
    assert not guards.opaque_token_in(sentence) and guards.mask_personal(sentence) == sentence
    s, r = play(sentence)
    assert "opaque_token_not_repeated" not in [n.code for n in r.notices]
    assert sentence[:12] in shown(s)


def test_R18_the_profile_side_does_not_quote_a_machine_like_token_either():
    p = prof.build_profile("私は ALPHAREMAINDER という名前の仕組みを調べました。情報の届け方に関心があります。", [{"title": "XK-9921-QZ-ABC の勉強会", "description": "案内を作りました。"}])
    s, _r = play("掲示を作りました。", profile=p)
    out = shown_with_retry(s)
    assert "ALPHAREMAINDER" not in out and "XK-9921" not in out and "情報の届け方" in out


def test_R19_the_new_folding_and_the_continuation_are_fast_on_their_worst_inputs_at_the_answer_limit():
    n = guards.MAX_ANSWER_CHARS
    worst = ["sk-A " * (n // 5), "sk-AAAAAA" + " a" * (n // 2), "ѕk-" * (n // 3), "а" * n, "A" * n, "A-" * (n // 2), "a1" * (n // 2), "аa" * (n // 2), "sk-" + "A " * (n // 2), "Bearer " + "A " * (n // 2)]
    for text in worst:
        text = text[:n]
        for fn in (guards.mask_personal, guards.has_personal, guards.opaque_token_in, guards.official_claim_in):
            began = time.perf_counter()
            fn(text)
            took = time.perf_counter() - began
            assert took < 5.0, (fn.__name__, text[:10], took)


# ------------------------------------------------------------------ found by Antigravity's independent QA of #260 at 51cc481 (PR #272 e6f2367: 43 PASS / 1 FAIL: anti_split_with_tab)
# "sk<TAB>-<TAB>live<TAB>-<TAB>987654321": the blanks around the separators cut the key into pieces (4 and 9 characters) that are each too short for a pattern, and 9 characters are below the 12 of the quote
# restriction.  The detection view now drops the blanks that touch a hyphen / underscore (the text itself is never rewritten).
BLANKS_AROUND_SEPARATORS = [
    "sk\t-\tlive\t-\t987654321",                         # Antigravity's exact input
    "sk - live - 987654321", "sk _ test _ 12345", "sk　-　live　-　987654321", "sk-live - 987654321", "pk\t_\ttest\t_\tabcdef", "sk \t - \t live \t - \t 987654321",
]


@pytest.mark.parametrize("secret", BLANKS_AROUND_SEPARATORS)
def test_R20_a_key_cut_by_blanks_around_its_separators_is_masked_to_its_end_and_never_quoted(secret):
    s, r = play(secret + " を利用しました。")
    out = shown_with_retry(s)
    for part in secret.replace("-", " ").replace("_", " ").split():
        if len(part) >= 5:
            assert part not in out, (secret, part)
    assert "personal_info_masked" in [n.code for n in r.notices]
    assert "を利用しました" in " ".join(t.text for t in s.turns if t.role == "candidate")


@pytest.mark.parametrize("token", ["live\t-\t987654321", "alpha - beta - 20240101", "key \t_ \tvalue \t_ \t12345678"])
def test_R21_the_same_pieces_without_a_known_prefix_are_not_quoted_either(token):
    s, r = play(token + " を入力しました。私は図書館の活動で案内を作りました。")
    out = shown_with_retry(s)
    digits = [p for p in token.replace("-", " ").replace("_", " ").split() if p.isdigit()][0]
    assert digits not in out
    assert "opaque_token_not_repeated" in [n.code for n in r.notices] and "図書館の活動で案内を作りました" in out


@pytest.mark.parametrize("sentence", [
    "Human - Computer Interaction の授業を見学しました。", "2024 - 2025 年度の委員を務めました。", "Python - Java - C のどれも使いました。", "A - B の二つの案を比べました。", "東京 - 大阪 の交流会に参加しました。",
    "SK - Hynix という会社について調べました。", "日本語 - English の翻訳を担当しました。",
])
def test_R22_ordinary_phrases_with_a_spaced_dash_are_untouched_and_still_quoted(sentence):
    assert guards.mask_personal(sentence) == sentence and not guards.opaque_token_in(sentence)
    s, r = play(sentence)
    assert not {"personal_info_masked", "opaque_token_not_repeated"} & {n.code for n in r.notices}
    assert sentence[:10] in shown(s)


def test_R23_dropping_the_blanks_is_linear_on_the_worst_inputs_at_the_answer_limit():
    n = guards.MAX_ANSWER_CHARS
    worst = ["sk\t-\t" * (n // 5), " - " * (n // 3), "a" + " -" * (n // 2), "\t" * n, "-" + " " * n, "sk" + " \t" * (n // 2) + "-", "_ " * (n // 2), "sk - a " * (n // 7)]
    for text in worst:
        text = text[:n]
        for fn in (guards.mask_personal, guards.has_personal, guards.opaque_token_in):
            began = time.perf_counter()
            fn(text)
            took = time.perf_counter() - began
            assert took < 5.0, (fn.__name__, text[:10], took)
