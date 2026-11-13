"""Strict article-vs-evidence validation (Issue #7).

The older checks only confirmed that a citation id *exists* near a number.
That let "30名[EV-1]" be edited to "999名[EV-1]" without any finding. This
module compares what the article actually says with the *structured values* of
the evidence record it cites:

* quantities with units (人数, 分, 字, 枚, MB, 点, 円, 倍率, ...) — value AND unit
* dates and times (西暦 / 令和 / ISO), weekday, and start-before-end order
* entry year (入学年度) vs. examination year (試験実施年度)
* scope: 年度内合計 vs 単独枠, 面接の「時間枠」 vs 実質の質疑時間, 「いずれか」 vs 両日
* the source list: PDF page numbers and URL

Rules of thumb that keep this honest:

* Nothing is guessed. A value the cited evidence does not contain is reported,
  never silently accepted ("quantity_not_in_evidence").
* Only evidence that resolves is used; an unknown citation id is already
  reported by the older checks and is not reported a second time here.
* What this *cannot* see (paraphrased qualitative claims, negations such as
  必要/不要, numbers written without a unit and far from a citation, ...) is
  listed in docs/STRICT_VALIDATION.md rather than implied to be covered.
"""
from __future__ import annotations

import dataclasses
import datetime
import re
import unicodedata
from typing import Any

from src.verify.consistency import ConsistencyIssue
from src.verify.fact_registry import Registry, get_registry
from src.verify.notation import Unclassified, find_ranges, kanji_to_int, normalize_notation, unclassified_numbers

_CITATION_RE = re.compile(r"\[(EV-[A-Za-z0-9_\-]+)\]")
_WEEKDAYS = "月火水木金土日"
QUANTITY_KINDS = frozenset({"persons", "minutes", "chars", "words", "pages", "mb", "items", "yen", "ratio", "page_ref"})

# Fallback only: classifies a number by its field NAME when the registry does not
# describe that field (unregistered fact_key or field). Registered fields declare
# their `kind` in src/verify/data/fact_keys.json instead.
_HEURISTIC_KEY_KINDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"evaluators|count|quota|capacity|persons"), "persons"),
    (re.compile(r"minutes"), "minutes"),
    (re.compile(r"words"), "words"),
    (re.compile(r"chars|characters"), "chars"),
    (re.compile(r"(^|_)page$"), "page_ref"),  # e.g. details_page: where in the source to look
    (re.compile(r"pages"), "pages"),
    (re.compile(r"(^|_)mb($|_)|megabytes"), "mb"),
    (re.compile(r"items"), "items"),
    (re.compile(r"yen|fee|amount|price|cost"), "yen"),
    (re.compile(r"ratio|rate"), "ratio"),
)


@dataclasses.dataclass(frozen=True)
class Quantity:
    kind: str  # persons minutes chars words pages mb items yen ratio | date date_noyear year_month entry_month year_* bare | range unclassified
    value: Any
    raw: str
    original: str = ""  # what the article wrote when `raw` is its canonical spelling (R8.8.6 -> 2026年8月6日)

    @property
    def shown(self) -> str:
        return f"{self.original}（＝{self.raw}）" if self.original else self.raw


@dataclasses.dataclass
class Expected:
    by_kind: dict[str, set[Any]]
    dates: set[tuple[str, tuple[int, int] | None]]  # (iso date, (h, m) | None)
    year_months: set[tuple[int, int]]
    entry_months: set[int]
    entry_years: set[int]
    exam_years: set[int]
    ordered_period: tuple[str, str] | None  # (start iso date, end iso date)
    any_numbers: set[Any]
    stages: set[int] = dataclasses.field(default_factory=set)  # 1 / 2 for first_stage* / second_stage* facts


# ---------------------------------------------------------------- helpers

def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


_kanji_to_int = kanji_to_int


def _num(s: str) -> float | int:
    s = s.replace(",", "")
    return float(s) if "." in s else int(s)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


# ------------------------------------------------- article-side extraction

_DATE_RE = re.compile(
    r"(?:令和(?P<ry>\d{1,2})|(?P<y>\d{4}))年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"
    r"(?:\((?P<wd>[月火水木金土日])\))?"
    r"(?:\s*(?P<h>\d{1,2}):(?P<mi>\d{2}))?"
)
_ISO_RE = re.compile(
    r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"
    r"(?:T(?P<h>\d{2}):(?P<mi>\d{2})(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?)?"
)
_NOYEAR_DATE_RE = re.compile(r"(?<![\d年])(?P<m>\d{1,2})月(?P<d>\d{1,2})日")
_YEAR_MONTH_RE = re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?!\d*日)")
_ENTRY_MONTH_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})月入学")
_YEAR_DEGREE_RE = re.compile(r"(?P<y>\d{4})年度(?P<role>に実施|実施|入学|入試)?")
_BARE_BEFORE_MARKER_RE = re.compile(r"(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?=\[EV-)")

_UNIT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("yen", re.compile(r"(?P<n>\d[\d,]*)万\s*(?P<low>\d[\d,]*)?\s*円")),  # special-cased below
    ("yen", re.compile(r"(?P<n>\d[\d,]*)\s*円")),
    ("persons", re.compile(r"(?P<n>\d[\d,]*)\s*(?:名|人)(?![気間物])")),
    ("minutes", re.compile(r"(?P<n>\d+)\s*分(?![野析類割担量配別])")),
    ("hours", re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*時間")),
    ("chars", re.compile(r"(?P<n>\d[\d,]*)\s*(?:文字|字)")),
    ("words", re.compile(r"(?P<n>\d[\d,]*)\s*(?:words?|ワード|単語|語)", re.I)),
    ("pages", re.compile(r"(?P<n>\d+)\s*(?:枚|ページ|頁)")),
    ("mb", re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?:メガバイト|MB)", re.I)),
    ("items", re.compile(r"(?P<n>\d+)\s*点")),
    ("ratio", re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?:倍|%)")),
)
_KANJI_UNIT_RE = re.compile(r"(?P<n>[〇一二三四五六七八九十百千万]+)\s*(?P<u>名|人|分|字|文字|枚|点|円)")
_KANJI_KIND = {"名": "persons", "人": "persons", "分": "minutes", "字": "chars", "文字": "chars", "枚": "pages", "点": "items", "円": "yen"}

_PAGE_REF_RE = re.compile(r"p\.\s*(?P<p>\d+(?:[・,、]\s*\d+)*)")
_ITEM_RANGE_RE = re.compile(r"\((?P<a>\d+)\)\s*[~〜～]\s*\((?P<b>\d+)\)")
# the ordinal of a selection stage: 第2次 / 2次選考, and the kanji spellings 第二次 / 二次選考 (a flipped ordinal written in kanji is the same mistake)
_STAGE_RE = re.compile(r"第(?P<a>\d+|[一二])次(?!世界|産業|性|元|情報)|(?<![\d第一二])(?P<b>\d+|[一二])次選考")
_KANJI_ORDINAL = {"一": 1, "二": 2}


def _ordinal_value(token: str) -> int:
    return int(token) if token.isdigit() else _KANJI_ORDINAL[token]
_PAPER_RE = re.compile(r"(?<![A-Za-z])A(?P<n>\d)(?!\d)")  # \b would not fire before Japanese text

# numbers that are neither facts nor checkable references
_STRIP_RES = (
    re.compile(r"https?://\S+"),
    re.compile(r"\(\d+\)"),  # list numbering such as (1)
    re.compile(r"作業基準日:\s*\d{4}-\d{2}-\d{2}"),  # the draft's own as-of date: no evidence exists for it
)


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _URL_SUB(text: str) -> str:
    return re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), text)


def _is_per_person(text: str, m: re.Match[str]) -> bool:
    """"一人30分", "1人あたり": a per-person unit, not a head count."""
    if m.group("n") not in ("1", "一"):
        return False
    return bool(re.match(r"\s*(?:\d|[一二三四五六七八九十]|あたり|当たり|ずつ)", text[m.end():]))


def extract_quantities(sentence: str, include_unclassified: bool = False) -> list[tuple[int, Quantity]]:
    """All checkable quantities in one sentence, as (position, Quantity). With `include_unclassified`, the digits no
    classifier understood come back as kind "unclassified" (reported by the article check, never checked)."""
    norm = normalize_notation(sentence)  # R8.8.6 / 十月八日 / 令和8年度 ... -> one canonical spelling (Issue #13)
    text = norm.text
    out: list[tuple[int, Quantity]] = []
    bare_spans = []
    for m in _BARE_BEFORE_MARKER_RE.finditer(text):
        out.append((m.start(), Quantity("bare", _num(m.group("n")), m.group(0).strip())))
        bare_spans.append((m.start(), m.start() + len(m.group("n"))))
    text = _CITATION_RE.sub(lambda m: " " * len(m.group(0)), text)
    for a, b in bare_spans:
        text = _blank(text, a, b)
    text = _URL_SUB(text)
    for m in list(_PAGE_REF_RE.finditer(text)):
        for page in re.split(r"[・,、]\s*", m.group("p")):
            out.append((m.start(), Quantity("page_ref", int(page), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for m in list(_ITEM_RANGE_RE.finditer(text)):
        out.append((m.start(), Quantity("item_range", (int(m.group("a")), int(m.group("b"))), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for m in list(_STAGE_RE.finditer(text)):
        out.append((m.start(), Quantity("stage", _ordinal_value(m.group("a") or m.group("b")), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for m in list(_PAPER_RE.finditer(text)):
        out.append((m.start(), Quantity("paper", int(m.group("n")), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for pattern in _STRIP_RES:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)

    for regex, iso in ((_DATE_RE, False), (_ISO_RE, True)):
        for m in list(regex.finditer(text)):
            if iso:
                year = int(m.group("y"))
            else:
                year = int(m.group("ry")) + 2018 if m.group("ry") else int(m.group("y"))
            try:
                day = datetime.date(year, int(m.group("m")), int(m.group("d")))
            except ValueError:
                out.append((m.start(), Quantity("date", ("invalid", None), m.group(0))))
                text = _blank(text, m.start(), m.end())
                continue
            time = (int(m.group("h")), int(m.group("mi"))) if m.group("h") else None
            wd = m.groupdict().get("wd")
            out.append((m.start(), Quantity("date", (day.isoformat(), time), m.group(0).strip())))
            if wd and _WEEKDAYS[day.weekday()] != wd:
                out.append((m.start(), Quantity("weekday", (day.isoformat(), wd), m.group(0).strip())))
            text = _blank(text, m.start(), m.end())

    for m in list(_NOYEAR_DATE_RE.finditer(text)):
        out.append((m.start(), Quantity("date_noyear", (int(m.group("m")), int(m.group("d"))), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for m in list(_YEAR_MONTH_RE.finditer(text)):
        out.append((m.start(), Quantity("year_month", (int(m.group("y")), int(m.group("m"))), m.group(0))))
        text = _blank(text, m.start(), m.end())
    for m in list(_ENTRY_MONTH_RE.finditer(text)):
        out.append((m.start(), Quantity("entry_month", int(m.group("m")), m.group(0))))
        text = _blank(text, m.start(), m.start() + len(m.group("m")) + 1)
    for m in list(_YEAR_DEGREE_RE.finditer(text)):
        role = {"入学": "entry", "入試": "entry", "に実施": "exam", "実施": "exam"}.get(m.group("role"), "any")
        out.append((m.start(), Quantity("year_" + role, int(m.group("y")), m.group(0))))
        text = _blank(text, m.start(), m.end())

    for r in find_ranges(text):  # 800〜1000字, 2〜3枚: both ends are checked, not just the one next to the unit
        out.append((r.start, Quantity("range", (r.kind, r.lo, r.hi), r.raw)))
        text = _blank(text, r.start, r.end)

    for m in list(_KANJI_UNIT_RE.finditer(text)):
        n = _kanji_to_int(m.group("n"))
        if m.group("u") in ("名", "人") and _is_per_person(text, m):
            text = _blank(text, m.start(), m.end())
        elif n is not None:
            out.append((m.start(), Quantity(_KANJI_KIND[m.group("u")], n, m.group(0))))
            text = _blank(text, m.start(), m.end())

    for kind, regex in _UNIT_PATTERNS:
        for m in list(regex.finditer(text)):
            if kind == "persons" and _is_per_person(text, m):
                text = _blank(text, m.start(), m.end())
                continue
            value: Any = _num(m.group("n"))
            out_kind = kind
            if kind == "yen" and "low" in regex.groupindex:  # 1万2000円
                value = int(value) * 10000 + (int(m.group("low").replace(",", "")) if m.group("low") else 0)
            elif kind == "hours":
                out_kind, value = "minutes", round(float(value) * 60)
            out.append((m.start(), Quantity(out_kind, value, m.group(0))))
            text = _blank(text, m.start(), m.end())
    for u in (unclassified_numbers(text) if include_unclassified else []):  # whatever is left: reported, never guessed into a quantity
        out.append((u.start, Quantity("unclassified", u.raw, u.raw, original=u.hint)))
    out = [(pos, dataclasses.replace(q, original=norm.originals[q.raw.strip()])
            if q.raw.strip() in norm.originals and q.kind != "unclassified" else q) for pos, q in out]
    return sorted(out, key=lambda t: t[0])


# ------------------------------------------------ evidence-side expectation

def _walk(value: Any, key: str, exp: Expected, fields: dict[str, dict[str, Any]] | None = None) -> None:
    """`fields` is the registry's description of the record's value fields (may be
    empty for an unregistered fact_key). A number whose field is registered with a
    `kind` is classified by the registry; any other number falls back to the
    name-based hints, so unregistered data is still checked, never skipped."""
    fields = fields or {}
    if isinstance(value, dict):
        if isinstance(value.get("date"), str) and isinstance(value.get("time"), str):
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", value["time"])
            if m:
                exp.dates.add((value["date"], (int(m.group(1)), int(m.group(2)))))
        for k, v in value.items():
            _walk(v, str(k), exp, fields)
        start, end = value.get("start"), value.get("end")
        if isinstance(start, str) and isinstance(end, str):
            exp.ordered_period = (start[:10], end[:10])
        return
    if isinstance(value, list):
        for v in value:
            _walk(v, key, exp, fields)
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        exp.any_numbers.add(value)
        spec = fields.get(key) or {}
        if spec.get("role") == "entry_months" or "month" in key:
            exp.entry_months.add(int(value))
        if spec.get("paper_size"):
            exp.by_kind.setdefault("paper", set()).add(int(spec["paper_size"]))
        else:
            paper = re.search(r"(?:^|_)a(\d)(?:_|$)", key.lower())
            if paper:  # free_format_a4_pages_max -> A4
                exp.by_kind.setdefault("paper", set()).add(int(paper.group(1)))
        if spec.get("kind"):
            exp.by_kind.setdefault(spec["kind"], set()).add(value)
        else:
            for pattern, kind in _HEURISTIC_KEY_KINDS:
                if pattern.search(key.lower()):
                    exp.by_kind.setdefault(kind, set()).add(value)
                    break
        return
    if isinstance(value, str):
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?)?", value)
        if m:
            time = (int(m.group(4)), int(m.group(5))) if m.group(4) else None
            exp.dates.add((f"{m.group(1)}-{m.group(2)}-{m.group(3)}", time))
            exp.exam_years.add(int(m.group(1)))
            return
        m = re.fullmatch(r"(\d{4})-(\d{2})", value)
        if m:
            exp.year_months.add((int(m.group(1)), int(m.group(2))))
            exp.entry_months.add(int(m.group(2)))
            return
        held = re.search(r"held_in_(\d{4})", value)
        if held:
            exp.exam_years.add(int(held.group(1)))
        span = re.search(r"_of_1_to_(\d+)", value)  # logic: any_of_1_to_3
        if span:
            exp.by_kind.setdefault("item_range", set()).add(int(span.group(1)))


def expected_from_evidence(evidence: dict[str, Any], registry: Registry | None = None) -> Expected:
    registry = registry or get_registry()
    exp = Expected({}, set(), set(), set(), set(), set(), None, set())
    if isinstance(evidence.get("fiscal_year"), int):
        exp.entry_years.add(evidence["fiscal_year"])
    fact_key = str(evidence.get("fact_key") or "")
    if registry.lookup(fact_key):
        stage = registry.stage(fact_key)
        if stage:
            exp.stages.add(stage)
    elif fact_key.startswith("first_stage"):  # unregistered: keep the old name-based hint
        exp.stages.add(1)
    elif fact_key.startswith("second_stage"):
        exp.stages.add(2)
    # optional, per record (Issue #12): the selection stage(s) this record's sentences refer to — the same fact_key
    # (interview, ...) serves either stage. An int or a list; 'final' means no ordinal is checked.
    record_stage = evidence.get("stage")
    for s in record_stage if isinstance(record_stage, list) else [record_stage]:
        if s in (1, 2) and not isinstance(s, bool):
            exp.stages.add(s)
    for proof in evidence.get("proofs") or []:
        if isinstance(proof, dict) and isinstance(proof.get("page"), int):
            exp.by_kind.setdefault("page_ref", set()).add(proof["page"])
    if isinstance(evidence.get("quota"), int) and not isinstance(evidence["quota"], bool):
        exp.by_kind.setdefault("persons", set()).add(evidence["quota"])
        exp.any_numbers.add(evidence["quota"])
    if "value" in evidence:
        _walk(evidence["value"], "value", exp, registry.fields(fact_key))
    for iso, _ in exp.dates:
        exp.exam_years.add(int(iso[:4]))
    return exp


def _merge(expecteds: list[Expected]) -> Expected:
    merged = Expected({}, set(), set(), set(), set(), set(), None, set())
    for e in expecteds:
        for k, v in e.by_kind.items():
            merged.by_kind.setdefault(k, set()).update(v)
        merged.dates |= e.dates
        merged.year_months |= e.year_months
        merged.entry_months |= e.entry_months
        merged.entry_years |= e.entry_years
        merged.exam_years |= e.exam_years
        merged.any_numbers |= e.any_numbers
        merged.stages |= e.stages
        merged.ordered_period = merged.ordered_period or e.ordered_period
    return merged


# ------------------------------------------------------------- the check

def _sentences(paragraph: str) -> list[str]:
    parts: list[str] = []
    for line in paragraph.split("\n"):
        for piece in re.split(r"(?<=。)", line):
            if piece.strip():
                parts.append(piece)
    return parts


def _contexts(sentences: list[str]) -> list[set[str]]:
    """Citation ids governing each sentence: its own, else the nearest cited
    sentence in the same paragraph (previous preferred, then following)."""
    own = [set(_CITATION_RE.findall(s)) for s in sentences]
    result: list[set[str]] = []
    for i, ids in enumerate(own):
        if ids:
            result.append(ids)
            continue
        chosen: set[str] = set()
        for j in range(i - 1, -1, -1):
            if own[j]:
                chosen = own[j]
                break
        if not chosen:
            for j in range(i + 1, len(own)):
                if own[j]:
                    chosen = own[j]
                    break
        result.append(chosen)
    return result


def _unclassified_notice(q: Quantity, exp: Expected, resolved: list[str]) -> ConsistencyIssue:
    """A number the QA could not classify. It is not checked; say so, and whether the cited evidence has the same number."""
    raw = str(q.value)
    where = ""
    if resolved and "/" not in raw:
        where = ("；引用した根拠にも同じ数値がある（意味は未確認）" if any(_same(_num(raw), n) for n in exp.any_numbers)
                 else "；引用した根拠にこの数値は無い")
    return ConsistencyIssue("unclassified_number", f"{raw!r}: {q.original}{where}")


def _check_quantity(
    q: Quantity, exp: Expected, claim: dict[str, Any], cited_ids: set[str]
) -> ConsistencyIssue | None:
    label = ",".join(sorted(cited_ids))
    kind = q.kind
    if kind == "weekday":
        return ConsistencyIssue("weekday_mismatch", f"{q.raw!r}: the weekday does not match that calendar date")
    if kind == "date":
        iso, time = q.value
        if iso == "invalid":
            return ConsistencyIssue("date_mismatch", f"{q.raw!r} is not a real calendar date")
        same_day = [e for e in exp.dates if e[0] == iso]
        if not same_day:
            return ConsistencyIssue(
                "date_mismatch", f"article says {iso} ({q.raw!r}); cited {label} has {sorted(d for d, _ in exp.dates) or 'no dates'}"
            )
        if time is not None and not any(e[1] == time for e in same_day):
            known = sorted({str(e[1]) for e in same_day})
            return ConsistencyIssue(
                "time_mismatch", f"article gives time {time[0]:02d}:{time[1]:02d} for {iso}; cited {label} has {known}"
            )
        return None
    if kind == "date_noyear":
        m, d = q.value
        if not any(int(e[0][5:7]) == m and int(e[0][8:10]) == d for e in exp.dates):
            return ConsistencyIssue("date_mismatch", f"{q.raw!r} matches no date in cited {label}")
        return None
    if kind == "year_month":
        y, m = q.value
        if (y, m) not in exp.year_months and not any(e[0][:7] == f"{y:04d}-{m:02d}" for e in exp.dates):
            return ConsistencyIssue("date_mismatch", f"{q.raw!r} matches no year-month in cited {label}")
        return None
    if kind == "entry_month":
        if q.value not in exp.entry_months and not any(m == q.value for _, m in exp.year_months):
            return ConsistencyIssue("entry_month_mismatch", f"{q.raw!r}: cited {label} gives entry months {sorted(exp.entry_months)}")
        return None
    if kind == "year_entry":
        allowed = exp.entry_years | ({claim["fiscal_year"]} if isinstance(claim.get("fiscal_year"), int) else set())
        if q.value not in allowed:
            return ConsistencyIssue("entry_year_mismatch", f"{q.raw!r} is not the entry year {sorted(allowed)} of the cited evidence")
        return None
    if kind == "year_exam":
        if q.value not in exp.exam_years:
            return ConsistencyIssue(
                "exam_year_mismatch", f"{q.raw!r}: cited {label} places the exam/event year at {sorted(exp.exam_years) or 'nothing'}"
            )
        return None
    if kind == "year_any":
        if q.value not in exp.entry_years | exp.exam_years:
            return ConsistencyIssue("year_mismatch", f"{q.raw!r} is neither the entry nor the exam year of cited {label}")
        return None
    if kind == "range":
        unit, lo, hi = q.value
        have = exp.by_kind.get(unit)
        if have is None:
            return ConsistencyIssue("quantity_not_in_evidence", f"{q.shown!r} ({unit}) is not a value of cited {label}; evidence has no {unit} value")
        missing = [n for n in (lo, hi) if not any(_same(n, v) for v in have)]
        if len(missing) == 2 or (missing and not any(_same(hi, v) for v in have)):
            return ConsistencyIssue("quantity_mismatch", f"article says {q.shown!r}; cited {label} says {sorted(have)} ({unit})")
        return None  # the other end is not in the evidence: reported as a notice by range_notices()
    if kind == "bare":
        if not any(_same(q.value, n) for n in exp.any_numbers):
            return ConsistencyIssue("quantity_not_in_evidence", f"number {q.raw!r} next to a citation is not a value of cited {label}")
        return None
    if kind == "stage":
        if exp.stages and q.value not in exp.stages:
            return ConsistencyIssue("stage_mismatch", f"{q.raw!r}: cited {label} concerns selection stage {sorted(exp.stages)}")
        return None
    if kind == "item_range":
        first, last = q.value
        have = exp.by_kind.get("item_range")
        if have is None:
            return ConsistencyIssue("quantity_not_in_evidence", f"{q.raw!r} is not backed by cited {label} (no item range recorded)")
        if first != 1 or last not in have:
            return ConsistencyIssue("item_range_mismatch", f"{q.raw!r}: cited {label} says items 1..{sorted(have)}")
        return None
    if kind in ("page_ref", "paper"):
        have = exp.by_kind.get(kind)
        what = "page" if kind == "page_ref" else "paper size"
        if have is None:
            return ConsistencyIssue("quantity_not_in_evidence", f"{what} {q.raw!r} is not recorded in cited {label}")
        if q.value not in have:
            category = "page_reference_mismatch" if kind == "page_ref" else "paper_size_mismatch"
            return ConsistencyIssue(category, f"{q.raw!r}: cited {label} records {what} {sorted(have)}")
        return None
    have = exp.by_kind.get(kind)
    if have is None:
        return ConsistencyIssue(
            "quantity_not_in_evidence",
            f"{q.raw!r} ({kind}) is not a value of cited {label}; evidence has no {kind} value, so it is not filled in",
        )
    if not any(_same(q.value, v) for v in have):
        return ConsistencyIssue(
            "quantity_mismatch", f"article says {q.raw!r}; cited {label} says {sorted(have)} ({kind})"
        )
    return None


def _has_negation(sentence: str, registry: Registry) -> bool:
    return any(token in sentence for token in registry.negation_cues)


def _apply_rule(rule: dict[str, Any], eid: str, evidence: dict[str, Any], paragraph: str,
                sentences: list[str], registry: Registry) -> list[ConsistencyIssue]:
    """One registered rule. The *wording cues* (合計 / 枠 / いずれか ...) come from the
    registry; the engines below are the only code."""
    category = rule["category"]
    issues: list[ConsistencyIssue] = []
    if rule.get("engine") == "dates_listed":
        value = evidence.get("value") if isinstance(evidence.get("value"), dict) else {}
        listed = [d for d in value.get("dates", []) if isinstance(d, str)] if isinstance(value.get("dates"), list) else []
        if len(listed) >= 2:
            stated = {q.value[0] for _, q in extract_quantities(paragraph) if q.kind == "date"}
            missing = [d for d in listed if d not in stated]
            if stated and missing:
                issues.append(ConsistencyIssue(category, f"{eid} lists {listed}; the text leaves out {missing}"))
        return issues
    if rule.get("required_any") and not any(w in paragraph for w in rule["required_any"]):
        issues.append(ConsistencyIssue(category, f"{eid} {rule['required_message']}"))
    if rule.get("required_any_pattern") and not re.search("|".join(rule["required_any_pattern"]), paragraph):
        issues.append(ConsistencyIssue(category, f"{eid} {rule['required_message']}"))
    for s in sentences:
        if any(w in s for w in rule.get("forbidden_unless_negated", ())) and not _has_negation(s, registry):
            issues.append(ConsistencyIssue(category, f"{eid} {rule['forbidden_message']}: {s.strip()[:40]!r}"))
    for pattern in rule.get("forbidden_patterns", ()):
        if re.search(pattern, paragraph):
            issues.append(ConsistencyIssue(category, f"{eid} {rule['forbidden_message']}"))
    return issues


def _semantic_issues(paragraph: str, sentences: list[str], contexts: list[set[str]],
                     evidence_by_id: dict[str, dict[str, Any]], registry: Registry) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    seen: set[tuple[str, str]] = set()
    for ids in contexts:
        for eid in ids:
            evidence = evidence_by_id.get(eid)
            if not evidence or (eid, paragraph) in seen:
                continue
            seen.add((eid, paragraph))
            # triggered by the evidence's CONTENT, so these protections also apply to
            # an unregistered fact_key (which is additionally reported as unregistered)
            for _name, rule in registry.triggered_rules(evidence):
                issues.extend(_apply_rule(rule, eid, evidence, paragraph, sentences, registry))
    return issues


def _period_issues(sentence: str, quantities: list[tuple[int, Quantity]], exp: Expected) -> list[ConsistencyIssue]:
    """A range written "A〜B" must be exactly the evidence's (start, end), in
    that order — not merely two dates that each exist somewhere in the evidence."""
    if exp.ordered_period is None:
        return []
    start, end = exp.ordered_period
    items: list[tuple[int, int, str]] = []
    year = None
    for pos, q in quantities:
        iso = None
        if q.kind == "date" and q.value[0] != "invalid":
            iso = q.value[0]
            year = int(iso[:4])
        elif q.kind == "date_noyear" and year is not None:
            try:
                iso = datetime.date(year, *q.value).isoformat()
            except ValueError:
                iso = None
        if iso:
            items.append((pos, pos + len(q.raw), iso))
    issues = []
    for (_, a_end, a_iso), (b_pos, _, b_iso) in zip(items, items[1:]):
        between = sentence[a_end:b_pos]
        if len(between) <= 8 and re.search(r"[~〜～]|から", between):
            if (a_iso, b_iso) == (end, start):
                issues.append(ConsistencyIssue("period_order_mismatch", f"period written end-before-start: {end}..{start}"))
            elif (a_iso, b_iso) != (start, end):
                issues.append(ConsistencyIssue("period_mismatch", f"article's period {a_iso}..{b_iso} is not the evidence's {start}..{end}"))
    return issues


# A paragraph that cites evidence about X must actually talk about X. This catches
# a citation id that was swapped for a different *real* record, which no value
# check can see when the sentence carries no number. The keywords per fact_key
# live in the registry (src/verify/data/fact_keys.json); a fact_key the registry
# does not know imposes no topic constraint — and is reported as unregistered.
def _topic_issues(paragraph: str, contexts: list[set[str]], evidence_by_id: dict[str, dict[str, Any]],
                  registry: Registry) -> list[ConsistencyIssue]:
    """Every evidence a paragraph cites must have a cue of its fact_key in that paragraph.
    A sentence citing two evidences is held to both (one claim, one evidence: docs/STRICT_VALIDATION.md)."""
    issues: list[ConsistencyIssue] = []
    seen: set[str] = set()
    for ids in contexts:
        for eid in ids:
            key = (evidence_by_id.get(eid) or {}).get("fact_key")
            if eid in seen or registry.cue_match(key, paragraph) is not False:
                continue
            seen.add(eid)
            spec = registry.lookup(key) or {}
            shown = [c[3:] if c.startswith("re:") else c for c in (spec.get("cues") or spec.get("topic_keywords") or [])][:4]
            issues.append(ConsistencyIssue(
                "citation_topic_mismatch",
                f"{eid} is about {key!r}, but its paragraph contains none of its cues {shown}: the citation may belong to another fact"))
    return issues


_SOURCE_LINE_RE = re.compile(r"\[(?P<eid>EV-[A-Za-z0-9_\-]+)\].*?PDF\s*p\.\s*(?P<pages>\d+(?:[・,、]\s*\d+)*)(?P<rest>.*)")


def _source_list_issues(text: str, evidence_by_id: dict[str, dict[str, Any]]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for line in _normalize(text).split("\n"):
        m = _SOURCE_LINE_RE.search(line)
        if not m or m.group("eid") not in evidence_by_id:
            continue
        evidence = evidence_by_id[m.group("eid")]
        pages = {int(p) for p in re.split(r"[・,、]\s*", m.group("pages"))}
        proof_pages = {p["page"] for p in evidence.get("proofs", []) if isinstance(p, dict) and "page" in p}
        if proof_pages and pages != proof_pages:
            issues.append(ConsistencyIssue(
                "source_page_mismatch", f"{m.group('eid')}: source list says p.{sorted(pages)}, evidence proofs are on p.{sorted(proof_pages)}"))
        url = re.search(r"https?://[^\s#)）]+", m.group("rest"))
        if url and evidence.get("source_url") and url.group(0) != evidence["source_url"]:
            issues.append(ConsistencyIssue(
                "source_url_mismatch", f"{m.group('eid')}: source list URL differs from the evidence record's source_url"))
    return issues


def paragraphs_with_citations(text: str) -> list[tuple[str, list[str], list[set[str]]]]:
    """(paragraph, its sentences, the citation ids governing each sentence) for every body
    paragraph. Source-list lines are left out. Shared by the as-of date checks (src/verify/as_of.py)
    and the qualitative checks (src/verify/qualitative.py)."""
    out: list[tuple[str, list[str], list[set[str]]]] = []
    for raw_paragraph in re.split(r"\n\s*\n", text):
        body_lines = [ln for ln in raw_paragraph.split("\n") if not _SOURCE_LINE_RE.search(_normalize(ln))]
        paragraph = _normalize("\n".join(body_lines))
        if paragraph.strip():
            sentences = _sentences(paragraph)
            out.append((paragraph, sentences, _contexts(sentences)))
    return out


def sentences_with_citations(text: str) -> list[tuple[str, set[str]]]:
    """Every body sentence of an article with the citation ids that govern it (its own,
    else the nearest cited sentence of the same paragraph)."""
    return [pair for _p, sentences, contexts in paragraphs_with_citations(text) for pair in zip(sentences, contexts)]


def check_article_strict(text: str, claim: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]],
                         registry: Registry | None = None, notices: list[ConsistencyIssue] | None = None) -> list[ConsistencyIssue]:
    """All strict findings for one article (see module docstring).

    `notices` (optional) receives what was NOT checked rather than wrong: numbers the QA could not
    classify (`unclassified_number`) and a range end the evidence does not record (`range_end_unverified`).
    They never fail an article."""
    issues: list[ConsistencyIssue] = []
    notes = notices if notices is not None else []
    markers = _CITATION_RE.findall(_normalize(text))
    for unknown in sorted({m for m in markers if m not in evidence_by_id}):
        # also catches ids that sit nowhere near a number (the older check only looks next to numbers)
        issues.append(ConsistencyIssue("unknown_citation", f"citation {unknown!r} does not resolve to a known evidence record"))
    all_cited = {eid for eid in markers if eid in evidence_by_id}
    registry = registry or get_registry()
    article_level = _merge([expected_from_evidence(evidence_by_id[e], registry) for e in all_cited])

    for raw_paragraph in re.split(r"\n\s*\n", text):
        # source-list lines ("- [EV-x] ... PDF p.5：URL") are checked on their own below
        body_lines = [ln for ln in raw_paragraph.split("\n") if not _SOURCE_LINE_RE.search(_normalize(ln))]
        paragraph = _normalize("\n".join(body_lines))
        if not paragraph.strip():
            continue
        sentences = _sentences(paragraph)
        contexts = _contexts(sentences)
        for sentence, ids in zip(sentences, contexts):
            resolved = [e for e in ids if e in evidence_by_id]
            if ids and not resolved:
                continue  # unknown citation: already reported by the older check
            exp = _merge([expected_from_evidence(evidence_by_id[e], registry) for e in resolved]) if resolved else article_level
            sentence = normalize_notation(sentence).text  # same spelling the quantities were found in
            quantities = extract_quantities(sentence, include_unclassified=True)
            for pos, q in quantities:
                if q.kind == "unclassified":
                    if not paragraph.lstrip().startswith("#"):  # a heading names the programme ("2026夏秋AO入試"), it asserts nothing
                        notes.append(_unclassified_notice(q, exp, resolved))
                    continue
                if q.kind == "range" and resolved:
                    unit, lo, hi = q.value
                    have = exp.by_kind.get(unit) or set()
                    if have and any(_same(hi, v) for v in have) and not any(_same(lo, v) for v in have):
                        notes.append(ConsistencyIssue(
                            "range_end_unverified", f"{q.shown!r}: the upper end is backed by {','.join(sorted(resolved))}, the lower end {lo} is not recorded there"))
                q = dataclasses.replace(q, raw=q.shown, original="") if q.original else q  # messages quote what the article wrote
                if not resolved:
                    if q.kind in ("persons", "bare"):
                        continue  # reported as unsupported_number by the older check
                    if q.kind in ("year_entry", "year_any", "year_exam"):
                        issue = _check_quantity(q, article_level, claim, all_cited)
                    else:
                        issue = ConsistencyIssue("uncited_quantity", f"{q.raw!r} ({q.kind}) appears with no citation")
                else:
                    issue = _check_quantity(q, exp, claim, set(resolved))
                if issue:
                    issues.append(issue)
            if resolved:
                issues.extend(_period_issues(sentence, quantities, exp))
        issues.extend(_semantic_issues(paragraph, sentences, contexts, evidence_by_id, registry))
        issues.extend(_topic_issues(paragraph, contexts, evidence_by_id, registry))
    issues.extend(_source_list_issues(text, evidence_by_id))
    return issues
