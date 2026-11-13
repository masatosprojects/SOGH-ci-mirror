"""Config profile -> original-bound facts -> SQLite -> preparation drafts -> Claude QA."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from .articles import claude_export
from .claude_adapter import run_qa
from .dimensions import migrate, save_dimensions
from .extract import PROFILES, PROFILE_VERSION
from .profiles import extract_profile, load_profile
from .store import EvidenceStore, canonical
from .process_lock import ProcessLock

SERIES = {
    "overview": ("制度と手続の確認", "全体を見渡し、必要な確認事項を自分用の一覧に整理してください。"),
    "documents": ("出願準備と書類の整理", "所定様式を大学公式サイトから取得し、学校への作成依頼と自分で書く部分を分けて管理してください。活動の名称だけでなく、取り組んだ目的と自分の役割を整理すると説明に役立ちます。"),
    "interview": ("面接に向けた準備", "提出する書類と大学で学びたいことを読み直し、取り組んだ理由、根拠、学んだことを自分の言葉で説明する練習をしてください。これは練習のための助言であり、大学が公表した想定質問や採点基準ではありません。"),
}
SERIES_KEYS = {"overview": {"quota", "common_test", "online_period", "postal_period", "interview", "statement_length"},
               "documents": {"postal_period", "online_period", "quota", "statement_length"},
               "interview": {"interview", "interview_scope", "common_test", "statement_length"}}


def draft(pack, profile, series, as_of):
    if series not in SERIES:
        raise ValueError("unknown article series")
    # Compare the COMPLETE pack with a fresh extraction, including metadata.
    original = extract_profile(profile, pack["source"]["local_path"])
    if canonical(pack["facts"]) != canonical(sorted(original.facts, key=lambda f: f["evidence_id"])):
        raise ValueError("pack facts differ from original profile")
    for key in ("university", "faculty", "department", "admission_method", "fiscal_year", "exam_year"):
        if pack["cycle"][key] != profile[key]:
            raise ValueError("cycle scope mismatch")
    if pack["source"]["sha256"] != profile["sha256"] or pack["source"]["url"] != profile["url"]:
        raise ValueError("source provenance mismatch")
    title = f"【{profile['fiscal_year']}年度入学】{profile['university']} {profile['faculty']} {profile['admission_method']}｜{SERIES[series][0]}"
    policy=profile.get('article_policy',{}).get(series,{})
    keys=set(policy.get('fact_keys',SERIES_KEYS[series]));available={f['key'] for f in original.facts}
    if policy and (not keys or not keys<=available or not set(policy.get('shared_fact_keys',[]))<=keys):
        raise ValueError('article policy requests unproven facts')
    selected = [f for f in original.facts if f["key"] in keys]
    if not selected:
        raise ValueError("no evidence for requested series")
    def cited(fact):
        import re
        cite="["+fact["evidence_id"]+"]"
        return "。".join(re.sub(r"(\d[\d,]*(?:名|人|円|字))",lambda m:m[0]+cite,s)+cite for s in fact["draft_sentence"].split("。") if s)+"。"
    claims = [{"key": f["key"], "evidence_id": f["evidence_id"],"text":cited(f)} for f in selected]
    refs = [f"- [{f['evidence_id']}] 公式募集要項 PDF p." + "・".join(str(p) for p in sorted({p["page"] for p in f["proofs"]})) + "：" + profile["url"] + f"#page={f['proofs'][0]['page']}" for f in selected]
    fact_sections=['## 公式資料で確認した事実',*[c['text'] for c in claims]]
    if policy:
        shared=set(policy.get('shared_fact_keys',[]))
        fact_sections=['## この方式固有の公式事実',*[c['text'] for c in claims if c['key'] not in shared],
                       '## 複数方式に共通する公式手続',*[c['text'] for c in claims if c['key'] in shared]]
    text = "\n\n".join(["# " + title, "作業基準日：" + as_of.isoformat() + "。未公開草案。",
        *fact_sections,
        "## 編集上の助言（大学公表の事実とは区別）", SERIES[series][1],
        "## 追加確認が必要な項目", "出願資格の個別判定、必要書類の全件、最新の訂正・追加案内は別途確認が必要です。不明な項目は推測していません。最新情報は大学公式サイトでご確認ください。合否を保証するものではありません。",
        "## 根拠資料", "\n".join(refs)]) + "\n"
    digest = hashlib.sha256(canonical([pack, profile, series, as_of.isoformat(), "generic-draft-v4"]).encode()).hexdigest()
    return {"article_id": profile["case_id"] + ":" + series + ":" + digest[:16], "case_id": profile["case_id"],
            "series": series, "input_hash": digest, "title": title, "text": text, "claims": claims,
            "evidence_ids": [f["evidence_id"] for f in selected], "publish_allowed": False,
            "claim": {k: profile[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}}


def fingerprint(db):
    state=[]
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        q='"'+table.replace('"','""')+'"'
        columns=[r[1] for r in db.execute("PRAGMA table_info("+q+")")]
        rows=sorted([list(r) for r in db.execute('SELECT * FROM '+q)],key=repr)
        state.append([table,columns,rows])
    return hashlib.sha256(canonical(state).encode()).hexdigest()


def promote_candidate(candidate,target,before):
    target=Path(target)
    if before is None and target.exists():raise ValueError('target appeared during validation')
    with closing(sqlite3.connect(target,timeout=20)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('ATTACH DATABASE ? AS candidate',(str(Path(candidate).resolve()),))
        db.execute('BEGIN IMMEDIATE')
        try:
            if before is not None and fingerprint(db)!=before:raise ValueError('target changed during validation')
            tables=list(db.execute("SELECT name,sql FROM candidate.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"))
            for table,ddl in tables:
                q='"'+table.replace('"','""')+'"'
                exists=db.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                if not exists:db.execute(ddl)
                cols=[r[1] for r in db.execute('PRAGMA candidate.table_info('+q+')')]
                current=[r[1] for r in db.execute('PRAGMA main.table_info('+q+')')]
                if cols!=current:
                    if table=='cycle_editions' and set(cols)-set(current)=={'profile_json'}:
                        db.execute('ALTER TABLE cycle_editions ADD COLUMN profile_json TEXT')
                    else:raise ValueError('unsupported schema difference; explicit migration required')
                selected=','.join('"'+c.replace('"','""')+'"' for c in cols)
                old_rows=set(db.execute('SELECT '+selected+' FROM main.'+q))
                candidate_rows=set(db.execute('SELECT '+selected+' FROM candidate.'+q))
                if not old_rows<=candidate_rows:raise ValueError('candidate would modify existing rows')
                db.execute('INSERT OR IGNORE INTO main.'+q+' ('+selected+') SELECT '+selected+' FROM candidate.'+q)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('promotion integrity failure')
            db.commit()
        except BaseException:
            db.rollback();raise


def independent_gate(collab,export_path,pdf_dir,output):
    code='''
import json,sys
from pathlib import Path
from src.integration.audit_handoff import check_source_pdfs,check_values_in_quotes,check_export
e=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
r={"source_pdfs":check_source_pdfs(e,Path(sys.argv[2])),"values_in_quotes":check_values_in_quotes(e),"export":check_export(e)}
Path(sys.argv[3]).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
raise SystemExit(0 if all(v["status"]=="pass" for v in r.values()) else 1)
'''
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(Path(export_path).resolve()),str(Path(pdf_dir).resolve()),str(Path(output).resolve())],cwd=collab,capture_output=True,text=True,encoding='utf-8',timeout=180)
    return result.returncode==0 and Path(output).is_file()


def run(profile_path,pdf_path,database,output,collab,as_of):
    if Path(output).exists():raise FileExistsError('use a fresh output directory')
    database=Path(database).resolve();database.parent.mkdir(parents=True,exist_ok=True)
    with ProcessLock(database.with_suffix('.updates.lock')):
        candidate=database.parent/('candidate-'+uuid.uuid4().hex+'.sqlite')
        before=None
        if database.exists():
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as src:
                if not src.execute("SELECT 1 FROM sqlite_master WHERE name='facts' AND type='table'").fetchone():raise ValueError('target must be a v0.3+ working DB, never a legacy original')
                with closing(sqlite3.connect(candidate)) as dst:src.backup(dst)
            with closing(sqlite3.connect(candidate)) as db:before=fingerprint(db)
        try:
            report=_run(profile_path,pdf_path,candidate,output,collab,as_of)
        except BaseException as exc:
            candidate.with_suffix('.failure.json').write_text(json.dumps({'success':False,'promoted':False,'error':type(exc).__name__,'candidate':str(candidate)}),encoding='utf-8')
            raise
        report['independent_source_gate']=False
        if report['success']:
            report['independent_source_gate']=independent_gate(collab,Path(output)/'claude-compatible-export.json',Path(pdf_path).parent,Path(output)/'independent-source-audit.json')
        report['success']=report['success'] and report['independent_source_gate']
        report['promoted']=False
        if report['success']:
            try:
                promote_candidate(candidate,database,before);report['promoted']=True
            except ValueError as exc:
                report['success']=False;report['promotion_error']=str(exc)
        report['candidate_counts']=report['after']
        if database.exists():report['after']=EvidenceStore(database).counts()
        else:report['after']={}
        report['target_database']=str(database)
        (Path(output)/'run-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        # The validated candidate remains a local artifact, including on rejection.
        candidate.replace(Path(output)/'candidate.sqlite')
        return report


def _run(profile_path, pdf_path, database, output, collab, as_of):
    profile = load_profile(profile_path)
    extracted = extract_profile(profile, pdf_path)  # Fail before touching DB on incomplete extraction.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    store = EvidenceStore(database)
    before = store.counts()
    backup = migrate(store, output / "before-migration.sqlite")
    observed = datetime.now(timezone.utc).isoformat()
    for case, original_profile in PROFILES.items():
        with store.connect() as db:
            present = db.execute("SELECT 1 FROM facts WHERE case_id=? AND source_sha256=?", (case, original_profile["sha256"])).fetchone()
        if present:
            metadata = dict(original_profile, case_id=case, profile_version=PROFILE_VERSION,
                            dimensions={"selection_category": "comprehensive", "entry_months": [4, 9] if case.startswith("keio") else [4],
                                        "round_name": original_profile["admission_method"],
                                        "scope": {"faculty": original_profile["faculty"], "department": original_profile["department"]}})
            save_dimensions(store, metadata, observed)
    store.ingest(extracted, observed[:10])
    save_dimensions(store, profile, observed)
    pack = store.pack(profile["case_id"], profile["sha256"])
    articles = [draft(pack, profile, series, as_of) for series in SERIES]
    for a in articles:
        path = output / (a["series"] + ".md")
        path.write_text(a["text"], encoding="utf-8")
        store.save_article(a, path)
    for name, data in (("article-input.json", pack), ("source-facts.json", extracted.facts), ("claude-compatible-export.json", claude_export([pack], articles))):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot = store.snapshot(output / "qa-input.sqlite")
    qa = run_qa(collab, (output / "claude-compatible-export.json").resolve(), snapshot.resolve(), output.resolve())
    with store.connect() as db:
        db.execute("INSERT INTO qa_runs VALUES(?,?,?,?)", (str(output.resolve()), qa["claude_commit"], str(output / "run-report.json"), int(qa["success"])))
    store.snapshot(output / "admissions-snapshot.sqlite")
    report = {"success": qa["success"], "case_id": profile["case_id"], "facts": len(extracted.facts), "drafts": len(articles),
              "before": before, "after": store.counts(), "backup": backup, "qa": qa,
              "visual_review": profile.get("visual_review", []), "unresolved": profile.get("unresolved", []), "publication_allowed": False}
    (output / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--collab", type=Path, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = p.parse_args()
    report = run(args.profile, args.pdf, args.database, args.output, args.collab, args.as_of)
    print(json.dumps({k: report[k] for k in ("success", "case_id", "facts", "drafts", "after")}, ensure_ascii=False))
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
