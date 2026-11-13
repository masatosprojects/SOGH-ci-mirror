"""Declarative, hash-pinned PDF profiles. No executable code in configuration."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .extract import Extracted, ExtractionError, normalized_with_positions, normalize

KNOWN_KEYS = {"quota", "postal_period", "online_period", "common_test", "interview_scope", "interview", "statement_length",
              "eligibility", "second_stage_date", "first_stage", "policy", "entry"}


def load_profile(path):
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    for field in ("case_id", "code", "university", "faculty", "department", "admission_method",
                  "fiscal_year", "exam_year", "sha256", "url", "rules", "cover_anchor", "dimensions"):
        if field not in p:
            raise ExtractionError("profile missing " + field)
    if not re.fullmatch(r"[0-9a-f]{64}", p["sha256"]):
        raise ExtractionError("profile requires a reviewed edition hash")
    if not p["rules"] or len({r["key"] for r in p["rules"]}) != len(p["rules"]):
        raise ExtractionError("empty or duplicate fact rules")
    if any(r["key"] not in KNOWN_KEYS for r in p["rules"]):
        raise ExtractionError("new fact_key needs Claude contract agreement")
    return p


def substitute(value, groups):
    if isinstance(value, dict):
        return {k: substitute(v, groups) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, groups) for v in value]
    if isinstance(value, str):
        if value.startswith("$datetime:"):
            y, m, d, h, minute = value[10:].split(",")
            return datetime(int(groups[y])+2018,int(groups[m]),int(groups[d]),int(groups[h]),int(groups[minute]),tzinfo=timezone(timedelta(hours=9))).isoformat()
        if value.startswith("$date:"):
            y, m, d = value[6:].split(",")
            return date(int(groups[y]) + 2018, int(groups[m]), int(groups[d])).isoformat()
        if value.startswith("$int:"):
            return int(groups[value[5:]].replace(",", ""))
        if value.startswith("$year:"):
            return int(groups[value[6:]]) + 2018
        return value.format_map(groups)
    return value


def extract_profile(profile, pdf_path):
    import pymupdf
    p = profile
    path = Path(pdf_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != p["sha256"]:
        raise ExtractionError("edition changed: reviewed profile required")
    with pymupdf.open(path) as doc:
        if doc.is_encrypted:
            raise ExtractionError("encrypted PDF requires manual review")
        pages = [page.get_text() for page in doc]
    if not pages or normalize(p["cover_anchor"]) not in normalize(pages[0]):
        raise ExtractionError("cover year/type anchor missing")
    facts = []
    for n, rule in enumerate(p["rules"], 1):
        proofs, groups = [], {}
        for anchor in rule["anchors"]:
            page = anchor["page"]
            if not isinstance(page, int) or not 1 <= page <= len(pages):
                raise ExtractionError("page out of range")
            text, positions = normalized_with_positions(pages[page - 1])
            hits = list(re.finditer(anchor["pattern"], text, re.DOTALL))
            if len(hits) != 1:
                raise ExtractionError(f"{rule['key']} p.{page}: expected unique anchor, got {len(hits)}")
            hit = hits[0]
            if hit.end() == hit.start():
                raise ExtractionError("empty proof")
            for k, v in hit.groupdict().items():
                if v is None or (k in groups and groups[k] != v):
                    raise ExtractionError("missing/conflicting capture")
                groups[k] = v
            proofs.append({"page": page, "quote": pages[page-1][positions[hit.start()]:positions[hit.end()-1]+1],
                           "quote_normalized": hit.group(), "normalized_start": hit.start(),
                           "normalized_end": hit.end(), "pattern": anchor["pattern"]})
            for group in anchor.get("include_capture_proofs", []):
                start, end = hit.span(group)
                if start < 0 or start == end: raise ExtractionError("missing captured table cell")
                proofs.append({"page":page,"quote":pages[page-1][positions[start]:positions[end-1]+1],
                               "normalized_start":start,"normalized_end":end,"capture_group":group,
                               "context_pattern":anchor["pattern"]})
        if not proofs:
            raise ExtractionError("facts require proofs")
        value = substitute(rule["value"], groups)
        sentence = rule["sentence"].format_map(dict(groups, **value))
        facts.append({"evidence_id": f"EV-{p['code']}-{n:02d}-{p['sha256'][:6]}",
                      "case_id": p["case_id"], "key": rule["key"], "value": value,
                      "scope": rule["scope"], "notes": rule.get("notes", []), "related_keys": [],
                      "proofs": proofs, "fiscal_year": p["fiscal_year"], "source_pdf_sha256": p["sha256"],
                      "source_url": p["url"], "verification": "source_checked_for_saved_version",
                      "revision_clearance": "not_cleared_for_publication", "profile_version": p["profile_version"],
                      "draft_sentence": sentence})
    return Extracted(p["case_id"], p, path, pages, facts)
