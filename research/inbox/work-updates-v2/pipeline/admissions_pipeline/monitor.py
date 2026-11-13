"""Resumable official-source monitor. No scheduler registration, posting, or AI."""
import argparse
import hashlib
import json
import sqlite3
import time
import urllib.error
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .collector import Collector, official_url
from .process_lock import ProcessLock
from .store import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets(url TEXT PRIMARY KEY,source_id TEXT NOT NULL,config_json TEXT NOT NULL,
 last_attempt REAL,last_success REAL,next_due REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,
 last_sha TEXT,last_snapshot TEXT,last_error TEXT);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started REAL NOT NULL,ended REAL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),
 url TEXT NOT NULL REFERENCES targets(url),checked_at REAL NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL,
 previous_sha TEXT,current_sha TEXT,old_snapshot TEXT,new_snapshot TEXT,error TEXT,
 analysis_status TEXT NOT NULL DEFAULT 'pending');
"""


class Monitor:
    def __init__(self, root, config, *, clock=time.time, collector=None):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.config, self.clock = config, clock
        self.collector = collector or Collector(self.root / "bodies", config["allowed_hosts"], delay=config.get("delay_seconds", 2))
        with self.connect() as db:
            db.executescript(SCHEMA)
            if "analysis_status" not in {r[1] for r in db.execute("PRAGMA table_info(checks)")}:
                db.execute("ALTER TABLE checks ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'pending'")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.root / "monitor.sqlite", timeout=20)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback(); raise

    def configure(self):
        if not 60 <= self.config.get("interval_seconds", 3600) <= 604800:
            raise ValueError("collection interval must be 1 minute to 7 days")
        seen = set()
        with self.connect() as db:
            for target in self.config["targets"]:
                url = target["url"]; official_url(url, self.config["allowed_hosts"])
                if url in seen:
                    continue  # One URL, one request per cycle even if multiple universities/roles refer to it.
                seen.add(url)
                sid = target.get("source_id", target["case"] + "-" + target["role"])
                old = db.execute("SELECT source_id FROM targets WHERE url=?", (url,)).fetchone()
                if old and old[0] != sid:
                    raise ValueError("source identity changed for existing URL")
                db.execute("INSERT INTO targets(url,source_id,config_json) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET config_json=excluded.config_json",
                           (url, sid, canonical(target)))
        return seen

    def _fetch(self, row):
        limit = min(3, max(1, self.config.get("max_attempts", 2)))
        last = None
        for attempt in range(1, limit + 1):
            try:
                record = self.collector.fetch(row["url"])
                if record["kind"] == "html":
                    # Strict decoding; replacement characters must not look like a valid new edition.
                    text = Path(record["local_path"]).read_bytes().decode("utf-8", errors="strict")
                    if "\ufffd" in text:
                        raise UnicodeError("replacement character in official source")
                supersedes=json.loads(row['config_json']).get('supersedes_sha256',[])
                if any(not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in supersedes):
                    raise ValueError('invalid explicit source lineage')
                snapshot = self.collector.write_snapshot(record, row["source_id"], self.root / "snapshots",supersedes=supersedes)
                return record, snapshot, attempt
            except Exception as exc:
                last = exc
                retryable = isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))
                if isinstance(exc, urllib.error.HTTPError):
                    retryable = exc.code in (408, 429, 500, 502, 503, 504)
                if not retryable or attempt == limit:
                    exc.monitor_attempts = attempt
                    raise
                time.sleep(min(5, 2 ** (attempt - 1)))
        raise last

    def run_once(self, force=False, export_path=None, collab_root=None):
        with ProcessLock(self.root / "monitor.lock"):
            urls = self.configure()
            run_id, started = uuid.uuid4().hex, self.clock()
            with self.connect() as db:
                # An OS lock has been acquired: no previous 'running' process can still own this root.
                db.execute("UPDATE runs SET status='interrupted',ended=? WHERE status='running'", (started,))
                db.execute("INSERT INTO runs VALUES(?,?,NULL,'running')", (run_id, started))
                targets = [dict(r) for r in db.execute("SELECT * FROM targets ORDER BY url") if r["url"] in urls]
            results, processed = [], 0
            for row in targets:
                if (self.root / "STOP").exists():
                    break
                now = self.clock()
                if not force and row["next_due"] > now:
                    results.append({"url": row["url"], "status": "not_due", "last_success": row["last_success"]}); continue
                if processed >= min(100, max(1, self.config.get("max_targets_per_run", 100))):
                    results.append({"url": row["url"], "status": "deferred_batch_limit"}); continue
                processed += 1
                with self.connect() as db:
                    db.execute("UPDATE targets SET last_attempt=? WHERE url=?", (now, row["url"]))
                try:
                    record, snapshot, attempts = self._fetch(row)
                    status = "first_fetch" if row["last_sha"] is None else ("unchanged" if row["last_sha"] == record["sha256"] else "changed")
                    with self.connect() as db:
                        db.execute("UPDATE targets SET last_success=?,next_due=?,failures=0,last_sha=?,last_snapshot=?,last_error=NULL WHERE url=?",
                                   (self.clock(), self.clock() + self.config.get("interval_seconds", 3600), record["sha256"], str(snapshot.resolve()), row["url"]))
                        db.execute("INSERT INTO checks(run_id,url,checked_at,status,attempts,previous_sha,current_sha,old_snapshot,new_snapshot) VALUES(?,?,?,?,?,?,?,?,?)",
                                   (run_id, row["url"], now, status, attempts, row["last_sha"], record["sha256"], row["last_snapshot"], str(snapshot.resolve())))
                    results.append({"url": row["url"], "source_id": row["source_id"], "status": status, "attempts": attempts,
                                    "sha256": record["sha256"], "previous_sha256": row["last_sha"], "retrieved_at": record["retrieved_at"],
                                    "old_snapshot": row["last_snapshot"], "new_snapshot": str(snapshot.resolve())})
                except Exception as exc:
                    error = type(exc).__name__ + (":" + str(exc.code) if isinstance(exc, urllib.error.HTTPError) else "")
                    with self.connect() as db:
                        db.execute("UPDATE targets SET failures=failures+1,next_due=?,last_error=? WHERE url=?",
                                   (self.clock() + min(86400, self.config.get("failure_backoff_seconds", 300) * 2 ** min(row["failures"], 8)), error, row["url"]))
                        db.execute("INSERT INTO checks(run_id,url,checked_at,status,attempts,error) VALUES(?,?,?,'failed',?,?)",
                                   (run_id, row["url"], now, getattr(exc, "monitor_attempts", 1), error))
                    results.append({"url": row["url"], "status": "failed", "error": error})
            report = {"run_id": run_id, "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                      "results": results, "success": not any(x["status"] == "failed" for x in results),
                      "stopped": (self.root / "STOP").exists(), "publication_allowed": False}
            if export_path and collab_root and not report["stopped"]:
                try:
                    report["versioning"] = self.versioning(results, export_path, collab_root)
                except Exception as exc:
                    report["versioning"] = {"success": False, "error": type(exc).__name__, "pending_checks_retained": True}
                if not report["versioning"]["success"]:
                    report["success"] = False
            report["stopped"] = (self.root / "STOP").exists()
            out = self.root / "reports"; out.mkdir(exist_ok=True)
            path = out / (run_id + ".json")
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            with self.connect() as db:
                db.execute("UPDATE runs SET ended=?,status=? WHERE id=?", (self.clock(), "stopped" if report["stopped"] else ("completed" if report["success"] else "failed"), run_id))
            return report

    def versioning(self, results, export_path, collab_root):
        import os, subprocess, sys
        manifest = self.root / "reports" / ("versions-" + uuid.uuid4().hex + ".json")
        manifest.parent.mkdir(exist_ok=True)
        with self.connect() as db:
            active = {t["url"] for t in self.config["targets"]}
            age_limit = self.config.get("max_snapshot_age_seconds", max(3600, self.config.get("interval_seconds", 3600)*2))
            current = [r["last_snapshot"] for r in db.execute("SELECT * FROM targets WHERE last_snapshot IS NOT NULL AND last_error IS NULL")
                       if r["url"] in active and self.clock() - r["last_success"] <= age_limit]
            pending = [dict(r) for r in db.execute("SELECT * FROM checks WHERE analysis_status='pending'")]
        old = sorted({x["old_snapshot"] for x in pending if x["old_snapshot"]})
        output = manifest.with_name(manifest.stem + "-impact.json")
        args = [sys.executable, "-B", "-X", "utf8", "-m", "src.versioning.impact", "--export", str(Path(export_path).resolve()), "--require-all-assessed", "--json-out", str(output.resolve())]
        for path in current: args += ["--new", str(Path(path).resolve())]
        for path in old: args += ["--old", str(Path(path).resolve())]
        # Empty current set must not accidentally run an unassessed-success check.
        if not current: return {"success": False, "reason": "no_successful_snapshots"}
        result = subprocess.run(args, cwd=collab_root, capture_output=True, text=True, encoding="utf-8", timeout=120,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if not output.exists(): return {"success": False, "reason": "versioning_report_missing"}
        impact = json.loads(output.read_text(encoding="utf-8"))
        differences = []
        for check in pending:
            if (self.root / "STOP").exists(): return {"success": False,"reason":"stop_requested","pending_checks_retained":True}
            if not check["old_snapshot"] or not check["new_snapshot"] or check["previous_sha"] == check["current_sha"]:
                continue
            diff_path = manifest.with_name(manifest.stem + f"-diff-{check['id']}.json")
            diff_result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "src.versioning.diff",
                "--old", str(Path(check["old_snapshot"]).resolve()), "--new", str(Path(check["new_snapshot"]).resolve()),
                "--json-out", str(diff_path.resolve())], cwd=collab_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
            if diff_result.returncode not in (0,1) or not diff_path.exists():
                return {"success": False, "reason": "source_diff_failed", "pending_checks_retained": True}
            diff = json.loads(diff_path.read_text(encoding="utf-8"))
            differences.append({"url": check["url"], "old_sha256": check["previous_sha"], "new_sha256": check["current_sha"],
                "change_class": "byte_only" if diff["identical_text"] else "content_changed", "diff_report_path": str(diff_path),
                "changed_blocks": len(diff.get("changes", [])), "value_changed_blocks": sum(bool(x.get("value_change")) for x in diff.get("changes", []))})
        if result.returncode in (0, 1):
            with self.connect() as db:
                db.executemany("UPDATE checks SET analysis_status='assessed' WHERE id=?", [(x["id"],) for x in pending])
        return {"success": result.returncode in (0, 1), "requires_review": result.returncode == 1,
                "safe_without_review": result.returncode == 0, "exit_code": result.returncode, "report_path": str(output),
                "summary": impact["summary"], "republish_required": impact["republish_required"],
                "articles_to_review": impact["articles_to_review"], "unassessed_evidence": impact["unassessed_evidence"], "source_differences": differences}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True); p.add_argument("--state", type=Path, required=True)
    p.add_argument("--force", action="store_true", help="explicit immediate check ignoring due time")
    p.add_argument("--restart", action="store_true", help="clear STOP only after acquiring the service lock")
    p.add_argument("--loop", action="store_true"); p.add_argument("--export", type=Path); p.add_argument("--collab", type=Path)
    args = p.parse_args()
    with ProcessLock(args.state / "service.lock"):
        if args.restart:
            (args.state / "STOP").unlink(missing_ok=True)
        return run_cli(args)


def run_cli(args):
    monitor = Monitor(args.state, json.loads(args.config.read_text(encoding="utf-8")))
    while True:
        report = monitor.run_once(args.force, args.export, args.collab)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if not args.loop or report["stopped"]: break
        args.force = False
        for _ in range(60):
            if (args.state / "STOP").exists():
                (args.state/'reports'/'service-stop.json').write_text(json.dumps({'stopped':True,'reason':'stop_requested_while_idle','stopped_at':datetime.now(timezone.utc).isoformat()}),encoding='utf-8')
                return
            time.sleep(1)
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__": main()
