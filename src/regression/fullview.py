"""Whole-view check (Issue #36): the CURRENT state of every university / method together.

Work delivers each batch as `claude-compatible-export.json` (found automatically by `handoffs`). A later
"whole view" (e.g. `samples/current/active-state.json`) repeats the evidence ids of earlier deliveries, so it
cannot be one more export: the isolation check would call every repeated id a collision. This module checks it on
its own and tells a LEGITIMATE reuse of an id from a real collision:

* same id, same fact / target / year / method / source URL / source hash / quote positions / value  -> reuse (fine)
* same id, anything of that different                                                             -> collision (failure)
* same article id with a different text                                                           -> collision (failure)
* `<base>:revision:<hash>` articles are the legitimate way to change an article: the base must exist and differ,
  the id must carry the revision hash, every citation must be listed in `evidence_ids` and exist.

Then the whole view goes through the same checks as any delivery (`evaluate_export`: every article's QA, registry,
body / citation / as-of mutations, citation swaps, meaning flips, notation, version round trip).

What this does NOT do, and says so in every report:
* `scope=export`: the original PDFs / full HTML are not in the repository, so the check against them is
  `not_run` — never counted as passed. (`scope=full` is Work's local run with the originals.)
* A green result is not publication approval. `publication_approved` is always false.

    python -m src.regression.fullview [--inbox research/inbox] [--view path ...] [--out-dir DIR] [--github-summary]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from src.regression.checks import Thresholds, evaluate_export
from src.regression.handoffs import INBOX, REPO_ROOT, find_exports
from src.verify.consistency import extract_citation_ids
from src.verify.fact_registry import get_registry

VIEW_GLOBS = ("*active-state*.json", "*full-view*.json")
CANONICAL_VIEW_NAMES = ("active-state.json", "full-view.json")  # always a view: if malformed that is a failure, not "no view"


def looks_like_view(data: Any) -> bool:
    return isinstance(data, dict) and "evidence" in data and "articles" in data
IDENTITY_FIELDS = ("fact_key", "value", "scope", "university", "faculty", "department", "admission_method", "fiscal_year",
                   "source_url", "source_kind")
_REVISION_RE = re.compile(r"^(?P<base>.+):revision:(?P<hash>[0-9a-f]{16})$")


def find_views(inbox: Path = INBOX) -> list[Path]:
    """Whole views by file name; a delivery (`claude-compatible-export.json`) is never a view."""
    found: set[Path] = set()
    for pattern in VIEW_GLOBS:
        found |= {p for p in Path(inbox).rglob(pattern) if p.name != "claude-compatible-export.json"}
    views = []
    for p in sorted(found):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        # a Work REPORT such as qa/full-view-final.json has other keys and is not a view; a file with the canonical
        # name is always one, so a broken one is reported instead of silently ignored
        if p.name in CANONICAL_VIEW_NAMES or looks_like_view(data):
            views.append(p)
    return views


def view_shape_problems(view: Any) -> list[str]:
    """What a whole view must look like before anything else is trusted: evidence is an object of records whose
    `evidence_id` is their key; articles is a list of objects with id, text and the article's own claim."""
    if not isinstance(view, dict):
        return ["the view is not an object"]
    problems: list[str] = []
    evidence, articles = view.get("evidence"), view.get("articles")
    if not isinstance(evidence, dict) or not evidence:
        problems.append("evidence must be a non-empty object keyed by evidence_id")
    else:
        for key, record in evidence.items():
            if not isinstance(record, dict):
                problems.append(f"evidence {key}: not an object")
            elif record.get("evidence_id") != key:
                problems.append(f"evidence {key}: its evidence_id is {record.get('evidence_id')!r}")
    if not isinstance(articles, list) or not articles:
        problems.append("articles must be a non-empty list")
    else:
        seen: set[str] = set()
        for i, a in enumerate(articles):
            if (not isinstance(a, dict) or not isinstance(a.get("article_id"), str) or not isinstance(a.get("text"), str)
                    or not isinstance(a.get("claim"), dict)):
                problems.append(f"article #{i}: needs article_id, text and claim")
                continue
            if a["article_id"] in seen:
                problems.append(f"article {a['article_id'][-30:]}: duplicate article_id")
            seen.add(a["article_id"])
    return problems


def _source_hash(record: dict[str, Any]) -> Any:
    return record.get("source_sha256") or record.get("source_pdf_sha256")


def _proofs(record: dict[str, Any]) -> list[tuple[Any, Any]]:
    return [(p.get("page"), p.get("quote")) for p in record.get("proofs") or [] if isinstance(p, dict)]


def evidence_differences(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Which of what an evidence id MEANS differs between two records carrying that id."""
    diff = [f for f in IDENTITY_FIELDS if a.get(f) != b.get(f)]
    if _source_hash(a) != _source_hash(b):
        diff.append("source_hash")
    if _proofs(a) != _proofs(b):
        diff.append("proofs")
    return diff


# ------------------------------------------------------------------ id reuse

def evidence_reuse(view: dict[str, Any], priors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reused: dict[str, str] = {}
    new: list[str] = []
    collisions: list[dict[str, Any]] = []
    refetched: list[str] = []
    for eid, record in view["evidence"].items():
        homes = [(key, prior["evidence"][eid]) for key, prior in priors.items() if eid in prior["evidence"]]
        if not homes:
            new.append(eid)
            continue
        bad = False
        for key, old in homes:
            diff = evidence_differences(record, old)
            if diff:
                collisions.append({"evidence_id": eid, "against": key, "differs": diff})
                bad = True
            elif record.get("retrieved_at") != old.get("retrieved_at"):
                refetched.append(eid)
        if not bad:
            reused[eid] = homes[0][0]
    return {"reused": len(reused), "new": len(new), "new_ids": sorted(new), "collisions": collisions,
            "retrieved_at_differs": sorted(set(refetched))}


def find_base_states(inbox: Path = INBOX) -> dict[str, dict[str, Any]]:
    """`*base-state*.json`: the state a whole view was derived from. Used ONLY to find the text a revision changed
    (an article's base); never for the id-reuse check, and it is Work's own record, not an independent one."""
    out = {}
    for p in sorted(Path(inbox).rglob("*base-state*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("articles"), list):
            out[p.relative_to(inbox).as_posix()] = data
    return out


def evidence_identity(view: dict[str, Any], priors: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The same FACT under two evidence ids (G-05) across the view and every earlier delivery. Reported with an alias PROPOSAL; never renamed.
    A `conflict` (two different statements about the same place in one source) is a real inconsistency and fails the view."""
    from src.db_contract.identity import find_groups, propose_aliases
    from src.db_contract.load_export import case_id_of
    evidence: dict[str, dict[str, Any]] = {}
    for prior in priors.values():
        evidence.update(prior["evidence"])
    evidence.update(view["evidence"])
    groups = find_groups(evidence, case_id_of)
    keep = sorted(view["evidence"])  # the ids the view (and its articles) already use are the ones to keep
    return {"groups": groups, "conflicts": [g for g in groups if "conflict" in g["kinds"]], "alias_proposal": propose_aliases(groups, prefer=keep)}


def article_history(view: dict[str, Any], priors: dict[str, dict[str, Any]], bases: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    prior_text: dict[str, tuple[str, str]] = {}
    for key, prior in priors.items():
        for a in prior["articles"]:
            prior_text.setdefault(a["article_id"], (key, a["text"]))
    base_only: dict[str, tuple[str, str]] = {}
    for key, state in (bases or {}).items():
        for a in state["articles"]:
            base_only.setdefault(a["article_id"], (key, a["text"]))
    view_text = {a["article_id"]: a["text"] for a in view["articles"]}
    failures: list[str] = []
    notices: list[str] = []
    same = new = revised = 0
    for a in view["articles"]:
        aid, text = a["article_id"], a["text"]
        m = _REVISION_RE.match(aid)
        listed = a.get("evidence_ids")
        cited = {e for e in extract_citation_ids(text)}
        if isinstance(listed, list):
            if cited - set(listed):
                failures.append(f"{aid[-40:]}: cites {sorted(cited - set(listed))} which its evidence_ids does not list")
        if cited - set(view["evidence"]):
            failures.append(f"{aid[-40:]}: cites {sorted(cited - set(view['evidence']))} which the view does not contain")
        if a.get("publish_allowed"):
            notices.append(f"{aid[-40:]}: publish_allowed is true (a machine QA result never approves publication)")
        if not m:
            if aid in prior_text:
                if prior_text[aid][1] == text:
                    same += 1
                else:
                    failures.append(f"{aid[-40:]}: the same article id as {prior_text[aid][0]} but its text differs "
                                    "(a change must be a new `:revision:` id)")
            else:
                new += 1
            continue
        revised += 1
        base_id = m.group("base")
        if a.get("base_article_id") not in (None, base_id):
            failures.append(f"{aid[-40:]}: base_article_id {a.get('base_article_id')!r} is not the base in its id")
        if not str(a.get("revision_hash", "")).startswith(m.group("hash")):
            failures.append(f"{aid[-40:]}: the id's revision hash does not match revision_hash")
        if not a.get("as_of"):
            failures.append(f"{aid[-40:]}: a revision has no as_of date")
        base = prior_text.get(base_id) or base_only.get(base_id) or ((base_id, view_text[base_id]) if base_id in view_text else None)
        if base is None:
            notices.append(f"{aid[-40:]}: the base article {base_id[-32:]} is in no delivery here, so the change from it is not checked")
        elif base[1] == text:
            failures.append(f"{aid[-40:]}: identical to its base text — not a revision")
        parent = a.get("parent_article_id")
        if parent and parent != aid and not _REVISION_RE.match(parent) and parent != base_id:
            failures.append(f"{aid[-40:]}: parent_article_id {parent[-32:]} is neither a revision nor the base")
    return {"same_text": same, "new": new, "revisions": revised, "failures": failures, "notices": notices,
            "revision_hash_recomputed": "not_run (Work's hash definition is not part of the contract)"}


# ------------------------------------------------------------------ one view

def check_view(key: str, view: dict[str, Any], priors: dict[str, dict[str, Any]], thresholds: Thresholds = Thresholds(),
               bases: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    reuse = evidence_reuse(view, priors)
    history = article_history(view, priors, bases)
    identity = evidence_identity(view, priors)
    qa = evaluate_export(key, view, thresholds)
    failures = [f"evidence id {c['evidence_id']} also in {c['against']} but differs in {c['differs']}" for c in reuse["collisions"]]
    failures += history["failures"]
    failures += [f"evidence identity: {g['fact_key']} {g['ids']} say different things about the same place" for g in identity["conflicts"]]
    failures += [f"QA: {f}" for f in qa["failures"]]
    checks = {
        "evidence_id_reuse": "failed" if reuse["collisions"] else "passed",
        "article_history": "failed" if history["failures"] else "passed",
        "article_qa_and_mutations": "failed" if qa["failures"] else "passed",
        "original_source_comparison": "not_run",
        "revision_hash_recomputation": "not_run",
    }
    return {
        "key": key, "records": len(view["evidence"]), "articles": len(view["articles"]),
        "evidence_reuse": reuse, "article_history": history, "evidence_identity": identity, "qa": qa, "checks": checks,
        "counts": {"passed": sum(v == "passed" for v in checks.values()), "failed": sum(v == "failed" for v in checks.values()),
                   "not_run": sum(v == "not_run" for v in checks.values()), "unverified_meanings": qa["semantic_coverage"]["unverified"]},
        "failures": failures,
        "warnings": qa["warnings"] + history["notices"] + (
            [f"the same fact under two evidence ids ({len(identity['groups'])} group(s), alias proposal {len(identity['alias_proposal'])}): "
             f"e.g. {identity['groups'][0]['ids']} — see docs/DB_SCHEMA_GAP_ANALYSIS.md G-05"] if identity["groups"] else []),
        "ok": not failures,
    }


def build_report(inbox: Path = INBOX, views: list[Path] | None = None, thresholds: Thresholds = Thresholds(),
                 scope: str = "export", execution_origin: str = "local", require_view: bool = False) -> dict[str, Any]:
    paths = views if views is not None else find_views(inbox)
    priors = {ref.key: ref.load() for ref in find_exports(inbox)}
    bases = find_base_states(inbox)
    # a view is never its own prior
    results = {}
    for p in paths:
        try:
            rel = Path(p).resolve().relative_to(Path(inbox).resolve()).as_posix()
        except ValueError:
            rel = Path(p).name
        try:
            view = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            results[rel] = {"key": rel, "ok": False, "failures": [f"unreadable view: {type(exc).__name__}"], "warnings": [], "unreadable": True}
            continue
        shape = view_shape_problems(view)
        if shape:
            results[rel] = {"key": rel, "ok": False, "failures": [f"malformed view: {s}" for s in shape], "warnings": [], "malformed": True}
            continue
        results[rel] = check_view(rel, view, {k: v for k, v in priors.items() if k != rel}, thresholds, bases)
    reasons = [f"{k}: {f}" for k, r in results.items() for f in r["failures"]]
    if require_view and not results:
        reasons.append("no whole view found under the inbox (--require-view)")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "commit": commit or None, "registry_version": get_registry().version, "scope": scope, "execution_origin": execution_origin,
        "original_source_check": {"status": "not_run" if scope == "export" else "see scope=full report",
                                  "reason": "the original PDFs / full HTML are not in the repository; this is not a source verification"},
        "publication_approved": False, "ci_success_is_publication_approval": False,
        "priors": sorted(priors), "views": results, "verdict": {"ok": not reasons, "reasons": reasons},
    }


def render_markdown(report: dict[str, Any]) -> str:
    v = report["verdict"]
    lines = ["# 全体ビュー検査（Issue #36）", "",
             f"- 判定: {'✅ 成功' if v['ok'] else '❌ 失敗'}　scope=`{report['scope']}`　実行: {report['execution_origin']}　commit `{report['commit']}`　登録簿 {report['registry_version']}",
             "- **原典（PDF/HTML原本）との照合: not_run**（リポジトリに原本が無い。原典照合の成功ではない）",
             "- **この結果は記事の公開承認ではない**（publication_approved = false）", ""]
    if not report["views"]:
        lines += ["全体ビュー（`*active-state*.json` / `*full-view*.json`）は見つかりませんでした。", ""]
    for key, r in report["views"].items():
        if r.get("malformed") or r.get("unreadable"):
            lines += [f"## `{key}`", ""] + [f"- ❌ {f}" for f in r["failures"]] + [""]
            continue
        reuse, hist, qa, c = r["evidence_reuse"], r["article_history"], r["qa"], r["counts"]
        m = qa["mutation"]
        lines += [f"## `{key}`", "",
                  f"- 根拠 {r['records']} / 記事 {r['articles']}　検査：成功 {c['passed']}・失敗 {c['failed']}・**not_run {c['not_run']}**・意味の未検証 {c['unverified_meanings']}件",
                  f"- 根拠IDの再利用: 旧納品と同一 {reuse['reused']} / 新規 {reuse['new']} / **衝突 {len(reuse['collisions'])}**",
                  f"- 記事: 旧版と同一 {hist['same_text']} / 新規 {hist['new']} / 改訂 {hist['revisions']} / 履歴の不整合 {len(hist['failures'])}",
                  f"- 本文 {m['body'][0]}/{m['body'][1]}・引用ID {m['citation_id'][0]}/{m['citation_id'][1]}・基準日 {m['as_of'][0]}/{m['as_of'][1]}"
                  f"・差し替え {m['swap'][0]}/{m['swap'][1]}・反転 {m['flip'][0]}/{m['flip'][1]}"
                  f"（検出できず未検証として報告 {m.get('flip_declared_unverified', 0)}）・表記ゆれ {m['notation_invariance'][0]}/{m['notation_invariance'][1]}、{m['notation_detection'][0]}/{m['notation_detection'][1]}",
                  f"- 版管理: {qa['versioning']['facts_checked']}事実", ""]
        for f in r["failures"]:
            lines.append(f"- ❌ {f}")
        for w in r["warnings"]:
            lines.append(f"- ⚠ {w}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inbox", type=Path, default=INBOX)
    parser.add_argument("--view", type=Path, action="append", help="a whole view to check (default: auto-detect under the inbox)")
    parser.add_argument("--scope", choices=("export", "full"), default="export")
    parser.add_argument("--execution-origin", default="local")
    parser.add_argument("--require-view", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args.inbox, args.view, scope=args.scope, execution_origin=args.execution_origin, require_view=args.require_view)
    markdown = render_markdown(report)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "fullview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out_dir / "fullview.md").write_text(markdown, encoding="utf-8")
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(markdown)
    print(markdown)
    return 0 if report["verdict"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
