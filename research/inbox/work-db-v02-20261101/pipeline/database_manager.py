"""Local worker state, consistent backup and read-only admissions audits."""
import json
import sqlite3
import os
import tempfile
from contextlib import contextmanager, closing
from pathlib import Path


class DatabaseManager:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,priority INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,available_at REAL NOT NULL DEFAULT 0,
                result TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS dependencies(
                task_id TEXT NOT NULL REFERENCES tasks(id),depends_on TEXT NOT NULL REFERENCES tasks(id),
                PRIMARY KEY(task_id,depends_on),CHECK(task_id<>depends_on));
              CREATE TABLE IF NOT EXISTS checkpoints(
                task_id TEXT PRIMARY KEY REFERENCES tasks(id),data TEXT NOT NULL,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY,started REAL NOT NULL,ended REAL,pid INTEGER NOT NULL,
                status TEXT NOT NULL,completed INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY,run_id TEXT,task_id TEXT,event TEXT NOT NULL,
                detail TEXT,created REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS ready_tasks ON tasks(status,priority,available_at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def backup(self, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError("backup destination exists")
        with self.connect() as db, closing(sqlite3.connect(path)) as target:
            db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup failed validation")
        return path

    def snapshot_external(self, source, destination, check=lambda: None):
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if not source.is_file() or source == destination or destination.exists():
            raise ValueError("source must exist; snapshot must be a new file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="admissions-snapshot-", suffix=".partial", dir=destination.parent)
        os.close(fd)
        try:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
                with closing(sqlite3.connect(temporary)) as dst:
                    src.backup(dst, pages=128, progress=lambda *args: check(), sleep=.05)
            check()
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return destination

    @staticmethod
    def audit(path, check=lambda: None):
        path = Path(path).resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            db.execute("PRAGMA query_only=ON")
            def progress():
                check()
                return 0
            db.set_progress_handler(progress, 1000)
            integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
            foreign_keys = [list(r) for r in db.execute("PRAGMA foreign_key_check")]
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            counts = {}
            columns = {}
            for table in tables:
                check()
                quoted = '"' + table.replace('"', '""') + '"'
                counts[table] = db.execute("SELECT count(*) FROM " + quoted).fetchone()[0]
                columns[table] = [r[1] for r in db.execute("PRAGMA table_info(" + quoted + ")")]
        return {"source": str(path), "integrity": integrity, "foreign_keys": foreign_keys,
                "counts": counts, "columns": columns, "source_facts_reverified": False}
