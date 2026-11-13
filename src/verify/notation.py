"""Notation variants of dates, years and numbers — Issue #13.

Independent of the article checks: this module only turns the many ways Japanese
text writes the same date, year or range into ONE canonical spelling that the strict
checks already understand, and reports what it could NOT classify. It never
looks at evidence and never decides whether something is right.

Rules that keep it honest:
* A rewrite is made only when the reading is unambiguous. "8/6" is a date only next to a
  weekday or a date word (締切・出願・まで ...); otherwise it stays "8/6" and is reported
  as an unclassified number (it could be a fraction).
* A number without a unit is never turned into persons / yen / pages. It is listed as
  `unclassified` so a person knows the QA did not check it.
* 年度 (fiscal year), 実施年 (exam year) and 入学年 (entry year) are not merged: an era year
  becomes the same Gregorian year in the SAME position, so "令和8年度入試" and "2026年度入試"
  go down exactly the same path.
* Everything is NFKC-normalised first (全角/半角, ，→,).
"""
from __future__ import annotations

import dataclasses
import re
import unicodedata

ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}
_ERA_ABBR = {"R": "令和", "H": "平成", "S": "昭和"}

KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
_KANJI_CHARS = "〇一二三四五六七八九十百千"

# unit word -> kind. Longest alternatives first so 文字 wins over 字 and 時間 over 時.
UNIT_KINDS: dict[str, str] = {
    "名": "persons", "人": "persons", "分": "minutes", "時間": "hours", "文字": "chars", "字": "chars",
    "words": "words", "word": "words", "ワード": "words", "単語": "words", "語": "words",
    "枚": "pages", "ページ": "pages", "頁": "pages", "MB": "mb", "メガバイト": "mb", "点": "items",
    "円": "yen", "倍": "ratio", "%": "ratio",
}
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNIT_KINDS), key=len, reverse=True))


def normalize_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def kanji_to_int(s: str) -> int | None:
    """三十 -> 30, 九百九十九 -> 999, 二〇 -> 20, 一万二千 -> 12000."""
    if not s:
        return None
    if all(c in KANJI_DIGITS for c in s):  # positional: 二〇二六
        return int("".join(str(KANJI_DIGITS[c]) for c in s))
    if "万" in s:
        head, _, tail = s.partition("万")
        high = kanji_to_int(head) if head else 1
        low = kanji_to_int(tail) if tail else 0
        if high is None or low is None:
            return None
        return high * 10000 + low
    total = current = 0
    for c in s:
        if c in KANJI_DIGITS:
            current = KANJI_DIGITS[c]
        elif c in KANJI_UNITS:
            total += (current or 1) * KANJI_UNITS[c]
            current = 0
        else:
            return None
    return total + current


def _to_int(s: str) -> int | None:
    s = s.replace(",", "")
    return int(s) if s.isdigit() else kanji_to_int(s)


def _era_year(era: str, n: str) -> int | None:
    value = 1 if n == "元" else _to_int(n)
    return None if value is None or not 1 <= value <= 99 else ERA_BASE[era] + value


# ------------------------------------------------------------------ rewriting dates

@dataclasses.dataclass
class Normalized:
    text: str
    originals: dict[str, str]  # canonical spelling -> what the article actually wrote


def _record(originals: dict[str, str], canonical: str, original: str) -> str:
    if original != canonical:
        originals.setdefault(canonical, original)
    return canonical


_ERA_FULL = "|".join(ERA_BASE)

_DATE_CONTEXT = re.compile(r"締切|締め切り|期限|出願|受付|提出|消印|発表|試験|面接|開始|終了|公開|期間|まで|から|必着|到着|入力|登録|郵送|実施|日程")
_WEEKDAY_AFTER = re.compile(r"\s*[(（]?[月火水木金土日][)）]?")
_SLASH_MD = re.compile(r"(?<![\d/.\-])(?P<m>\d{1,2})/(?P<d>\d{1,2})(?![\d/])")
_TIME_AFTER_DATE = re.compile(
    r"(?P<head>\d{1,2}月\d{1,2}日(?:\s*[(（][月火水木金土日][)）])?)\s*(?P<ap>午前|午後)?\s*(?P<h>\d{1,2})時(?:\s*(?P<mi>\d{1,2})分)?(?:ごろ)?")


def _kanji_date_parts(text: str, originals: dict[str, str]) -> str:
    """二〇二六年十月八日 / 令和八年十月八日 / 十月八日 -> Arabic numerals (no change of meaning)."""
    def era_year(m: re.Match[str]) -> str:
        year = _era_year(m.group("era"), m.group("n"))
        return m.group(0) if year is None else _record(originals, f"{m.group('era')}{year - ERA_BASE[m.group('era')]}年", m.group(0))
    text = re.sub(rf"(?P<era>{_ERA_FULL})(?P<n>元|[{_KANJI_CHARS}]+)年", era_year, text)

    def positional_year(m: re.Match[str]) -> str:
        return _record(originals, f"{kanji_to_int(m.group('y'))}年", m.group(0))
    text = re.sub(r"(?<![〇一二三四五六七八九十])(?P<y>[〇一二三四五六七八九]{4})年", positional_year, text)

    def month(m: re.Match[str]) -> str:
        value = kanji_to_int(m.group("n"))
        return m.group(0) if value is None or not 1 <= value <= 12 else _record(originals, f"{value}月", m.group(0))
    text = re.sub(rf"(?<![{_KANJI_CHARS}])(?P<n>[{_KANJI_CHARS}]{{1,3}})月(?![間曜])", month, text)

    def day(m: re.Match[str]) -> str:
        value = kanji_to_int(m.group("n"))
        return m.group(0) if value is None or not 1 <= value <= 31 else _record(originals, f"{value}日", m.group(0))
    return re.sub(rf"(?<=月)(?P<n>[{_KANJI_CHARS}]{{1,3}})日(?!間)", day, text)


def normalize_notation(sentence: str) -> Normalized:
    """The canonical spelling of every date / year this module is sure about. Idempotent."""
    originals: dict[str, str] = {}
    text = normalize_width(sentence)

    # R8.8.6 / H31/4/1 / R8年度  ->  令和8.8.6 ...
    text = re.sub(r"(?<![A-Za-z0-9])(?P<a>[RHS])(?=\d{1,2}[./年])",
                  lambda m: _ERA_ABBR[m.group("a")], text)
    # 令和8.8.6 / 令和8/8/6 -> 2026年8月6日
    def era_full_date(m: re.Match[str]) -> str:
        year = _era_year(m.group("era"), m.group("n"))
        mo, d = int(m.group("m")), int(m.group("d"))
        if year is None or not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return _record(originals, f"{year}年{mo}月{d}日", m.group(0))
    text = re.sub(rf"(?P<era>{_ERA_FULL})(?P<n>元|\d{{1,2}})[./](?P<m>\d{{1,2}})[./](?P<d>\d{{1,2}})(?![\d])", era_full_date, text)

    text = _kanji_date_parts(text, originals)

    # 令和8年 -> 2026年 (the same position: 年度 / 入学 / 月 stay exactly as written)
    def era_year(m: re.Match[str]) -> str:
        year = _era_year(m.group("era"), m.group("n"))
        return m.group(0) if year is None else _record(originals, f"{year}年", m.group(0))
    text = re.sub(rf"(?P<era>{_ERA_FULL})(?P<n>元|\d{{1,2}})年", era_year, text)

    # 2026/8/6, 2026.8.6, 2026-8-6 -> 2026年8月6日 (ISO 2026-08-06 is already understood and left alone)
    def western(m: re.Match[str]) -> str:
        mo, d = int(m.group("m")), int(m.group("d"))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return _record(originals, f"{m.group('y')}年{mo}月{d}日", m.group(0))
    text = re.sub(r"(?<![\d.\-/])(?P<y>(?:19|20)\d{2})[/.\-](?P<m>\d{1,2})[/.\-](?P<d>\d{1,2})(?![\d])",
                  lambda m: m.group(0) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0)) else western(m), text)

    # 8/6 -> 8月6日, only next to a weekday or a date word; else it stays and is reported as unclassified
    def month_day(m: re.Match[str]) -> str:
        mo, d = int(m.group("m")), int(m.group("d"))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        near = text[max(0, m.start() - 12): m.end() + 12]
        if _WEEKDAY_AFTER.match(text, m.end()) or _DATE_CONTEXT.search(near):
            return _record(originals, f"{mo}月{d}日", m.group(0))
        return m.group(0)
    text = _SLASH_MD.sub(month_day, text)

    # 10月8日 午後5時 / 17時30分 -> 10月8日 17:00 / 17:30
    def with_time(m: re.Match[str]) -> str:
        hour, minute = int(m.group("h")), int(m.group("mi") or 0)
        if m.group("ap") == "午後" and hour < 12:
            hour += 12
        if not (0 <= hour <= 24 and 0 <= minute <= 59):
            return m.group(0)
        return _record(originals, f"{m.group('head')} {hour}:{minute:02d}", m.group(0))
    text = _TIME_AFTER_DATE.sub(with_time, text)
    return Normalized(text, originals)


# ------------------------------------------------------------------ ranges

_NUM = rf"(?:\d[\d,]*(?:\.\d+)?|[{_KANJI_CHARS}万]+)"
_RANGE_RE = re.compile(
    rf"(?P<lo>{_NUM})\s*(?P<u1>{_UNIT_ALT})?\s*(?:[〜~～\-–—]|から)\s*(?P<hi>{_NUM})\s*(?P<u2>{_UNIT_ALT})", re.I)


@dataclasses.dataclass(frozen=True)
class RangeMatch:
    start: int
    end: int
    kind: str
    lo: float | int
    hi: float | int
    raw: str


def _number(s: str) -> float | int | None:
    s = s.replace(",", "")
    if re.fullmatch(r"\d+", s):
        return int(s)
    if re.fullmatch(r"\d+\.\d+", s):
        return float(s)
    return kanji_to_int(s)


def find_ranges(text: str) -> list[RangeMatch]:
    """"800〜1000字", "2〜3枚", "30名から40名", "800字〜1000字". Both ends share one unit."""
    out: list[RangeMatch] = []
    for m in _RANGE_RE.finditer(text):
        if m.start() > 0 and text[m.start() - 1] in "-/." and m.group("lo")[0].isdigit():
            continue  # 2026-10-8, 8/6〜: part of a date
        u2 = m.group("u2")
        kind = UNIT_KINDS.get(u2) or UNIT_KINDS.get(u2.lower())
        if m.group("u1"):
            k1 = UNIT_KINDS.get(m.group("u1")) or UNIT_KINDS.get(m.group("u1").lower())
            if k1 != kind:
                continue
        lo, hi = _number(m.group("lo")), _number(m.group("hi"))
        if kind is None or lo is None or hi is None or lo > hi:
            continue
        out.append(RangeMatch(m.start(), m.end(), "minutes" if kind == "hours" else kind, lo, hi, m.group(0)))
    return out


# ------------------------------------------------------------------ what could not be classified

_RESIDUAL_RE = re.compile(r"(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?(?:/\d[\d,]*)?")


@dataclasses.dataclass(frozen=True)
class Unclassified:
    start: int
    raw: str
    hint: str


def unclassified_numbers(blanked_text: str) -> list[Unclassified]:
    """Digits left in the text AFTER every classifier took what it understood.
    These are NOT checked: the QA could not tell what they are (a head count? a year? a fraction?)."""
    out = []
    for m in _RESIDUAL_RE.finditer(blanked_text):
        raw = m.group(0)
        hint = ("slash form: a date (month/day) or a fraction — not guessed" if "/" in raw
                else "no unit next to it — not read as persons, yen or pages")
        out.append(Unclassified(m.start(), raw, hint))
    return out
