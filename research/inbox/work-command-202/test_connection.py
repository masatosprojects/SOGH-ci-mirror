"""Work integration against the pinned PR #193 reference implementation."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tests import test_g03_read_contract as fixture
from src.db_contract import historical_read as hr
import importlib.util
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "research/inbox/work-updates-v2/pipeline/scripts/export_active.py"
spec = importlib.util.spec_from_file_location("work_active_export", SOURCE)
active = importlib.util.module_from_spec(spec)
spec.loader.exec_module(active)
from cited_article import export_cited_article, render_citations, export_json


class WorkReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make(self, **kw):
        return fixture.build(self.root, **kw)

    def exported(self, path, **kw):
        with closing(sqlite3.connect(path)) as db:
            return export_cited_article(db, "art-old", [(fixture.EV, kw or None)])

    def test_restored_payload_and_no_second_lookup(self):
        path = self.make()
        with closing(sqlite3.connect(path)) as db:
            result = export_cited_article(db, "art-old", [(fixture.EV, None)])
            row = result["citations"][0]
            self.assertEqual(json.loads(row["row"]["value_json"]), {"quota":16})
            self.assertEqual(row["source_sha256"], fixture.A)
            self.assertEqual(row["version_id"], "HV-1")
            self.assertEqual(row["provenance"]["restore_id"], "R-1")
            self.assertFalse(db.in_transaction)
            with hr.forbid_current_evidence_reads(db):
                self.assertEqual(json.loads(export_json(result)), result)
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute("SELECT * FROM facts").fetchall()

    def test_ordinary_without_history_schema(self):
        path = self.make(history=False, restored=False)
        with closing(sqlite3.connect(path)) as db:
            result = export_cited_article(db, "art-plain", [(fixture.EV2, None)])
            self.assertEqual(result["citations"][0]["kind"], "current_citation")

    def test_caller_snapshot_retained(self):
        path = self.make()
        with closing(sqlite3.connect(path)) as db:
            db.execute("BEGIN")
            export_cited_article(db, "art-old", [(fixture.EV, None)])
            self.assertTrue(db.in_transaction)

    def test_read_consumes_one_snapshot_during_revocation(self):
        path = self.make(wal=True)
        fired = []
        with closing(sqlite3.connect(path)) as db:
            def on_read(sql):
                if not fired and "SELECT" in sql.upper() and "restore_events" in sql:
                    fired.append(True)
                    fixture.sql(path, "INSERT INTO restore_revocations VALUES ('R-1','fixture','now','test')")
            db.set_trace_callback(on_read)
            result = export_cited_article(db, "art-old", [(fixture.EV, None)])
            self.assertTrue(fired)
            self.assertEqual(result["citations"][0]["version_id"], "HV-1")
            db.set_trace_callback(None)
            with self.assertRaises(hr.ReadContractError):
                export_cited_article(db, "art-old", [(fixture.EV, None)])

    def test_bound_export_tamper_refused(self):
        path = self.make()
        result = self.exported(path)
        result["citations"][0]["source_sha256"] = fixture.B
        with self.assertRaises(hr.ReadContractError):
            export_json(result)

    def test_bad_article_in_renderer_refused(self):
        path = self.make()
        with closing(sqlite3.connect(path)) as db:
            obj = hr.read_cited_evidence(db, "art-old", fixture.EV)
        with self.assertRaises(ValueError):
            render_citations("art-plain", [obj])

    def test_history_negative_conditions(self):
        cases = [
            ("missing_version", "DELETE FROM evidence_history_versions", "history_version_missing"),
            ("missing_pin", "DELETE FROM article_history_pins", "pin_missing"),
            ("missing_event", "DELETE FROM restore_events", "restore_unavailable"),
            ("missing_relation", "DELETE FROM article_evidence WHERE article_id='art-old'", "citation_missing"),
            ("source", "UPDATE article_history_pins SET source_sha256='" + fixture.B + "'", None),
            ("case", "UPDATE article_history_pins SET case_id='fiction-other-case'", None),
            ("scope", "UPDATE article_history_pins SET scope='other'", None),
            ("row_value", "UPDATE evidence_history_versions SET row_json=replace(row_json,'16','19')", "digest_mismatch"),
            ("no_downgrade", "DELETE FROM restored_articles", "registry_inconsistent"),
        ]
        for name, sql, code in cases:
            with self.subTest(name=name):
                path = fixture.build(self.root, name=name+".sqlite", append_only=False)
                fixture.sql(path, sql)
                with self.assertRaises(hr.ReadContractError) as caught:
                    self.exported(path)
                if code:
                    self.assertEqual(caught.exception.code, code)

    def test_expect_rejects_all_four_work_cases(self):
        path = self.make()
        for expected in ({"case_id":"wrong"}, {"scope":"wrong"},
                         {"record_subset":{"locator":"page 8"}}):
            with self.subTest(expected=expected):
                with self.assertRaises(hr.ReadContractError):
                    self.exported(path, **expected)
        with closing(sqlite3.connect(path)) as db:
            with self.assertRaises(hr.ReadContractError):
                export_cited_article(db, "art-old", [(fixture.EV2,None)])

    def test_legacy_article_without_evidence_ids(self):
        path = self.make(history=False, restored=False)
        text = "plain body [EV-2]"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE article_heads(article_id)")
            db.execute("CREATE TABLE update_batches(batch_id,state)")
            db.execute("ALTER TABLE revised_articles ADD COLUMN batch_id")
            db.execute("UPDATE article_versions SET body=? WHERE article_id='art-plain'",(text,))
            raw = db.execute("SELECT record_json,value_json FROM facts WHERE evidence_id=?", (fixture.EV2,)).fetchone()
            db.commit()
        record=json.loads(raw[0])
        record.update(value=json.loads(raw[1]),fact_key="deadline",source_pdf_sha256=fixture.B)
        base={"evidence":{fixture.EV2:record},"articles":[{"article_id":"art-plain","text":text}]}
        source=self.root/"legacy.json"
        source.write_text(json.dumps(base),encoding="utf-8")
        self.assertEqual(active.export_active(path,source),base)

    def test_active_export_rejects_previous_four_failures(self):
        path = self.make(history=False, restored=False)
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE article_heads(article_id)")
            db.execute("CREATE TABLE update_batches(batch_id,state)")
            db.execute("ALTER TABLE revised_articles ADD COLUMN batch_id")
            db.commit()
            raw = db.execute("SELECT record_json,value_json FROM facts WHERE evidence_id=?", (fixture.EV2,)).fetchone()
        record = json.loads(raw[0])
        record.update(value=json.loads(raw[1]), fact_key="deadline", case_id=fixture.CASE,
                      source_pdf_sha256=fixture.B)
        base = {"evidence":{fixture.EV2:record}, "articles":[
            {"article_id":"art-plain","text":"plain body","evidence_ids":[fixture.EV2]}]}
        source = self.root/"base.json"
        source.write_text(json.dumps(base),encoding="utf-8")
        self.assertEqual(active.export_active(path,source),base)
        for field, changed in (("case_id","wrong"),("scope","wrong"),("locator","page 8")):
            with self.subTest(field=field):
                bad=copy.deepcopy(base)
                bad["evidence"][fixture.EV2][field]=changed
                source.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaises(ValueError):
                    active.export_active(path,source)
        bad=copy.deepcopy(base)
        bad["articles"][0]["evidence_ids"]=[fixture.EV]
        source.write_text(json.dumps(bad),encoding="utf-8")
        with self.assertRaises(ValueError):
            active.export_active(path,source)


    def test_both_documented_cli_entry_points_work_without_pythonpath(self):
        path = self.make(history=False, restored=False)
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE article_heads(article_id)")
            db.execute("CREATE TABLE update_batches(batch_id,state)")
            db.execute("ALTER TABLE revised_articles ADD COLUMN batch_id")
            raw = db.execute("SELECT record_json,value_json FROM facts WHERE evidence_id=?",
                             (fixture.EV2,)).fetchone()
            db.commit()
        record = json.loads(raw[0])
        record.update(value=json.loads(raw[1]), fact_key="deadline", source_pdf_sha256=fixture.B)
        base = {"evidence": {fixture.EV2: record}, "articles": [
            {"article_id": "art-plain", "text": "plain body", "evidence_ids": [fixture.EV2]}]}
        source = self.root / "cli-base.json"
        source.write_text(json.dumps(base), encoding="utf-8")
        before = hashlib.sha256(path.read_bytes()).digest()
        env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
        for name in ("work-updates-v2", "work-faq-v3"):
            with self.subTest(pipeline=name):
                pipeline = ROOT / "research/inbox" / name / "pipeline"
                output = self.root / (name + ".json")
                proc = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", "scripts/export_active.py",
                     "--database", str(path), "--base-export", str(source), "--output", str(output)],
                    cwd=pipeline, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8")), base)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_detached_cli_reports_the_missing_contract_before_opening_inputs(self):
        script = self.root / "export_active.py"
        script.write_bytes(SOURCE.read_bytes())
        output = self.root / "output.json"
        proc = subprocess.run(
            [sys.executable, "-I", "-B", str(script), "--database", str(self.root / "absent.sqlite"),
             "--base-export", str(self.root / "absent.json"), "--output", str(output)],
            cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("full SOGH-collab checkout with the g3 read contract", proc.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
