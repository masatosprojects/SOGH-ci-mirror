from pathlib import Path

from src.integration.validate_export import _load_records, main, validate_records

VALID = {
    "evidence_id": "EV-1",
    "university": "〇〇大学",
    "faculty": "理学部",
    "admission_method": "総合型選抜",
    "fiscal_year": 2026,
    "source_url": "https://example.ac.jp/x.pdf",
    "retrieved_at": "2026-10-01",
}


def test_validate_records_all_valid():
    report = validate_records({"EV-1": VALID})
    assert report["ok_count"] == 1
    assert report["invalid_count"] == 0


def test_validate_records_flags_invalid():
    bad = {**VALID}
    del bad["fiscal_year"]
    report = validate_records({"EV-1": VALID, "EV-2": bad})
    assert report["ok_count"] == 1
    assert report["invalid_count"] == 1
    assert report["records"]["EV-2"]["errors"]


def test_load_records_from_plain_object(tmp_path: Path):
    p = tmp_path / "export.json"
    p.write_text('{"EV-1": %s}' % _as_json(VALID), encoding="utf-8")
    records = _load_records(p)
    assert "EV-1" in records


def test_load_records_from_evidence_wrapper(tmp_path: Path):
    p = tmp_path / "export.json"
    p.write_text('{"evidence": {"EV-1": %s}}' % _as_json(VALID), encoding="utf-8")
    records = _load_records(p)
    assert "EV-1" in records


def test_load_records_from_list(tmp_path: Path):
    p = tmp_path / "export.json"
    p.write_text("[%s]" % _as_json(VALID), encoding="utf-8")
    records = _load_records(p)
    assert "EV-1" in records


def test_main_returns_nonzero_on_invalid_export(tmp_path: Path):
    bad = {**VALID}
    del bad["source_url"]
    p = tmp_path / "export.json"
    p.write_text('{"EV-1": %s}' % _as_json(bad), encoding="utf-8")
    assert main([str(p)]) == 1


def test_main_returns_zero_on_valid_export(tmp_path: Path):
    p = tmp_path / "export.json"
    p.write_text('{"EV-1": %s}' % _as_json(VALID), encoding="utf-8")
    assert main([str(p)]) == 0


def _as_json(record: dict) -> str:
    import json

    return json.dumps(record, ensure_ascii=False)
