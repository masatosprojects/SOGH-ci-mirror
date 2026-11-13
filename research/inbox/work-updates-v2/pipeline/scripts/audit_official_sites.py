"""Read configured public sources once, recording failures and review candidates."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admissions_pipeline.collector import Collector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config/official_audit.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/official-audit")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    collector = Collector(args.output / "bodies", config["allowed_hosts"])
    records = []
    for target in config["targets"]:
        try:
            record = dict(target, **collector.fetch(target["url"]))
            if "expected_sha256" in target:
                record["matches_saved_edition"] = record["sha256"] == target["expected_sha256"]
            if record["kind"] == "html":
                inspected = collector.inspect_html(record, config["terms"])
                record["candidate_links"] = inspected["candidate_links"]
            record["snapshot_path"] = str(collector.write_snapshot(record, target.get("source_id", target["case"] + "-" + target["role"]), args.output / "snapshots", target.get("supersedes", [])))
            record["status"] = "fetched_requires_scope_review"
        except Exception as exc:
            record = dict(target, status="not_confirmed", error=type(exc).__name__)
        records.append(record)
        print(target["case"], target["role"], record["status"], flush=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "records": records,
              "exhaustive": False, "publication_allowed": False,
              "limits": ["Candidate links are not verified facts", "News pagination/search/manual scope review required",
                         "No semantic diff: delegated to Claude #15/#16", "No proof that notices do not exist"]}
    args.output.mkdir(parents=True, exist_ok=True)
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = args.output / ("audit-" + run + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = {}
    for history in sorted(args.output.glob("audit-*.json")):
        for record in json.loads(history.read_text(encoding="utf-8"))["records"]:
            if record.get("status", "").startswith("fetched"):
                snapshot = Path(record.get("snapshot_path", args.output / "snapshots" /
                    (record.get("source_id", record["case"] + "-" + record["role"]) + "-" + record["sha256"] + ".snapshot.json")))
                if snapshot.is_file():
                    latest[record["url"]] = str(snapshot.resolve())
    (args.output / "snapshot-paths.json").write_text(json.dumps(list(latest.values()), indent=2), encoding="utf-8")
    print(path, flush=True)


if __name__ == "__main__":
    main()
