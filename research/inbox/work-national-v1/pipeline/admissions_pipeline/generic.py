"""Config profile -> original-bound facts -> SQLite -> preparation drafts -> Claude QA."""
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from .articles import claude_export
from .claude_adapter import run_qa
from .dimensions import migrate, save_dimensions
from .extract import PROFILES, PROFILE_VERSION
from .profiles import extract_profile, load_profile
from .store import EvidenceStore, canonical

SERIES = {
    "overview": ("制度と手続の確認", "全体を見渡し、必要な確認事項を自分用の一覧に整理してください。"),
    "documents": ("出願準備と書類の整理", "所定様式を大学公式サイトから取得し、学校への作成依頼と自分で書く部分を分けて管理してください。活動の名称だけでなく、取り組んだ目的と自分の役割を整理すると説明に役立ちます。"),
    "interview": ("面接に向けた準備", "提出した自己申告書を読み直し、取り組んだ理由、根拠、学んだことを自分の言葉で説明する練習をしてください。これは練習のための助言であり、大学が公表した想定質問や採点基準ではありません。"),
}
SERIES_KEYS = {"overview": {"quota", "common_test", "postal_period", "interview"},
               "documents": {"postal_period", "quota"},
               "interview": {"interview", "interview_scope", "common_test"}}


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
    selected = [f for f in original.facts if f["key"] in SERIES_KEYS[series]]
    if not selected:
        raise ValueError("no evidence for requested series")
    claims = [{"key": f["key"], "evidence_id": f["evidence_id"],
               "text": "。".join(s + "[" + f["evidence_id"] + "]" for s in f["draft_sentence"].split("。") if s) + "。"} for f in selected]
    refs = [f"- [{f['evidence_id']}] 公式募集要項 PDF p." + "・".join(str(p["page"]) for p in f["proofs"]) + "：" + profile["url"] + f"#page={f['proofs'][0]['page']}" for f in selected]
    text = "\n\n".join(["# " + title, "作業基準日：" + as_of.isoformat() + "。未公開草案。",
        "## 公式資料で確認した事実", *[c["text"] for c in claims],
        "## 編集上の助言（大学公表の事実とは区別）", SERIES[series][1],
        "## 追加確認が必要な項目", "出願資格の個別判定、必要書類の全件、最新の訂正・追加案内は別途確認が必要です。不明な項目は推測していません。最新情報は大学公式サイトでご確認ください。合否を保証するものではありません。",
        "## 根拠資料", "\n".join(refs)]) + "\n"
    digest = hashlib.sha256(canonical([pack, profile, series, as_of.isoformat(), "generic-draft-v2"]).encode()).hexdigest()
    return {"article_id": profile["case_id"] + ":" + series + ":" + digest[:16], "case_id": profile["case_id"],
            "series": series, "input_hash": digest, "title": title, "text": text, "claims": claims,
            "evidence_ids": [f["evidence_id"] for f in selected], "publish_allowed": False,
            "claim": {k: profile[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}}


def run(profile_path, pdf_path, database, output, collab, as_of):
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
