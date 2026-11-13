"""Read a committed tree without changing Claude's checkout or branch."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path


def main():
    p = argparse.ArgumentParser(); p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--commit", required=True); p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit): raise ValueError("full immutable commit required")
    args.output.mkdir(parents=True, exist_ok=False)
    archive = args.output / "source.zip"
    subprocess.run(["git", "-C", str(args.repo.resolve()), "archive", "--format=zip", "--output=" + str(archive.resolve()), args.commit], check=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if not (args.output / item.filename).resolve().is_relative_to(args.output.resolve()): raise ValueError("archive traversal")
        z.extractall(args.output)
    metadata = {"commit": args.commit, "files": {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in args.output.rglob("*") if p.is_file() and p.name not in ("source.zip", "QA_PROVENANCE.json")}}
    (args.output / "QA_PROVENANCE.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"commit": args.commit, "files": len(metadata["files"])}))


if __name__ == "__main__": main()
