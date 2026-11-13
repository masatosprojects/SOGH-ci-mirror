"""Qualitative checks: meaning that carries no number — Issue #9.

Numbers, dates, units and scope are checked elsewhere. Here: a yes/no that flipped
("共通テストは不要" -> "必要"), a limit or exception that vanished or became an
unconditional claim ("延長する場合がある" -> "延長しない", "…に限り" -> unconditional),
a listed item left out.

How it stays honest:
* Rules are DATA in the fact_key registry (`assertions` per key, `qualitative_rules`
  for every record): when a value looks like THIS, the paragraph that cites it must say
  that and must not say the opposite. The wording lists live in the registry; this file
  is only the engine.
* A forbidden phrase is allowed when its own sentence negates it ("必須ではありません").
* What no rule covers is NEVER treated as correct: `semantic_coverage` lists, per article,
  the boolean values and qualifiers that were checked and those that were not.
"""
from __future__ import annotations

import re
from typing import Any

from src.verify.consistency import ConsistencyIssue, extract_citation_ids
from src.verify.fact_registry import Registry, get_registry
from src.verify.strict_claims import paragraphs_with_citations


def _alt(items: list[str]) -> str:
    return "(?:" + "|".join(i[3:] if i.startswith("re:") else re.escape(i) for i in items) + ")"


def _expand(patterns: list[str], registry: Registry) -> list[str]:
    """`lex:NAME` -> every item of that lexicon; `{lex:NAME}` inside a `re:` pattern -> an alternation of them."""
    lexicons = registry.data.get("lexicons", {})
    out: list[str] = []
    for pat in patterns:
        if pat.startswith("lex:"):
            out.extend(lexicons[pat[4:]])
        elif pat.startswith("re:") and "{lex:" in pat:
            out.append(re.sub(r"\{lex:([A-Za-z0-9_]+)\}", lambda m: _alt(lexicons[m.group(1)]), pat))
        else:
            out.append(pat)
    return out


def _hit(pattern: str, text: str) -> bool:
    return bool(re.search(pattern[3:], text)) if pattern.startswith("re:") else pattern in text


def _any(patterns: list[str], text: str) -> bool:
    return any(_hit(p, text) for p in patterns)


_REFERENCE_LINE = re.compile(r"^\s*(?:[-*]\s*\[EV-[A-Za-z0-9_\-]+\]|#)")


def _is_reference_list(paragraph: str) -> bool:
    """A bibliography block ("## 根拠資料" and "- [EV-x] label：url" lines) cites evidence but asserts nothing:
    the wording rules do not apply to it (PDF source lines are already left out of the paragraphs)."""
    lines = [ln for ln in paragraph.splitlines() if ln.strip()]
    return bool(lines) and all(_REFERENCE_LINE.match(ln) for ln in lines)


def _when_ok(when: dict[str, Any] | None, evidence: dict[str, Any]) -> bool:
    if not when:
        return True
    value = evidence.get("value")
    v = value.get(when["field"]) if isinstance(value, dict) else None
    if "equals" in when:
        return v is not None and v == when["equals"]
    if "nonempty" in when:
        return bool(v) == bool(when["nonempty"])
    if not isinstance(v, str):
        return False
    if "contains" in when:
        return when["contains"] in v
    if "regex" in when:
        return bool(re.search(when["regex"], v))
    return False


def assertions_for(evidence: dict[str, Any], registry: Registry) -> list[dict[str, Any]]:
    """Every assertion that could apply: the key's own, then the global qualitative rules
    (which apply to any record, registered fact_key or not)."""
    spec = registry.lookup(evidence.get("fact_key"))
    return [*(spec.get("assertions", []) if spec else []), *registry.data.get("qualitative_rules", [])]


def _apply(a: dict[str, Any], eid: str, evidence: dict[str, Any], paragraph: str, sentences: list[str],
           registry: Registry) -> list[ConsistencyIssue]:
    category = a.get("category", "polarity_mismatch")
    note = a.get("message", a["id"])
    issues: list[ConsistencyIssue] = []
    must = _expand(a.get("must_any", []), registry)
    forbid = _expand(a.get("forbid_any", []), registry)
    if must and not _any(must, paragraph):
        shown = [m[3:] if m.startswith("re:") else m for m in must][:3]
        issues.append(ConsistencyIssue(category, f"{eid}: {note}（必要な言い回しが無い: {shown}）"))
    for sentence in sentences:
        hit = next((f for f in forbid if _hit(f, sentence)), None)
        if hit and not (a.get("forbid_unless_negated", True) and any(c in sentence for c in registry.negation_cues)):
            issues.append(ConsistencyIssue(
                category, f"{eid}: {note}（禁止の言い回し「{hit[3:] if hit.startswith('re:') else hit}」: {sentence.strip()[:36]!r}）"))
    if a.get("sentence_if"):  # a sentence about the subject must keep its predicate (a closed class), whatever replaced it
        applies, keeps = _expand(a["sentence_if"], registry), _expand(a["sentence_must"], registry)
        for sentence in sentences:
            if _any(applies, sentence) and not _any(keeps, sentence):
                issues.append(ConsistencyIssue(category, f"{eid}: {note}（述語が保たれていない: {sentence.strip()[:36]!r}）"))
    field = a.get("echo_all_field")
    if field:
        items = (evidence.get("value") or {}).get(field)
        missing = [i for i in items if isinstance(i, str) and i not in paragraph] if isinstance(items, list) else []
        if missing:
            issues.append(ConsistencyIssue(category, f"{eid}: {note}（本文に無い項目: {missing}）"))
    return issues


def _sentence_rules(paragraph: str, sentences: list[str], registry: Registry) -> list[ConsistencyIssue]:
    """A boilerplate sentence ("最新情報は…確認してください", "個別判定は別途必要です") must keep its action. This guards its STRUCTURE,
    so a rewrite nobody listed ("…は済んでいます") is still caught."""
    out: list[ConsistencyIssue] = []
    for rule in registry.data.get("article_sentence_rules", []):
        applies, must = _expand(rule["applies_to"], registry), _expand(rule["must_any"], registry)
        for sentence in sentences:
            if _any(applies, sentence) and not _any(must, sentence):
                out.append(ConsistencyIssue(rule.get("category", "polarity_mismatch"), f"本文: {rule.get('message', rule['id'])}（{sentence.strip()[:36]!r}）"))
    return out


def check_qualitative(text: str, evidence_by_id: dict[str, dict[str, Any]], registry: Registry | None = None) -> list[ConsistencyIssue]:
    registry = registry or get_registry()
    issues: list[ConsistencyIssue] = []
    for paragraph, sentences, contexts in paragraphs_with_citations(text):
        if _is_reference_list(paragraph):
            continue
        for rule in registry.data.get("article_rules", []):  # boilerplate: no evidence needed
            issues.extend(_apply(rule, "本文", {}, paragraph, sentences, registry))
        issues.extend(_sentence_rules(paragraph, sentences, registry))
        seen: set[tuple[str, str]] = set()
        for eid in sorted(set().union(*contexts) if contexts else set()):
            evidence = evidence_by_id.get(eid)
            if not evidence:
                continue
            for a in assertions_for(evidence, registry):
                if (eid, a["id"]) in seen or not _when_ok(a.get("when"), evidence):
                    continue
                seen.add((eid, a["id"]))
                issues.extend(_apply(a, eid, evidence, paragraph, sentences, registry))
    return issues


_TERM_RUN = re.compile(r"[\u4e00-\u9fff\u30a0-\u30ff]{2,}")


def _anchors(assertion: dict[str, Any], registry: Registry) -> tuple[list[str], list[str]]:
    """What makes a sentence THE SUBJECT of an assertion -> (specific, lexical).
    specific: its regexes and plain phrases of 3+ characters. One- and two-character words ("使", "認め", "成績") occur
    everywhere and anchor nothing. lexical: the words of a lexicon it names ("免除", "必須"): they anchor a sentence only
    together with the topic of the cited fact (a duty to mail a letter is not about the common test)."""
    specific: list[str] = []
    lexical: list[str] = []
    for pat in [*assertion.get("must_any", []), *assertion.get("forbid_any", [])]:
        items = _expand([pat], registry)
        if pat.startswith("lex:"):
            lexical += items
        else:
            specific += [p for p in items if p.startswith("re:") or len(p) >= 3]
    return specific, lexical


def _topic_hit(evidence: dict[str, Any], sentence: str, registry: Registry) -> bool:
    key = evidence.get("fact_key")
    words = [*registry.topic_keywords(key), *(registry.lookup(key) or {}).get("cues", [])]
    return any(_hit(w, sentence) for w in words)


def _clauses(sentence: str) -> list[str]:
    """Split at a comma or a "…ですが／ますが" so that two conditions in one sentence are accounted for separately."""
    parts = [p for p in re.split(r"(?<=[、，,])|(?<=ですが)|(?<=ますが)|(?<=ものの)", sentence) if p.strip()]
    return parts or [sentence]


def _leaves(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _leaves(v, out)
    elif isinstance(value, list):
        for v in value:
            _leaves(v, out)


def _evidence_text(evidence: dict[str, Any]) -> str:
    """Everything a record says in words: the quoted source lines, the value, the sentences Work wrote from it."""
    out: list[str] = []
    for key in ("proofs", "value", "sentences", "field_proofs"):
        _leaves(evidence.get(key), out)
    return "".join(out)


def _ungrounded_terms(sentence: str, corpus: str, stop: set[str]) -> list[str]:
    """Content words (kanji / katakana runs) of the sentence whose character pairs are not all in the cited evidence's own words."""
    found = []
    for run in _TERM_RUN.findall(re.sub(r"\[EV-[^\]]+\]", "", sentence)):
        if run in stop:
            continue
        if not all(run[i:i + 2] in corpus for i in range(len(run) - 1)):
            found.append(run)
    return found


def semantic_coverage(text: str, evidence_by_id: dict[str, dict[str, Any]], registry: Registry | None = None) -> dict[str, Any]:
    """What the qualitative checks did and did not look at, for the evidence this article cites.
    `unverified` is the honest list: the QA has no rule for these, so it says nothing about them."""
    registry = registry or get_registry()
    checked: dict[str, list[str]] = {}
    unverified: list[dict[str, str]] = []
    for eid in sorted(e for e in extract_citation_ids(text) if e in evidence_by_id):
        evidence = evidence_by_id[eid]
        value = evidence.get("value") if isinstance(evidence.get("value"), dict) else {}
        applied = [a["id"] for a in assertions_for(evidence, registry) if _when_ok(a.get("when"), evidence)]
        if applied:
            checked[eid] = applied
        covered_fields = {a["when"]["field"] for a in assertions_for(evidence, registry)
                          if a.get("when") and _when_ok(a["when"], evidence)}
        for name, v in value.items():
            if isinstance(v, bool) and name not in covered_fields:
                unverified.append({"evidence_id": eid, "what": f"boolean {name}={v}", "why": "no assertion registered"})
        proofs = evidence.get("field_proofs")
        if isinstance(proofs, dict):  # a record that gives a per-field source position must give one for every boolean it states
            for name, v in value.items():
                if isinstance(v, bool) and not proofs.get(name):
                    unverified.append({"evidence_id": eid, "what": f"boolean {name}={v}", "why": "field_proofs has no source position for it"})
        if value.get("qualifier") and "qualifier" not in covered_fields:
            unverified.append({"evidence_id": eid, "what": f"qualifier {str(value['qualifier'])[:30]!r}", "why": "no qualitative rule matches it"})
    # SENTENCE by sentence (Issue #47): a sentence that states an obligation / prohibition / exemption is either the subject
    # of an assertion that checked it, or it is reported. One assertion applying somewhere in the paragraph says nothing
    # about the other sentences, so a new duty added next to correct, checked conditions cannot hide behind them.
    wording = _expand(registry.data.get("claim_wording", {}).get("obligation", []), registry)
    stop = set(registry.data.get("claim_wording", {}).get("stop_terms", []))
    for paragraph, sentences, contexts in paragraphs_with_citations(text):
        if _is_reference_list(paragraph):
            continue
        for whole, sentence_ids in zip(sentences, contexts):
            ids = sorted(e for e in sentence_ids if e in evidence_by_id)
            if not ids:
                continue
            for sentence in _clauses(whole):  # one sentence may carry several conditions: each is accounted for on its own
                hit = next((w for w in wording if _hit(w, sentence)), None)
                if hit is None or any(c in sentence for c in registry.negation_cues):
                    continue  # no claim of a duty, or a hedge ("…とは断定できません") that claims nothing

                def governs(e: str, a: dict[str, Any], sentence: str = sentence) -> bool:
                    specific, lexical = _anchors(a, registry)
                    return any(_hit(p, sentence) for p in specific) or (
                        any(_hit(p, sentence) for p in lexical) and _topic_hit(evidence_by_id[e], sentence, registry))
                if any(_when_ok(a.get("when"), evidence_by_id[e]) and governs(e, a) for e in ids for a in assertions_for(evidence_by_id[e], registry)):
                    continue  # verified (or contradicted, which is a finding): not an open question
                corpus = "".join(_evidence_text(evidence_by_id[e]) for e in ids)
                ungrounded = _ungrounded_terms(sentence, corpus, stop)
                word = hit[3:] if hit.startswith("re:") else hit
                entry = {"evidence_id": ",".join(ids), "what": f"obligation wording {word!r}: {sentence.strip()[:30]!r}",
                         "snippet": sentence.strip()[:30],
                         "kind": "unsupported_obligation" if ungrounded else "obligation_without_rule",
                         "why": "no assertion governs this clause"}
                if ungrounded:
                    entry["why"] = "no assertion governs this clause, and its content words are not in the cited evidence"
                    entry["ungrounded_terms"] = ungrounded
                unverified.append(entry)
    return {"checked": checked, "unverified": unverified,
            "counts": {"evidence_with_checks": len(checked), "unverified": len(unverified),
                       "unsupported_obligations": sum(u.get("kind") == "unsupported_obligation" for u in unverified)}}
