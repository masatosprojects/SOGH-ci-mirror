"""The `prepare` hook of the g4 harness (SOGH_G4_PREPARE=src.integration.g4_prepare:prepare): applies the frozen migration chain (0002 .. latest, including the guards of 0004) to a DISPOSABLE
clone, so that Work's update path is exercised on a database that carries the final protections. Never run it on an original or on the audited copy itself. SELF_VALIDATED."""
from pathlib import Path


def prepare(path) -> None:
    from src.db_contract import additive_schema as ad
    result = ad.apply(Path(path), confirm_disposable_copy=True)
    if result["rolled_back"]:
        raise RuntimeError(f"migrations did not apply: {result}")
