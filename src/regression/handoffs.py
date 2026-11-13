"""Find what Work has delivered: every claude-compatible-export.json under
research/inbox/. A new university arrives as a new export (or a new handoff
directory); nothing here needs editing for it — discovery is by file name."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
INBOX = REPO_ROOT / "research" / "inbox"
EXPORT_NAME = "claude-compatible-export.json"


@dataclasses.dataclass(frozen=True)
class ExportRef:
    handoff: str  # directory name under research/inbox
    rel: str  # path of the export within the handoff, posix
    path: Path

    @property
    def key(self) -> str:
        return f"{self.handoff}/{self.rel}"

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


def find_exports(inbox: Path = INBOX) -> list[ExportRef]:
    refs = []
    for path in sorted(Path(inbox).rglob(EXPORT_NAME)):
        rel = path.relative_to(inbox)
        refs.append(ExportRef(rel.parts[0], Path(*rel.parts[1:]).as_posix(), path))
    return refs


def find_handoffs(inbox: Path = INBOX) -> list[Path]:
    """Handoff directories: those with a manifest.json or holding an export."""
    inbox = Path(inbox)
    found = {p.parent for p in inbox.glob("*/manifest.json")}
    found |= {inbox / ref.handoff for ref in find_exports(inbox)}
    return sorted(found)
