"""Report-only context for the duplication findings of the article QA (contract: docs/QA_DUPLICATION_CONTEXT_CONTRACT.md, version duplication-context-v1).

What this module is: an EXPLANATION layer. For every repeated phrase that `checks.find_overused_phrases` reports it says WHERE the phrase stands in the articles: in a registered mandatory notice, a registered
heading, a source-list item (by its syntax), a fact sentence that cites evidence, ordinary prose, or across a line break. For a pair of near-duplicate articles it says whether the similarity comes
from the scaffold or from the prose. It never decides pass or fail: the gate stays `find_overused_phrases` (12 characters, 5 articles) and `find_near_duplicates` (5-shingles, 0.8), unchanged.
A repeat is "scaffold only" only when EVERY occurrence of it is a whole registered line or a source-list item; one occurrence in prose makes it "uncovered" and it stays a finding.

The registry (`rules`) is a versioned dict, loaded with `load_rules`: every entry names one exact line (whitespace-insensitive), why it must be fixed text, which contract item requires it and who approved
it. No pattern, no wildcard, no "everything that looks like a notice". The registry is written and reviewed on the QA side, not by the producer of the articles it checks.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import unicodedata
from collections import Counter, defaultdict

from src.article_qa import checks

CONTRACT_VERSION = "duplication-context-v1"
KINDS_REGISTERED = ("mandatory_notice", "heading")
_SOURCE_ITEM = re.compile(r"^[-*]\s*\[EV-[A-Za-z0-9_-]+\]\s[^。]*$")  # a list entry that names an evidence id and has no sentence in it
_CITES = re.compile(r"\[EV-[A-Za-z0-9_-]+\]")


class RuleError(ValueError):
    pass


def _flat(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def _gate_flat(text: str) -> str:
    """The normalisation of the gate (`checks.find_overused_phrases`): whitespace removed, nothing else. The windows must be cut exactly as the gate cuts them."""
    return re.sub(r"\s+", "", text)


def load_rules(rules: dict) -> dict:
    """Validate a registry and return {"version", "sha256", "lines": {flat line: entry}}. Refuses an entry without a reason, a contract reference or an approver, a short or duplicated line,
    a kind that is not registered, and any registry that claims thresholds (the thresholds are not the registry's to change)."""
    if not isinstance(rules, dict) or set(rules) - {"version", "entries"} or not isinstance(rules.get("version"), str) or not rules["version"] or not isinstance(rules.get("entries"), list):
        raise RuleError("a registry is {version, entries} and nothing else (no thresholds, no patterns)")
    lines: dict[str, dict] = {}
    for e in rules["entries"]:
        if not isinstance(e, dict) or set(e) != {"id", "kind", "text", "rationale", "contract_ref", "approved_by"}:
            raise RuleError("an entry is exactly {id, kind, text, rationale, contract_ref, approved_by}")
        if e["kind"] not in KINDS_REGISTERED:
            raise RuleError(f"{e.get('id')}: kind must be one of {KINDS_REGISTERED}")
        if not all(isinstance(e[k], str) and e[k].strip() for k in ("id", "text", "rationale", "contract_ref", "approved_by")):
            raise RuleError(f"{e.get('id')}: id, text, rationale, contract_ref and approved_by must be non-empty text")
        flat = _flat(e["text"])
        if len(flat) < (12 if e["kind"] == "mandatory_notice" else 2):
            raise RuleError(f"{e['id']}: a registered notice shorter than the 12-character window would exclude ordinary words")
        if flat in lines:
            raise RuleError(f"{e['id']}: the same line is registered twice")
        lines[flat] = e
    digest = hashlib.sha256(json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"version": rules["version"], "sha256": digest, "lines": lines}


def line_kind(line: str, rules: dict) -> str:
    """heading_registered | mandatory_notice | source_item | cited_fact_sentence | heading_unregistered | prose | blank. Only the first three are scaffold."""
    s = line.strip()
    if not s:
        return "blank"
    entry = rules["lines"].get(_flat(s.lstrip("#").strip() if s.startswith("#") else s))
    if s.startswith("#"):
        return "heading_registered" if entry and entry["kind"] == "heading" else "heading_unregistered"
    if entry and entry["kind"] == "mandatory_notice":
        return "mandatory_notice"
    if _SOURCE_ITEM.match(s):
        return "source_item"
    if _CITES.search(s):
        return "cited_fact_sentence"
    return "prose"


SCAFFOLD = ("heading_registered", "mandatory_notice", "source_item")


def _spans(text: str, rules: dict):
    """(flat text, per-character kind list, per-character line number) of one article."""
    flat, kinds, lineno = [], [], []
    for n, line in enumerate(text.splitlines()):
        k = line_kind(line, rules)
        for c in _gate_flat(line):
            flat.append(c)
            kinds.append(k)
            lineno.append(n)
    return "".join(flat), kinds, lineno


def classify_repeats(articles: dict[str, str], rules: dict, phrase_len: int = 12, min_occurrences: int = 5) -> dict:
    """The same repeats as `find_overused_phrases` (same window, same count, same normalisation), each with the kinds of its occurrences. `scaffold_only` is True only if every occurrence
    lies inside one scaffold line; a window that crosses a line break is "cross_line" and is never scaffold."""
    seen: dict[str, list[tuple[str, str]]] = defaultdict(list)
    per_article = {aid: _spans(text, rules) for aid, text in articles.items()}
    for aid, (flat, kinds, lineno) in per_article.items():
        done = set()
        for i in range(max(0, len(flat) - phrase_len + 1)):
            ph = flat[i:i + phrase_len]
            if ph in done:
                continue
            done.add(ph)
            window = set(lineno[i:i + phrase_len])
            kind = "cross_line" if len(window) > 1 else kinds[i]
            seen[ph].append((aid, kind))
    repeats = []
    for ph, occ in seen.items():
        if len(occ) >= min_occurrences:
            kinds = Counter(k for _, k in occ)
            repeats.append({"phrase": ph, "articles": len(occ), "kinds": dict(kinds), "scaffold_only": all(k in SCAFFOLD for k in kinds)})
    summary = Counter("scaffold_only" if r["scaffold_only"] else "uncovered" for r in repeats)
    return {"contract": CONTRACT_VERSION, "rules_version": rules["version"], "rules_sha256": rules["sha256"], "phrase_len": phrase_len, "min_occurrences": min_occurrences,
            "total": len(repeats), "scaffold_only": summary["scaffold_only"], "uncovered": summary["uncovered"], "repeats": repeats}


def gate_unchanged(articles: dict[str, str], rules: dict) -> bool:
    """The report counts the same repeats as the gate (a self-check used by tests and by the reporter)."""
    gate = {ast.literal_eval(f.detail.rsplit(" appears verbatim", 1)[0]) for f in checks.find_overused_phrases(articles)}
    return gate == {r["phrase"] for r in classify_repeats(articles, rules)["repeats"]}


def thresholds_are_the_gates() -> bool:
    d = inspect.signature(checks.find_overused_phrases).parameters
    c = inspect.signature(classify_repeats).parameters
    return (d["phrase_len"].default, d["min_occurrences"].default) == (c["phrase_len"].default, c["min_occurrences"].default)


def similarity_profile(text_a: str, text_b: str, rules: dict, k: int = 5) -> dict:
    """The near-duplicate score of the whole articles (the gate's number) next to the score of their prose and fact sentences only. A high whole score with a low prose score is
    scaffold-driven; a high prose score is substantive (two articles say the same thing). The gate is the whole score."""
    def body(text):
        return "\n".join(l for l in text.splitlines() if line_kind(l, rules) in ("prose", "cited_fact_sentence", "heading_unregistered"))
    whole = checks.near_duplicate_score(text_a, text_b, k)
    prose = checks.near_duplicate_score(body(text_a), body(text_b), k)
    return {"whole": whole, "body_only": prose, "reading": "substantive" if prose >= 0.8 else ("scaffold_driven" if whole >= 0.8 else "below_threshold")}
