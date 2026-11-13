"""Shared helpers of the DB acceptance tests (tests/test_db_acceptance_*.py). Not a test module.

Every database built here is SYNTHETIC (invented university, invented facts, a temporary file). It is driven through Work's own
store code (`admissions_pipeline.store` / `revisions`, imported read-only) so that the audit judges what that code really writes.
A pass on these is a pass on SYNTHETIC data: tests record the target kind and never call it a real-database result.
"""
from __future__ import annotations

import copy
import hashlib
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STAGE1_PATCH = REPO / "patches" / "m1-stage1" / "work-pipeline-stage1.patch"


def _patched_default() -> Path:
    """Work's current pipeline (research/inbox/work-faq-v3, delivered and never written) with the M1 stage-1 patch applied to a COPY in a temporary directory: the guarded database
    (migration 0004) needs a connection that registers the write capability and an update path that approves a batch before it moves a head."""
    import atexit
    import shutil
    import subprocess
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="sogh-pipeline-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    shutil.copytree(REPO / "research" / "inbox" / "work-faq-v3" / "pipeline", root / "pipeline", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    subprocess.run(["git", "-c", "core.autocrlf=false", "apply", str(STAGE1_PATCH)], cwd=root / "pipeline", check=True, capture_output=True)
    return root / "pipeline"


# SOGH_PIPELINE_ROOT runs the same tests against another copy of Work's pipeline (tests/test_work_stage1_patch.py uses it for the delivered and the patched copy)
PIPELINE = Path(os.environ["SOGH_PIPELINE_ROOT"]) if os.environ.get("SOGH_PIPELINE_ROOT") else _patched_default()
sys.dont_write_bytecode = True  # Work's manifest lists every file: never leave bytecode in its directory
sys.path.insert(0, str(PIPELINE))

from admissions_pipeline.extract import Extracted  # noqa: E402
from admissions_pipeline.notice_articles import revise_article  # noqa: E402
from admissions_pipeline.revisions import RevisionStore  # noqa: E402
from admissions_pipeline.store import EvidenceStore, canonical  # noqa: E402

from src.integration import db_audit as da  # noqa: E402

TARGET_KIND = "synthetic"
REGISTRY = {"fact_keys": {"generative_ai_policy": {"status": "active"}, "fee_refund": {"status": "active"},
                          "multilingual_evaluation": {"status": "proposed"}}}


def profile(university="試験大学", faculty="試験学部", method="試験方式", fiscal_year=2027, sha="a" * 64, department=None) -> dict[str, Any]:
    return {"university": university, "faculty": faculty, "department": department, "admission_method": method, "fiscal_year": fiscal_year,
            "exam_year": fiscal_year - 1, "sha256": sha, "url": f"https://example.ac.jp/{university}/{fiscal_year}.pdf"}


def scope(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}


def ingest_cycle(store: EvidenceStore, case_id: str, p: dict[str, Any], tmp: Path, count: int = 16, eid: str | None = None) -> str:
    """Register one cycle with one initial fact (募集人員) and one base article, the way Work's extractor stores them."""
    eid = eid or f"EV-{case_id}-1"
    text = f"募集人員は{count}名です。"
    fact = {"evidence_id": eid, "key": "quota", "fact_key": "quota", "value": {"count": count, "unit": "名"}, "fiscal_year": p["fiscal_year"],
            "admission_method": p["admission_method"], "university": p["university"], "faculty": p["faculty"], "source_sha256": p["sha256"],
            "source_url": p["url"], "proofs": [{"page": 1, "quote": text}], "verification": "source_checked_for_saved_version"}
    store.ingest(Extracted(case_id, p, tmp / f"{case_id}.pdf", [text], [fact]), "2026-11-01")
    article = {"article_id": f"art-{case_id}", "case_id": case_id, "input_hash": hashlib.sha256(case_id.encode()).hexdigest(), "series": "overview",
               "title": "試験記事", "text": f"# 試験記事\n\n募集人員は{count}名[{eid}]です。\n\n## 根拠資料\n- [{eid}] 募集要項 PDF p.1\n",
               "evidence_ids": [eid], "claim": scope(p)}
    store.save_article(article, tmp / f"{case_id}.md")
    return eid


def make_native(tmp: Path, name: str = "native.sqlite") -> tuple[Path, dict[str, Any]]:
    """A v0.3-style database (EvidenceStore only) with one cycle, one fact and one article."""
    path = tmp / name
    store = EvidenceStore(path)
    p = profile()
    ingest_cycle(store, "case", p, tmp)
    return path, p


def notice(p: dict[str, Any], eid: str = "EV-U-1", logical: str = "notice", case: str = "case", **over: Any) -> dict[str, Any]:
    rec = {"evidence_id": eid, "logical_id": logical, "case_id": case, **scope(p), "fact_key": "generative_ai_policy", "source_sha256": "b" * 64,
           "source_kind": "html", "source_url": "https://example.ac.jp/faq", "proofs": [{"page": 1}], "value": {"allowed": "FAQの説明"},
           "sentences": ["生成AIの使用を明示します。"], "temporal_status": "current_faq", "retrieved_at": "2026-11-01"}
    rec.update(over)
    return rec


def approve(store: RevisionStore, record: dict[str, Any], article: dict[str, Any], previous_id: str | None = None,
            as_of: date = date(2026, 11, 1)) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    batch = store.stage([record], REGISTRY)
    revised = revise_article(article, store.effective_records(batch), as_of, previous_id)
    qa = {"success": True, "batch_input_sha": batch["input_sha"], "articles_sha256": hashlib.sha256(canonical([revised]).encode()).hexdigest()}
    return batch, revised, qa, store.finalize(batch, [revised], qa, REGISTRY)


def base_article(store: EvidenceStore, case: str = "case") -> dict[str, Any]:
    with store.connect() as db:
        row = db.execute("SELECT * FROM article_versions WHERE case_id=? ORDER BY article_id LIMIT 1", (case,)).fetchone()
        ev = [r[0] for r in db.execute("SELECT evidence_id FROM article_evidence WHERE article_id=?", (row["article_id"],))]
    return {"article_id": row["article_id"], "case_id": row["case_id"], "input_hash": row["input_hash"], "series": row["series"], "title": row["title"],
            "text": row["body"], "evidence_ids": ev, "claim": scope(profile())}


def audit(path: Path, baseline: Path | None = None) -> dict[str, Any]:
    return da.audit(path, baseline, TARGET_KIND)


def failing(path: Path, baseline: Path | None = None) -> dict[str, Any]:
    r = audit(path, baseline)
    return {k: v for k, v in r["invariants"].items() if v["status"] == "fail"}


def app_connect(path):
    """A connection the way SOGH's own code opens one: the write capability registered and recursive triggers on (see patches/m1-stage1). Any other connection is refused by the guards of migration 0004."""
    db = sqlite3.connect(path)
    db.create_function("sogh_write_ok", 0, lambda: 1)
    db.execute("PRAGMA recursive_triggers=ON")
    return db


def sql(path: Path, statement: str, *args: Any) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute(statement, args)
        db.commit()


def counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as db:
        return {n: db.execute(f"SELECT count(*) FROM {n}").fetchone()[0]
                for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}


def heads(path: Path) -> dict[str, dict[str, str]]:
    with closing(sqlite3.connect(path)) as db:
        return {"evidence": dict(db.execute("SELECT logical_id,evidence_id FROM evidence_heads")),
                "articles": dict(db.execute("SELECT base_article_id,article_id FROM article_heads"))}


__all__ = ["copy", "TARGET_KIND"]
