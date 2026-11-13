"""The fact_key registry: what each kind of evidence means, as data.

Before this, the meaning of a fact_key (its units, its topic words, its
selection stage, which wording rules apply) lived in Python dictionaries inside
strict_claims.py. Adding a university or a new kind of fact then meant editing
code. Now it is data (src/verify/data/fact_keys.json, versioned), and this module
loads it, checks it, and checks evidence records against it.

Severities
  error    fails the evidence gate and the article QA
           unregistered_fact_key, missing_required_field, value_type_mismatch, value_not_object
  warning  reported, does not fail (compatibility with data that is ahead of the registry)
           unregistered_value_field, unregistered_value, unregistered_scope, scope_unusual_for_key,
           fact_key_deprecated
  notice   information
           fact_key_proposed (usable, but the specification is not agreed yet),
           legacy_no_fact_key (older records that carry only `quota`)

An unregistered fact_key is never treated as verified.

CLI:
    python -m src.verify.fact_registry check <export.json> [--json-out out.json]   # evidence vs registry
    python -m src.verify.fact_registry validate                                    # the registry file itself
    python -m src.verify.fact_registry list | show <fact_key> | markdown
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import functools
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).parent / "data" / "fact_keys.json"
SCHEMA_VERSION = 1
STATUSES = ("active", "proposed", "deprecated")
TYPES = ("integer", "number", "string", "boolean", "iso_date", "iso_datetime", "clock_time",
         "string_list", "integer_list", "iso_month_list", "iso_date_list")
ROLES = ("logic", "period_label", "entry_months")
ENGINES = ("cues", "dates_listed")
ASSERTION_CATEGORIES = ("polarity_mismatch", "qualifier_dropped", "qualifier_contradicted", "unconditional_assertion", "listed_item_omitted")
WHEN_OPS = ("equals", "contains", "regex", "nonempty")
TRIGGER_OPS = ("contains", "equals", "startswith", "regex", "min_items")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")


class RegistryError(ValueError):
    """The registry file itself is malformed."""


@dataclasses.dataclass
class RegistryIssue:
    severity: str  # error | warning | notice
    category: str
    detail: str
    evidence_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ------------------------------------------------------------- type checks

def _is_date(s: Any) -> bool:
    if not (isinstance(s, str) and _DATE.match(s)):
        return False
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _type_ok(type_name: str, value: Any) -> bool:
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "iso_date":
        return _is_date(value)
    if type_name == "iso_datetime":
        return isinstance(value, str) and bool(_DATETIME.match(value)) and _is_date(value[:10])
    if type_name == "clock_time":
        m = re.fullmatch(r"(\d{2}):(\d{2})", value) if isinstance(value, str) else None
        return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60
    if type_name.endswith("_list"):
        element = {"string_list": "string", "integer_list": "integer", "iso_date_list": "iso_date"}.get(type_name)
        if type_name == "iso_month_list":
            return isinstance(value, list) and all(
                isinstance(v, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v) for v in value)
        return isinstance(value, list) and element is not None and all(_type_ok(element, v) for v in value)
    raise RegistryError(f"unknown type {type_name!r}")


# ---------------------------------------------------- registry file checks


def _assertion_problems(a: Any, where: str, value_fields: dict[str, Any] | None, lexicons: dict[str, Any] | None = None) -> list[str]:
    out: list[str] = []
    if not isinstance(a, dict) or not a.get("id"):
        return [f"{where}: an assertion needs an id"]
    here = f"{where}.{a['id']}"
    if a.get("category", "polarity_mismatch") not in ASSERTION_CATEGORIES:
        out.append(f"{here}: category must be one of {ASSERTION_CATEGORIES}")
    if not (a.get("must_any") or a.get("forbid_any") or a.get("echo_all_field") or a.get("sentence_if")):
        out.append(f"{here}: needs must_any, forbid_any, echo_all_field or sentence_if/sentence_must")
    if bool(a.get("sentence_if")) != bool(a.get("sentence_must")):
        out.append(f"{here}: sentence_if and sentence_must go together")
    for key in ("must_any", "forbid_any", "sentence_if", "sentence_must"):
        for pat in a.get(key, []):
            for name in re.findall(r"lex:([A-Za-z0-9_]+)", pat if isinstance(pat, str) else ""):
                if lexicons is not None and name not in lexicons:
                    out.append(f"{here}: unknown lexicon {name!r}")
            if not isinstance(pat, str) or not pat:
                out.append(f"{here}: {key} must be non-empty strings")
            elif pat.startswith("lex:"):
                continue
            elif pat.startswith("re:"):
                pat = re.sub(r"\{lex:[A-Za-z0-9_]+\}", "(?:x)", pat)
                try:
                    re.compile(pat[3:])
                except re.error as exc:
                    out.append(f"{here}: bad regex {pat!r}: {exc}")
    when = a.get("when")
    if when is not None:
        ops = [op for op in WHEN_OPS if op in when]
        if len(ops) != 1 or not isinstance(when.get("field"), str):
            out.append(f"{here}: when needs a field and exactly one of {WHEN_OPS}")
        else:
            if "regex" in when:
                try:
                    re.compile(when["regex"])
                except re.error as exc:
                    out.append(f"{here}: bad when-regex: {exc}")
            if value_fields is not None and when["field"] not in value_fields:
                out.append(f"{here}: when.field {when['field']!r} is not a value field of this fact_key")
    field = a.get("echo_all_field")
    if field and value_fields is not None and field not in value_fields:
        out.append(f"{here}: echo_all_field {field!r} is not a value field of this fact_key")
    return out



def validate_registry_data(data: dict[str, Any]) -> list[str]:
    """Problems in the registry file itself (empty list = well-formed)."""
    problems: list[str] = []

    def need(cond: bool, message: str) -> None:
        if not cond:
            problems.append(message)

    need(data.get("schema_version") == SCHEMA_VERSION, f"schema_version must be {SCHEMA_VERSION}")
    need(isinstance(data.get("registry_version"), str) and bool(_SEMVER.match(data.get("registry_version", ""))),
         "registry_version must be semver (e.g. 1.0.0)")
    log = data.get("changelog")
    need(isinstance(log, list) and bool(log), "changelog must list the registry's versions (newest last)")
    if isinstance(log, list) and log:
        versions = [e.get("version", "") for e in log]
        need(all(_SEMVER.match(v) for v in versions), "changelog: every version must be semver")
        need(all(e.get("changes") for e in log), "changelog: every entry needs `changes`")
        need(versions[-1] == data.get("registry_version"), "changelog: the last entry must be the current registry_version")
        parsed = [tuple(int(x) for x in v.split(".")) for v in versions if _SEMVER.match(v)]
        need(parsed == sorted(set(parsed)), "changelog: versions must be strictly increasing")
    for name, cfg in data.get("source_kinds", {}).items():
        need(name in ("pdf", "html") and bool(cfg.get("description")), f"source_kinds.{name}: only pdf and html are defined, with a description")
    lex = data.get("lexicons", {})
    for name, items in lex.items():
        need(isinstance(items, list) and bool(items) and all(isinstance(i, str) and i for i in items), f"lexicons.{name}: a non-empty list of strings")
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str) and item.startswith("re:"):
                try:
                    re.compile(item[3:])
                except re.error as exc:
                    problems.append(f"lexicons.{name}: bad regex {item!r}: {exc}")
    ids = [a.get("id") for a in data.get("qualitative_rules", []) if isinstance(a, dict)]
    need(len(ids) == len(set(ids)), "qualitative_rules: ids must be unique")
    for a in data.get("qualitative_rules", []):
        problems.extend(_assertion_problems(a, "qualitative_rules", None, lex))
    for a in data.get("article_rules", []):
        problems.extend(_assertion_problems(a, "article_rules", None, lex))
        need("when" not in a and not a.get("must_any"), f"article_rules.{a.get('id')}: article rules only forbid phrases (no when / must_any)")
    cw = data.get("claim_wording", {})
    need(isinstance(cw.get("obligation"), list) and bool(cw["obligation"]) and all(isinstance(x, str) and x for x in cw["obligation"]),
         "claim_wording.obligation must be a non-empty list of strings")
    for pat in cw.get("obligation", []) if isinstance(cw.get("obligation"), list) else []:
        if isinstance(pat, str) and pat.startswith("re:"):
            try:
                re.compile(pat[3:])
            except re.error as exc:
                problems.append(f"claim_wording.obligation: bad regex {pat!r}: {exc}")
    need(isinstance(cw.get("stop_terms", []), list), "claim_wording.stop_terms must be a list")
    for r in data.get("article_sentence_rules", []):
        need(isinstance(r, dict) and r.get("id") and r.get("applies_to") and r.get("must_any") and r.get("category") in ASSERTION_CATEGORIES,
             f"article_sentence_rules.{r.get('id') if isinstance(r, dict) else r}: needs id, applies_to, must_any and a known category")
        for key in ("applies_to", "must_any"):
            for pat in (r.get(key, []) if isinstance(r, dict) else []):
                if isinstance(pat, str) and pat.startswith("re:"):
                    try:
                        re.compile(re.sub(r"\{lex:[A-Za-z0-9_]+\}", "(?:x)", pat[3:]))
                    except re.error as exc:
                        problems.append(f"article_sentence_rules.{r.get('id')}: bad regex {pat!r}: {exc}")
    cues = data.get("temporal_cues", {})
    for kind in ("elapsed", "upcoming"):
        need(isinstance(cues.get(kind), list) and bool(cues[kind]) and all(isinstance(c, str) and c for c in cues[kind]),
             f"temporal_cues.{kind} must be a non-empty list of strings")
    kinds, scopes, rules = data.get("kinds", {}), data.get("scopes", {}), data.get("rules", {})
    for name, cfg in kinds.items():
        need(isinstance(cfg.get("units"), list) and cfg["units"], f"kind {name}: units must be a non-empty list")
    for pattern in data.get("scope_patterns", []):
        try:
            re.compile(pattern["pattern"])
        except (re.error, KeyError) as exc:
            problems.append(f"scope_patterns: bad pattern {pattern!r}: {exc}")
    for name, cfg in rules.items():
        need(cfg.get("engine", "cues") in ENGINES, f"rule {name}: unknown engine {cfg.get('engine')!r}")
        need(bool(cfg.get("category")), f"rule {name}: category is required")
        for key in ("forbidden_patterns", "required_any_pattern"):
            for p in cfg.get(key, []):
                try:
                    re.compile(p)
                except re.error as exc:
                    problems.append(f"rule {name}: bad regex {p!r}: {exc}")
    for i, trig in enumerate(data.get("semantic_triggers", [])):
        need(trig.get("rule") in rules, f"semantic_triggers[{i}]: unknown rule {trig.get('rule')!r}")
        ops = [op for op in TRIGGER_OPS if op in trig]
        need(len(ops) == 1, f"semantic_triggers[{i}]: exactly one of {TRIGGER_OPS} is required")
        need(isinstance(trig.get("field"), str) and (trig["field"] == "scope" or trig["field"].startswith("value.")),
             f"semantic_triggers[{i}]: field must be 'scope' or 'value.<name>'")
        if "regex" in trig:
            try:
                re.compile(trig["regex"])
            except re.error as exc:
                problems.append(f"semantic_triggers[{i}]: bad regex: {exc}")
    keys = data.get("fact_keys", {})
    need(bool(keys), "fact_keys must not be empty")
    for key, spec in keys.items():
        where = f"fact_key {key}"
        need(re.fullmatch(r"[a-z][a-z0-9_]*", key) is not None, f"{where}: name must be lower_snake_case")
        need(bool(spec.get("description")), f"{where}: description is required")
        need(spec.get("status") in STATUSES, f"{where}: status must be one of {STATUSES}")
        need(bool(_SEMVER.match(spec.get("since", ""))), f"{where}: since must be semver")
        need(spec.get("stage") in (None, 1, 2), f"{where}: stage must be 1, 2 or absent")
        need(isinstance(spec.get("topic_keywords"), list) and bool(spec["topic_keywords"]) or spec.get("status") == "proposed",
             f"{where}: topic_keywords is required (a non-empty list) unless the key is only proposed")
        for scope in spec.get("scopes", []):
            need(scope in scopes or scope in ("*", "all_*"), f"{where}: unknown scope {scope!r}")
        for rule in spec.get("rules", []):
            need(rule in rules, f"{where}: unknown rule {rule!r}")
        cues = spec.get("cues")
        need(cues is not None or spec.get("status") != "active",
             f"{where}: an active key must have cues (what its sentence says), so a swapped citation id can be noticed")
        if cues is not None:
            need(isinstance(cues, list) and bool(cues) and all(isinstance(c, str) and c for c in cues), f"{where}: cues must be a non-empty list of strings")
            for c in cues if isinstance(cues, list) else []:
                if isinstance(c, str) and c.startswith("re:"):
                    try:
                        re.compile(c[3:])
                    except re.error as exc:
                        problems.append(f"{where}: bad cue regex {c!r}: {exc}")
        for a in spec.get("assertions", []):
            problems.extend(_assertion_problems(a, where, spec.get("value", {}), lex))
        eef = spec.get("event_end_field")
        need(eef is None or eef in spec.get("value", {}), f"{where}: event_end_field {eef!r} must be one of the value fields")
        tk = spec.get("temporal_keywords", [])
        need(isinstance(tk, list) and all(isinstance(w, str) and w for w in tk), f"{where}: temporal_keywords must be a list of strings")
        if spec.get("status") == "deprecated":
            need(bool(spec.get("replaced_by")), f"{where}: a deprecated key must name replaced_by")
        value = spec.get("value", {})
        need(isinstance(value, dict) and bool(value), f"{where}: value must describe at least one field")
        for field, fspec in value.items():
            fwhere = f"{where}.{field}"
            need(fspec.get("type") in TYPES, f"{fwhere}: type must be one of {TYPES}")
            need(fspec.get("kind") is None or fspec["kind"] in kinds, f"{fwhere}: unknown kind {fspec.get('kind')!r}")
            need(fspec.get("role") is None or fspec["role"] in ROLES, f"{fwhere}: unknown role {fspec.get('role')!r}")
            need(fspec.get("kind") is None or fspec.get("type") in ("integer", "number"),
                 f"{fwhere}: a quantity kind needs an integer/number type")
    return problems


# ------------------------------------------------------------------ Registry

class Registry:
    def __init__(self, data: dict[str, Any]):
        problems = validate_registry_data(data)
        if problems:
            raise RegistryError("fact_keys.json is malformed:\n  " + "\n  ".join(problems))
        self.data = data
        self.version: str = data["registry_version"]
        self.fact_keys: dict[str, dict[str, Any]] = data["fact_keys"]
        self.rules: dict[str, dict[str, Any]] = data["rules"]
        self.kinds: dict[str, Any] = data["kinds"]
        self.negation_cues: tuple[str, ...] = tuple(data.get("negation_cues", ()))
        self._patterns = [(re.compile(p["pattern"]), p) for p in data.get("scope_patterns", [])]

    # -- lookup
    def lookup(self, fact_key: str | None) -> dict[str, Any] | None:
        return self.fact_keys.get(fact_key) if fact_key else None

    def topic_keywords(self, fact_key: str | None) -> tuple[str, ...]:
        spec = self.lookup(fact_key)
        return tuple(spec.get("topic_keywords", ())) if spec else ()

    def temporal_keywords(self, fact_key: str | None) -> tuple[str, ...]:
        spec = self.lookup(fact_key)
        return tuple(spec.get("temporal_keywords", ())) if spec else ()

    def cue_match(self, fact_key: str | None, text: str) -> bool | None:
        """Does `text` contain a cue of this fact_key? None = the key has no cues (no constraint).
        Falls back to topic_keywords for a key registered without cues."""
        spec = self.lookup(fact_key)
        if not spec:
            return None
        cues = spec.get("cues")
        if cues is None:
            words = spec.get("topic_keywords", ())
            return any(w in text for w in words) if words else None
        return any((re.search(c[3:], text) if c.startswith("re:") else (c in text)) for c in cues)

    def event_end_field(self, fact_key: str | None) -> str | None:
        spec = self.lookup(fact_key)
        return spec.get("event_end_field") if spec else None

    @property
    def temporal_cues(self) -> dict[str, tuple[str, ...]]:
        cues = self.data["temporal_cues"]
        return {"elapsed": tuple(cues["elapsed"]), "upcoming": tuple(cues["upcoming"])}

    def stage(self, fact_key: str | None) -> int | None:
        spec = self.lookup(fact_key)
        return spec.get("stage") if spec else None

    def fields(self, fact_key: str | None) -> dict[str, dict[str, Any]]:
        spec = self.lookup(fact_key)
        return spec.get("value", {}) if spec else {}

    def scope_info(self, scope: str | None) -> dict[str, Any] | None:
        if not scope:
            return None
        if scope in self.data.get("scopes", {}):
            return self.data["scopes"][scope]
        for pattern, info in self._patterns:
            if pattern.match(scope):
                return info
        return None

    def _scope_allowed(self, fact_key: str, scope: str) -> bool:
        allowed = self.fact_keys[fact_key].get("scopes")
        if not allowed or "*" in allowed or scope in allowed:
            return True
        info = self.scope_info(scope)
        return bool(info and info.get("semantics") == "all_units" and "all_*" in allowed)

    # -- semantic rules
    @staticmethod
    def _field_value(evidence: dict[str, Any], field: str) -> Any:
        if field == "scope":
            return evidence.get("scope")
        value = evidence.get("value")
        return value.get(field[len("value."):]) if isinstance(value, dict) else None

    def triggered_rules(self, evidence: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Rules that apply to this evidence: triggered by its content (any key,
        registered or not) plus the rules its fact_key lists explicitly."""
        names: list[str] = []
        for trig in self.data.get("semantic_triggers", []):
            v = self._field_value(evidence, trig["field"])
            if v is None:
                continue
            if ("contains" in trig and isinstance(v, str) and trig["contains"] in v) \
               or ("equals" in trig and v == trig["equals"]) \
               or ("startswith" in trig and isinstance(v, str) and v.startswith(trig["startswith"])) \
               or ("regex" in trig and isinstance(v, str) and re.search(trig["regex"], v)) \
               or ("min_items" in trig and isinstance(v, list) and len(v) >= trig["min_items"]):
                names.append(trig["rule"])
        spec = self.lookup(evidence.get("fact_key"))
        names.extend(spec.get("rules", []) if spec else [])
        seen, out = set(), []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append((n, self.rules[n]))
        return out

    # -- checking evidence
    def check_record(self, record: dict[str, Any], evidence_id: str | None = None) -> list[RegistryIssue]:
        eid = evidence_id or record.get("evidence_id")
        issues: list[RegistryIssue] = []

        def add(severity: str, category: str, detail: str) -> None:
            issues.append(RegistryIssue(severity, category, detail, eid))

        issues.extend(self._check_source(record, eid))
        key = record.get("fact_key")
        if not key:
            add("notice", "legacy_no_fact_key",
                "record has no fact_key (older format, e.g. only `quota`): checked by value hints, not by the registry")
            return issues
        spec = self.lookup(key)
        if spec is None:
            add("error", "unregistered_fact_key",
                f"fact_key {key!r} is not in the registry (version {self.version}); it is NOT treated as verified. "
                "Propose it on Issue #19 / #22, then add it to src/verify/data/fact_keys.json (docs/FACT_KEYS.md)")
            return issues
        if spec["status"] == "proposed":
            add("notice", "fact_key_proposed", f"fact_key {key!r} is proposed: usable, but its specification is not agreed yet")
        elif spec["status"] == "deprecated":
            add("warning", "fact_key_deprecated", f"fact_key {key!r} is deprecated; use {spec.get('replaced_by')!r}")

        if "stage" in record:  # optional (Issue #12): which selection stage this record is about
            stages = record["stage"] if isinstance(record["stage"], list) else [record["stage"]]
            fixed = self.stage(key)
            if not stages or any(isinstance(s, bool) or s not in (1, 2, "final") for s in stages):
                add("error", "stage_invalid", f"record stage must be 1, 2, 'final' or a non-empty list of them, got {record['stage']!r}")
            elif fixed and fixed not in stages:
                add("error", "stage_conflict", f"fact_key {key!r} is a stage-{fixed} fact but the record says stage {record['stage']!r}")
            elif fixed and set(stages) != {fixed}:
                add("warning", "stage_overbroad", f"fact_key {key!r} is a stage-{fixed} fact: stage {record['stage']!r} also lets a sentence use another ordinal")

        value = record.get("value")
        if not isinstance(value, dict):
            add("error", "value_not_object", f"fact_key {key!r}: `value` must be an object, got {type(value).__name__}")
            return issues
        fields = spec["value"]
        for name, fspec in fields.items():
            present = name in value
            nullable = fspec.get("nullable", False)
            if fspec.get("required") and (not present or (value[name] is None and not nullable)):
                add("error", "missing_required_field", f"fact_key {key!r}: required value field {name!r} is missing")
                continue
            if not present:
                continue
            v = value[name]
            if v is None:
                if not nullable:
                    add("error", "value_type_mismatch", f"fact_key {key!r}: {name!r} is null but not nullable")
                continue
            if not _type_ok(fspec["type"], v):
                add("error", "value_type_mismatch", f"fact_key {key!r}: {name!r} must be {fspec['type']}, got {v!r}")
            elif fspec.get("known_values") and v not in fspec["known_values"]:
                add("warning", "unregistered_value", f"fact_key {key!r}: {name!r}={v!r} is not among the known values {fspec['known_values']}")
        for name in value:
            if name not in fields:
                add("warning", "unregistered_value_field",
                    f"fact_key {key!r}: value field {name!r} is not registered; it is checked only by name-based hints")
        scope = record.get("scope")
        if scope:
            if self.scope_info(scope) is None:
                add("warning", "unregistered_scope", f"scope {scope!r} is not registered; its meaning is not checked")
            elif not self._scope_allowed(key, scope):
                add("warning", "scope_unusual_for_key", f"fact_key {key!r} is not normally used with scope {scope!r}")
        return issues

    @staticmethod
    def _check_source(record: dict[str, Any], eid: str | None) -> list[RegistryIssue]:
        """The source contract: an HTML notice must not pretend to be a PDF. Older records with no
        source_kind keep working (a PDF hash, or none, as before)."""
        out: list[RegistryIssue] = []
        kind = record.get("source_kind")
        if kind is None:
            return out
        if kind not in ("pdf", "html"):
            out.append(RegistryIssue("warning", "unregistered_source_kind", f"source_kind {kind!r} is not one of pdf / html", eid))
            return out
        sha = lambda v: isinstance(v, str) and bool(re.fullmatch(r"[0-9a-f]{64}", v))  # noqa: E731
        if kind == "html":
            if record.get("source_pdf_sha256") not in (None, ""):
                out.append(RegistryIssue("error", "source_contract_violation", "an html source must have source_pdf_sha256 = null (it is not a PDF)", eid))
            if not sha(record.get("source_sha256")):
                out.append(RegistryIssue("error", "source_contract_violation", "an html source needs source_sha256 (sha256 of the page body, 64 hex)", eid))
            pages = {p.get("page") for p in record.get("proofs", []) if isinstance(p, dict)}
            if pages - {1}:
                out.append(RegistryIssue("warning", "source_contract_violation", f"an html source has one logical page (1); proofs cite {sorted(map(str, pages))}", eid))
        elif not sha(record.get("source_pdf_sha256")):
            out.append(RegistryIssue("error", "source_contract_violation", "a pdf source needs source_pdf_sha256 (sha256 of the file, 64 hex)", eid))
        return out

    def check_evidence(self, evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
        issues: list[RegistryIssue] = []
        for eid, record in evidence_by_id.items():
            issues.extend(self.check_record(record, eid))
        by_sev = {s: sum(i.severity == s for i in issues) for s in ("error", "warning", "notice")}
        keys_used = sorted({r.get("fact_key") for r in evidence_by_id.values() if r.get("fact_key")})
        return {
            "registry_version": self.version,
            "records": len(evidence_by_id),
            "ok": by_sev["error"] == 0,
            "by_severity": by_sev,
            "fact_keys_used": keys_used,
            "unregistered_fact_keys": sorted({k for k in keys_used if k not in self.fact_keys}),
            "proposed_fact_keys": sorted(k for k in keys_used if k in self.fact_keys and self.fact_keys[k]["status"] == "proposed"),
            "records_without_fact_key": sorted(e for e, r in evidence_by_id.items() if not r.get("fact_key")),
            "issues": [i.to_dict() for i in issues],
        }


@functools.lru_cache(maxsize=1)
def get_registry() -> Registry:
    return load_registry(DEFAULT_PATH)


def load_registry(path: Path) -> Registry:
    return Registry(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------ documentation

def render_markdown(registry: Registry) -> str:
    """docs/FACT_KEYS_REFERENCE.md is generated from the registry, so it cannot drift."""
    d = registry.data
    lines = [
        "# fact_key 登録簿（自動生成）",
        "",
        f"登録簿バージョン: **{registry.version}**（schema {d['schema_version']}、更新 {d.get('updated', '')}）",
        "",
        "このファイルは `python -m src.verify.fact_registry markdown` で `src/verify/data/fact_keys.json` から生成される。",
        "**直接編集しない**（テストが生成結果との一致を確認する）。追加手順は [FACT_KEYS.md](FACT_KEYS.md)。",
        "",
        "## fact_key 一覧",
        "",
        "| fact_key | 意味 | 状態 | since | 段階 | 値の項目（型・種類） | 手がかり（cues） |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, spec in registry.fact_keys.items():
        fields = ", ".join(
            f"`{n}`{'*' if f.get('required') else ''}:{f['type']}" + (f"[{f['kind']}]" if f.get("kind") else "")
            for n, f in spec["value"].items())
        lines.append(
            f"| `{key}` | {spec['description']} | {spec['status']} | {spec['since']} | {spec.get('stage') or '-'} | {fields} | "
            f"{'・'.join(c.replace('re:', '正規表現:') for c in spec.get('cues', spec.get('topic_keywords', [])))} |")
    lines += ["", "`*` は必須の項目。種類（`[persons]` など）は、本文の数量を単位つきで照合するときの分類。", "", "## 数量の種類と単位", "",
              "| 種類 | 意味 | 本文での単位 |", "|---|---|---|"]
    for name, cfg in d["kinds"].items():
        lines.append(f"| `{name}` | {cfg['label']} | {'・'.join(cfg['units'])} |")
    lines += ["", "## 適用範囲（scope）", "", "| scope | 種別 | 意味 |", "|---|---|---|"]
    for name, cfg in d["scopes"].items():
        lines.append(f"| `{name}` | {cfg['semantics']} | {cfg['description']} |")
    for p in d.get("scope_patterns", []):
        lines.append(f"| `{p['pattern']}`（パターン） | {p['semantics']} | {p['description']} |")
    lines += ["", "## 検証ルール", "", "| ルール | 検出カテゴリ | 内容 | 発動する条件 |", "|---|---|---|---|"]
    triggers: dict[str, list[str]] = {}
    for t in d["semantic_triggers"]:
        op = next(o for o in TRIGGER_OPS if o in t)
        triggers.setdefault(t["rule"], []).append(f"`{t['field']}` {op} `{t[op]}`")
    for name, cfg in registry.rules.items():
        lines.append(f"| `{name}` | `{cfg['category']}` | {cfg.get('description', '')} | {'; '.join(triggers.get(name, ['（fact_key 側で指定）']))} |")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check an export's evidence records against the registry")
    c.add_argument("export", type=Path)
    c.add_argument("--json-out", type=Path, default=None)
    c.add_argument("--registry", type=Path, default=None, help="alternative registry file (e.g. a proposed one)")
    v = sub.add_parser("validate", help="check the registry file itself")
    v.add_argument("--registry", type=Path, default=None)
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("fact_key")
    sub.add_parser("markdown")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        path = args.registry or DEFAULT_PATH
        problems = validate_registry_data(json.loads(Path(path).read_text(encoding="utf-8")))
        print(json.dumps({"registry": path.name, "well_formed": not problems, "problems": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    registry = load_registry(args.registry) if getattr(args, "registry", None) else get_registry()
    if args.cmd == "list":
        for key, spec in registry.fact_keys.items():
            print(f"{key}\t{spec['status']}\t{spec['description']}")
        return 0
    if args.cmd == "show":
        spec = registry.lookup(args.fact_key)
        print(json.dumps(spec, ensure_ascii=False, indent=2) if spec else f"{args.fact_key!r} is not registered")
        return 0 if spec else 1
    if args.cmd == "markdown":
        print(render_markdown(registry), end="")
        return 0
    data = json.loads(args.export.read_text(encoding="utf-8"))
    evidence = data["evidence"] if isinstance(data, dict) and "evidence" in data else data
    report = registry.check_evidence(evidence)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
