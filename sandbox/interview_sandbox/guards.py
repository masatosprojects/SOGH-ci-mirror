"""Wording and privacy guards. Everything the sandbox shows to a person is checked against the claims the product must never make."""
from __future__ import annotations

import re

# A DENIAL of a claim is the wording we want ("実際の面接と同じ進行や合格可能性は保証しません", "必ず聞かれるとは限りません"): a pattern is not a violation when the SAME CLAUSE negates it (no '、' or '。'
# in between, at most 24 characters). "合格できますが、保証はしません" is still refused: the comma ends the clause, so the assertion stands. Found while reviewing Work's PR #109 preview.
_DENIAL = r"(?![^。、]{0,24}(?:とは限りません|とは限らない|ではありません|ではない|ものではありません|を意味しません|保証しません|しません|できません))"

# claims that are forbidden in anything the sandbox emits (an invented practice tool may not say these, even as a joke)
FORBIDDEN_CLAIMS = (
    re.compile(r"合格(率|確率|可能性)\s*(?:(?:は|が|[:：])\s*)?(?:(?:約|およそ)\s*)?\d"),  # "合格率は 80%" too (found re-reviewing PR #109: a particle between the word and the number evaded the first pattern)
    re.compile(r"合格(できます|間違い|保証|確実)" + _DENIAL),
    re.compile(r"(大学|学校)(公認|公式認定)(?!でも(ありません|ない)|ではありません|ではない)"),  # a denial ("大学公認でもありません") is the wording we WANT
    re.compile(r"完全(に)?再現" + _DENIAL),
    re.compile(r"再現度\s*\d"),
    re.compile(r"必ず(出題|聞かれ)" + _DENIAL),
    re.compile(r"(出題|質問)(されます|される予定)" + _DENIAL),
    re.compile(r"実際の(入試|面接)(と同じ|そのまま)" + _DENIAL),
    re.compile(r"\d+\s*(点|％|%)\s*(満点|で合格)"),
)

# a person's words about these are never probed further
SENSITIVE_TERMS = ("家庭の事情", "家庭環境", "宗教", "信仰", "政治的", "支持政党", "思想", "病気", "持病", "既往", "年収", "家族構成", "国籍", "出身地")

# Personal-information shapes, in the forms a person actually types: ASCII and full-width letters / digits / '@', a spelled-out "(at)", international phone numbers, links and account names, postal codes.
# Names and street addresses are NOT detected (a school or university name such as 大阪府立大学 must stay readable): the screen tells people not to enter them, and the limit is stated in the README.
_D = "0-9０-９"
_SEP = r"[-\s‐-―−－ー]?"
_AT = r"(?:[@＠]|\s*[\(\[（［]\s*(?:at|AT|アット)\s*[\)\]）］]\s*)"
_EMAIL = re.compile(rf"[\w.+\-]+{_AT}[\w\-]+(?:[.．][\w\-]+)+")  # NOTE: quadratic on one very long run of word characters (20,000 characters took 6 s); the input limits (MAX_ANSWER_CHARS, the profile limits) bound it. A look-behind made it linear but stopped masking "a@b.c+d@e.f" (found by a differential fuzz), so the exact pattern is kept.
_PHONE = re.compile(rf"(?:[+＋]\s?[8８][1１]{_SEP}|[0０])[{_D}]{{1,4}}{_SEP}[{_D}]{{1,4}}{_SEP}[{_D}]{{3,4}}")
_URL = re.compile(r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)  # ASCII only: it stops at a Japanese comma or full stop
_HANDLE = re.compile(r"(?<![\w@＠])[@＠][A-Za-z0-9_]{3,15}(?![\w@＠])")
_POSTAL = re.compile(rf"〒\s?[{_D}]{{3}}{_SEP}[{_D}]{{4}}")

# Secret-looking strings (API keys, access tokens, private keys, "password: ..."): a practice answer has no reason to contain one, and it must never be quoted back.  Linear patterns: each starts only where
# a run of key characters begins.  The hyphen class includes the Unicode hyphens a person (or a hostile test) may type instead of "-".
_H = "\\-\u2010-\u2015\u2212\uff0d"
_SECRET = (
    re.compile(rf"(?<![A-Za-z0-9])(?:(?i:s\s{{0,3}}k|p\s{{0,3}}k|r\s{{0,3}}k)|エスケ[ーイ]|ピーケ[ーイ]|アールケ[ーイ])\s{{0,3}}[{_H}_]\s{{0,3}}[A-Za-z0-9_{_H}]{{6,}}"),  # sk-..., SK-..., s k - ..., pk_..., rk-... (API key shape; full-width letters are folded first)
    re.compile(r"(?<![A-Za-z0-9])(?i:bearer)\s+(?=[A-Za-z0-9._~+/=\-]*[A-Z0-9])[A-Za-z0-9._~+/=\-]{6,}"),   # Bearer <token>
    re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),                       # AWS access key id
    re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),   # GitHub tokens
    re.compile(r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9\-]{10,}"),                                   # Slack tokens
    re.compile(r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"),  # JSON web token
    re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----"),
    re.compile(r"(?i)(?<![A-Za-z])(?:api[_\- ]?key|secret|token|passw(?:or)?d|パスワード|暗証番号|秘密鍵)\s*[:=：＝]\s*[^\s、。,;]{4,}"),      # "password: xxxx"
    re.compile(r"(?<![A-Za-z0-9+/_\-])(?=[A-Za-z0-9+/_\-]{0,63}[0-9])(?=[A-Za-z0-9+/_\-]{0,63}[A-Za-z])[A-Za-z0-9+/_\-]{40,}(?![A-Za-z0-9+/_\-])"),  # a long unbroken token with letters and digits
)
SECRET_PLACEHOLDER = "[秘密情報らしい文字列]"


# Letters of other scripts that are drawn like an ASCII letter (a finite table of the common ones; NFKC does not fold them).  Used ONLY for detection: the text itself is never rewritten.
_CONFUSABLE = {
    **{c: "a" for c in "\u0430\u03b1"}, **{c: "c" for c in "\u0441\u03f2"}, **{c: "e" for c in "\u0435"}, **{c: "h" for c in "\u04bb"}, **{c: "i" for c in "\u0456\u03b9\u0131"},
    **{c: "j" for c in "\u0458"}, **{c: "k" for c in "\u043a\u03ba"}, **{c: "o" for c in "\u043e\u03bf\u0585"}, **{c: "p" for c in "\u0440\u03c1"}, **{c: "s" for c in "\u0455"},
    **{c: "x" for c in "\u0445\u03c7"}, **{c: "y" for c in "\u0443\u03b3"}, **{c: "d" for c in "\u0501"}, **{c: "q" for c in "\u051b"}, **{c: "w" for c in "\u051d"}, **{c: "v" for c in "\u0475\u03bd"},
    **{c: "l" for c in "\u04cf"},
    **{c: "A" for c in "\u0410\u0391"}, **{c: "B" for c in "\u0412\u0392"}, **{c: "C" for c in "\u0421\u03f9"}, **{c: "E" for c in "\u0415\u0395"}, **{c: "H" for c in "\u041d\u0397"},
    **{c: "I" for c in "\u0406\u0399"}, **{c: "J" for c in "\u0408"}, **{c: "K" for c in "\u041a\u039a"}, **{c: "M" for c in "\u041c\u039c"}, **{c: "N" for c in "\u039d"}, **{c: "O" for c in "\u041e\u039f"},
    **{c: "P" for c in "\u0420\u03a1"}, **{c: "S" for c in "\u0405"}, **{c: "T" for c in "\u0422\u03a4"}, **{c: "X" for c in "\u0425\u03a7"}, **{c: "Y" for c in "\u04ae\u03a5"}, **{c: "Z" for c in "\u0396"},
}


# A key written with blanks around its separators ("sk<TAB>-<TAB>live<TAB>-<TAB>987654321") is cut into pieces that are each too short for a pattern.  In the DETECTION view the blanks (space, tab) that touch a
# hyphen or an underscore are dropped; the text itself is never rewritten.  This can make an ordinary "Human - Computer" look like "Human-Computer" to the detector, which is harmless (nothing is changed).
_DASHES = frozenset("-_\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d")
_DASH_BLANKS = re.compile(r"[ \t]*([-_\u2010-\u2015\u2212\uff0d])[ \t]*")


def _drop_blanks_around_dashes(chars: list[str], origin: list[int]) -> tuple[list[str], list[int]]:
    out: list[str] = []
    idx: list[int] = []
    n, i = len(chars), 0
    while i < n:
        if chars[i] in " \t":
            j = i
            while j < n and chars[j] in " \t":
                j += 1
            before = chars[i - 1] if i else ""
            after = chars[j] if j < n else ""
            if before not in _DASHES and after not in _DASHES:
                out.extend(chars[i:j])
                idx.extend(origin[i:j])
            i = j
            continue
        out.append(chars[i])
        idx.append(origin[i])
        i += 1
    return out, idx


def _folded(text: str) -> tuple[str, list[int]]:
    """The text as the secret patterns see it: NFKC (full-width letters and digits become ASCII) with invisible formatting characters dropped, and for every kept character the index it came from in the
    original text.  Detection runs on this view; masking replaces the matching span of the ORIGINAL text, so what the person typed is never rewritten except where a secret was."""
    import unicodedata
    out: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if unicodedata.category(ch) == "Cf":
            continue
        for c in unicodedata.normalize("NFKC", ch):
            out.append(_CONFUSABLE.get(c, c))
            origin.append(i)
    out, origin = _drop_blanks_around_dashes(out, origin)
    return "".join(out), origin


# A key can go on after a blank ("sk-ABC DEF GHI"): once a secret is found, the English words that follow it on the same line (separated by one to three blanks, up to the first character that is not part of
# one) are part of it too.  This can hide a few harmless words after a secret; it cannot reveal anything.
_CONTINUATION = re.compile(r"(?:[ \t]{1,3}[A-Za-z0-9_\-+/=]+)*")


def _secret_spans(text: str) -> list[tuple[int, int]]:
    folded, origin = _folded(text)
    spans = sorted((origin[m.start()], origin[_CONTINUATION.match(folded, m.end()).end() - 1] + 1) for p in _SECRET for m in p.finditer(folded) if m.end() > m.start())
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


# QUOTE RESTRICTION FOR SECRETS THAT NO PATTERN KNOWS.  The patterns above recognise the shapes of known keys; a new or disguised shape is not recognised.  So, in addition, a sentence that holds a machine-like
# token is never QUOTED (not in a follow-up, not as the evidence of a feedback item, not in a document-based question), whether or not it was recognised: a run of 12 or more ASCII letters / digits / "-_+/=" that has
# a digit, two or more capital letters INSIDE a word (a capital whose previous character is a letter: "FICTIONAL-ALPHA", "ALPHAREMAINDER", camelCase), or one of "_/+=" ("A9f3KQ7xLm2Zp8Vt", "2023-report-final-v2"), or a
# word that mixes Latin letters with Cyrillic / Greek ones.  Plain words stay quotable: "state-of-the-art-information-retrieval-evaluation-methods" (lower case and hyphens only), "Telecommunications" (one initial
# capital), "Human-Computer-Interaction" (capitals only at the start of a word), "ChatGPT" (short).
_TOKEN_RUN = re.compile(r"[A-Za-z0-9_\-+/=]{12,}")
_WORD = re.compile(r"[\w\-]+")


def _script_of(ch: str) -> str:
    o = ord(ch)
    if "A" <= ch <= "Z" or "a" <= ch <= "z":
        return "latin"
    if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF:
        return "greek"
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    return ""


def opaque_token_in(text: str) -> bool:
    """True if the text holds a machine-like token that must not be quoted back (see the note above).  Detection only; nothing is rewritten."""
    import unicodedata
    view = _DASH_BLANKS.sub(r"\1", unicodedata.normalize("NFKC", text))
    for m in _TOKEN_RUN.finditer(view):
        run = m.group()
        inside = sum(1 for i, c in enumerate(run) if i and c.isupper() and run[i - 1].isalpha())
        if any(c.isdigit() for c in run) or inside >= 2 or any(c in "_/+=" for c in run):
            return True
    for m in _WORD.finditer(view):
        scripts = {s for s in map(_script_of, m.group()) if s}
        if "latin" in scripts and len(scripts) > 1:
            return True
    return False


def _mask_secrets(text: str) -> str:
    for a, b in reversed(_secret_spans(text)):
        text = text[:a] + SECRET_PLACEHOLDER + text[b:]
    return text

# What a person says ABOUT the university (a quota, a rate, a deadline, a fee, an interview length) is not a verified official fact.  The tool never repeats it as if it were one: not in a follow-up question,
# not as the evidence of a feedback item, not in a document-based question.  The words are narrow on purpose (a club that "recruited 30 members" or a "公式戦" is the person's own experience and stays quotable).
OFFICIAL_CLAIM_WORDS = ("倍率", "定員", "募集人員", "募集人数", "募集定員", "入学定員", "志願者数", "志願倍率", "競争率", "合格者数", "受験料", "検定料", "締切", "締め切り", "出願期間", "出願期限",
                        "提出期限", "募集要項", "配点", "合格最低点", "合格ライン", "選考日程", "試験日", "面接時間", "試験時間", "試験会場")
# "X is/of ... <number><unit>" about the interview / selection / application / entrance examination is a statement about the university ("面接は10分です", "選考の日程は11月3日").
# "定期試験で90点", "入試に向けて3か月", "面接の練習を週3回" are the person's own experience: no は/が/の directly after the noun, or no such unit, so they stay quotable.
OFFICIAL_CLAIM_PATTERN = re.compile(r"(?:面接|選考|出願|入試)(?:時間|日程|期間|期限|方法)?[はがの][^。！？\n]{0,8}[0-9０-９]+\s*(?:分|時間|日|月|人|名|点|割|倍|%|％|問)|公式(?!戦|サイト|ホームページ|アカウント|HP)")


MAX_ANSWER_CHARS = 4000  # one spoken-length answer; longer input is refused before any scanning


def clean_text(text: str) -> tuple[str, int]:
    """Remove control characters (except a line break and a tab), invisible formatting characters (zero-width, bidi overrides, BOM, soft hyphen), line/paragraph separators, lone surrogates
    and private-use characters.  Returns the cleaned text and how many characters were removed.  Done BEFORE any guard runs: a zero-width character inside 合格できます would otherwise hide
    the claim from the guard, and an escape sequence would reach the terminal when the person's words are quoted back."""
    import unicodedata
    keep, removed = [], 0
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\t" or not (cat in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")):
            keep.append(ch)
        else:
            removed += 1
    return "".join(keep), removed


def forbidden_claims_in(text: str) -> list[str]:
    return [p.pattern for p in FORBIDDEN_CLAIMS if p.search(text)]


def assert_clean(text: str) -> str:
    bad = forbidden_claims_in(text)
    if bad:
        raise ValueError(f"the sandbox would make a forbidden claim: {bad}")
    return text


def mask_personal(text: str) -> str:
    """Mask an e-mail address or phone number before the text is quoted back or shown in a report."""
    text = _EMAIL.sub("[メール]", text)  # first: an address contains characters that would also look like an account name or a link
    text = _URL.sub("[リンク]", text)
    text = _mask_secrets(text)
    text = _HANDLE.sub("[アカウント名]", text)
    text = _POSTAL.sub("[郵便番号]", text)
    return _PHONE.sub("[電話番号]", text)


def has_personal(text: str) -> bool:
    return any(p.search(text) for p in (_EMAIL, _URL, _HANDLE, _POSTAL, _PHONE)) or bool(_secret_spans(text))


# WHAT IS TREATED AS AN UNVERIFIED STATEMENT ABOUT THE UNIVERSITY (and therefore never quoted back), stated as rules rather than as a list of phrasings.  Detection runs on the NFKC view of the sentence (so
# circled and full-width digits are plain digits).  A sentence is such a statement when it contains
#   1. an INSTITUTIONAL NOUN (the quota, the entrants, the successful candidates, the applicants ...) that governs a number of people through は / が / の  ("新入生は七十七名", "受け入れるのは九百八十七名",
#      "合格者の三十名"), or a number of people who are selected / hired / admitted ("百二十人が選ばれる"), in a sentence that is about the university; or
#   2. a DATE (month, or day followed by まで / から / 必着 / 締切) tied to a deadline or application word ("願書は11月9日まで", "出願の期限は12月5日"); or
#   3. one of the fixed words / patterns above (quota, rate, fee, deadline, interview length, "the official ...").
# What it is NOT: a number that belongs to the person's own action ("三人を支援しました", "30人集めました", "参考書を三冊読みました", "三か月続けました") or to a thing they saw ("先生三人に質問しました"): there the number is
# not bound to an institutional noun by は / が / の, or the sentence has no university term.  A statement worded in a way none of these rules describes is NOT detected (it is quoted); see the limits in the doc.
_NUM = "0-9〇零一二三四五六七八九十百千万"
_UNIVERSITY_TERMS = ("大学", "本学", "学部", "学類", "学科", "研究科", "願書", "出願", "入学試験", "入試", "選考")
_INSTITUTIONAL_NOUNS = "受け入れ|受入|迎え|定員|入学者|合格者|新入生|志願者|入学生|枠"
_PEOPLE_COUNT = re.compile(rf"(?:{_INSTITUTIONAL_NOUNS})[^。！？\n]{{0,6}}?[はがの]\s*(?:毎年|例年|昨年|今年|去年|約|およそ|ほぼ|だいたい|大体)?\s*[{_NUM}]+\s*[人名]|[{_NUM}]+\s*[人名]\s*[がを]?\s*(?:選ばれ|採用|受け入れ|入学でき|入学し)")
_DATE_ANY = rf"[{_NUM}]+\s*月(?:\s*[{_NUM}]+\s*日)?|[{_NUM}]+\s*日"
_DEADLINE_NOUNS = ("願書", "出願", "締切", "締め切り", "期限", "受付", "受け付け", "提出", "選考日程", "試験日")
# a date STATED as a deadline: "<deadline word> は/が/の <date>" or "<date> まで / 必着 / 締切".  "十一月に出願する予定です" and "出願を十一月九日に済ませました" (the person's own plan / action) are not.
_DEADLINE_DATE = re.compile(rf"(?:{'|'.join(_DEADLINE_NOUNS)})[^。！？\n]{{0,6}}?[はがの]\s*(?:{_DATE_ANY})|(?:{_DATE_ANY})\s*(?:まで|必着|締切|締め切り|迄)")


def official_claim_in(text: str) -> bool:
    """True if the text states something about the university that this tool has not verified (a quota, a rate, a deadline, a fee, an interview length, "the official ...").  See the rules above."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    if any(w in text for w in OFFICIAL_CLAIM_WORDS) or OFFICIAL_CLAIM_PATTERN.search(text):
        return True
    if any(t in text for t in _UNIVERSITY_TERMS) and _PEOPLE_COUNT.search(text):
        return True
    return any(t in text for t in _DEADLINE_NOUNS) and bool(_DEADLINE_DATE.search(text))


def sensitive_in(text: str) -> list[str]:
    return [t for t in SENSITIVE_TERMS if t in text]
