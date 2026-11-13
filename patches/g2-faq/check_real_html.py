"""Independent-QA helper for PR #276: run Work's DELIVERED FAQ extraction and the PATCHED one on a SAVED copy of the official FAQ page and compare them.

    python patches/g2-faq/check_real_html.py --html <path to the saved body> [--repo <repository root>]

Reads the saved body only (it is never written; its SHA-256, size and modification time are checked before and after). Works in a temporary directory: it copies the delivered pipeline
(research/inbox/work-faq-v3/pipeline), applies patches/g2-faq/work-faq-g2.patch to a second copy with ``git apply`` and runs ``extract_conditions`` -> ``structured_record`` ->
``audit_condition_source`` on both. No network, no database, no model. Exit code 0 only if every check holds. The saved body is NOT part of the repository (source bodies are not stored in it);
the expected SHA-256 is the one of the saved FAQ the delivered candidate was made from.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SHA = "dad557c53e2e66f6f05807d90abb6cfc708a55b6200dec579d1bf2389cf9a770"
Q0 = "ＡＣ入試の選考で重視されるのはどのようなことですか？"
Q1 = "生成AIを使用した場合は、どこまで下線を引けばよいのでしょうか？"
Q2 = "生成AIで作成した画像（図や表等も含む）はどのようにすればよいでしょうか？"
RUN = r'''
import json, sys
sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from admissions_pipeline.faq_policy import extract_conditions, structured_record, audit_condition_source
cfg = json.loads(open(sys.argv[1] + "/config/faq-structured-v3.json", encoding="utf-8").read())[0]
record = json.loads(sys.argv[2]); cycle = json.loads(sys.argv[3]) if sys.argv[3] != "null" else None
if cycle is not None:  # the delivered extractor needs the cycle that the delivered spec named
    cfg = dict(cfg, case_id=cycle["case_id"], fiscal_year=cycle["fiscal_year"])
cand = extract_conditions(record, cfg, cycle)
rec = structured_record(cand, cfg.get("parent_evidence_id"), cfg["profile_version"])
audit = audit_condition_source(rec, record["local_path"])
span = lambda p: [p["page"], p["normalized_start"], p["normalized_end"], p["quote"]]
print(json.dumps({"sections": [p["section"] for p in cand["proofs"]], "base_sections": [p["section"] for p in cand["base_record"]["proofs"]],
  "spans": [span(p) for p in cand["proofs"]], "base_spans": [span(p) for p in cand["base_record"]["proofs"]], "values": cand["values"],
  "base": {k: cand["base_record"].get(k) for k in ("case_id", "faculty", "department", "fiscal_year", "published_date", "scope", "scope_status", "source_sha256")},
  "applies_to": [b["applies_to"] for b in cand["field_proofs"].values()], "audit_status": audit["status"]}, ensure_ascii=False))
'''


def fingerprint(path: Path):
    data = path.read_bytes()
    st = path.stat()
    return hashlib.sha256(data).hexdigest(), st.st_size, st.st_mtime_ns


def run_tree(tree: Path, runner: Path, record: dict, cycle):
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(runner), str(tree), json.dumps(record, ensure_ascii=False), json.dumps(cycle, ensure_ascii=False) if cycle else "null"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return {"error": r.stderr[-800:]}
    return json.loads(r.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, type=Path)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = ap.parse_args()
    before = fingerprint(args.html)
    checks = {"source_sha256_matches": before[0] == SHA}
    if not checks["source_sha256_matches"]:
        print(json.dumps({"checks": checks, "note": "the saved body is not the one the delivered candidate was made from: stop"}, indent=1))
        return 2
    delivered_src = args.repo / "research" / "inbox" / "work-faq-v3" / "pipeline"
    patch = args.repo / "patches" / "g2-faq" / "work-faq-g2.patch"
    with tempfile.TemporaryDirectory(prefix="g2check-") as tmp:
        tmp = Path(tmp)
        body = tmp / "faq.html"
        shutil.copyfile(args.html, body)
        a, b = tmp / "delivered", tmp / "patched"
        for d in (a, b):
            shutil.copytree(delivered_src, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        done = subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(patch)], cwd=b, capture_output=True, text=True, encoding="utf-8")
        checks["patch_applies_cleanly"] = done.returncode == 0
        if not checks["patch_applies_cleanly"]:
            print(json.dumps({"checks": checks, "git_apply_stderr": done.stderr[-600:]}, indent=1))
            return 2
        runner = tmp / "run.py"
        runner.write_text(RUN, encoding="utf-8")
        record = {"kind": "html", "url": "https://ac.tsukuba.ac.jp/consultation/faq/", "local_path": str(body), "sha256": SHA, "retrieved_at": "2026-11-01T09:53:47.926390+00:00"}
        cycle = {"case_id": "tsukuba-klis-ac-2027", "university": "筑波大学", "faculty": "情報学群", "department": "知識情報・図書館学類", "admission_method": "アドミッションセンター入試",
                 "fiscal_year": 2027, "exam_year": 2026}
        old, new = run_tree(a, runner, record, cycle), run_tree(b, runner, record, None)
        if "error" in old or "error" in new:
            print(json.dumps({"checks": checks, "delivered_error": old.get("error"), "patched_error": new.get("error")}, indent=1))
            return 2
        saved = json.loads((args.repo / "research" / "inbox" / "work-faq-v3" / "candidates" / "faq-candidate.json").read_text(encoding="utf-8"))
        checks.update({
            "delivered_run_reproduces_the_saved_candidate": [(p["normalized_start"], p["normalized_end"], p["quote"]) for p in saved["proofs"]] == [(s[1], s[2], s[3]) for s in old["spans"]]
            and [(p["normalized_start"], p["normalized_end"]) for p in saved["base_record"]["proofs"]] == [(s[1], s[2]) for s in old["base_spans"]],
            "delivered_sections_are_all_the_group_heading": old["sections"] == [Q0] * 6 and old["base_sections"] == [Q0] * 2,
            "patched_sections_are_the_immediate_questions": new["sections"] == [Q1] * 5 + [Q2] and new["base_sections"] == [Q1, Q2],
            "offsets_and_quotes_identical": old["spans"] == new["spans"] and old["base_spans"] == new["base_spans"],
            "values_identical": old["values"] == new["values"],
            "patched_audit_passes": new["audit_status"] == "pass",
            "str076_scope_is_unknown": all(new["base"][k] is None for k in ("case_id", "faculty", "department", "fiscal_year", "published_date"))
            and new["base"]["scope"] == "general_admission_faq" and new["base"]["scope_status"] == "unknown" and all(x is None for x in new["applies_to"]),
            "source_sha256_in_record": new["base"]["source_sha256"] == SHA,
        })
    checks["saved_body_unchanged"] = before == fingerprint(args.html)
    print(json.dumps({"checks": checks, "all_pass": all(checks.values())}, ensure_ascii=False, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
