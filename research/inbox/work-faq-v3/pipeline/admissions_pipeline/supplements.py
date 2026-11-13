"""Additional notices remain separate from the original guide and its facts."""
import hashlib
import json
import re
from pathlib import Path
from .collector import Page
from .extract import normalized_with_positions, normalize
from .profiles import substitute
from .store import canonical


def source_pages(record):
    raw = Path(record["local_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("supplement source hash mismatch")
    if record["kind"] == "pdf":
        import pymupdf
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            return [p.get_text() for p in doc]
    return ["\n".join(Page(raw.decode("utf-8", errors="strict"), record["url"]).text)]


def extract_notice(spec, record, cycle):
    if record["url"] != spec["url"] or record["sha256"] != spec["expected_sha256"]:
        raise ValueError("unreviewed notice edition")
    if cycle["case_id"] != spec["case_id"] or cycle["fiscal_year"] != spec["fiscal_year"]:
        raise ValueError("notice applicability mismatch")
    pages = source_pages(record)
    groups, proofs = {}, []
    for anchor in spec["anchors"]:
        page = anchor["page"]
        text, positions = normalized_with_positions(pages[page - 1])
        scope_start, scope_end = 0, len(text)
        if spec.get("section_start"):
            markers = list(re.finditer(re.escape(normalize(spec["section_start"])), text))
            if len(markers) != 1:
                raise ValueError("notice section ambiguous")
            scope_start = markers[0].start()
            scope_end = text.find(normalize(spec["section_end"]), scope_start)
            if scope_end < 0:
                raise ValueError("notice section boundary missing")
        hits = list(re.finditer(anchor["pattern"], text[scope_start:scope_end], re.DOTALL))
        if len(hits) != 1:
            raise ValueError(f"notice {spec['logical_id']}: expected one anchor, got {len(hits)}")
        hit = hits[0]
        start, end = scope_start + hit.start(), scope_start + hit.end()
        if start == end:
            raise ValueError("empty notice quote")
        for key, value in hit.groupdict().items():
            if value is None or (key in groups and groups[key] != value):
                raise ValueError("conflicting notice captures")
            groups[key] = value
        proofs.append({"page": page, "quote": pages[page-1][positions[start]:positions[end-1]+1],
                       "normalized_start": start, "normalized_end": end,
                       "section": spec.get("section_start"), "source_kind": record["kind"]})
        for group in anchor.get("include_capture_proofs", []):
            a,b=hit.span(group); a+=scope_start; b+=scope_start
            if a < scope_start or a == b: raise ValueError("missing captured table cell")
            proofs.append({"page":page,"quote":pages[page-1][positions[a]:positions[b-1]+1],
                           "normalized_start":a,"normalized_end":b,"capture_group":group,"context_pattern":anchor["pattern"]})
    if not proofs:
        raise ValueError("notice without evidence")
    value = substitute(spec["value"], groups)
    identity = [spec["logical_id"], record["sha256"], value, spec["profile_version"]]
    eid = "EV-U-" + hashlib.sha256(canonical(identity).encode()).hexdigest()[:12]
    return {"evidence_id": eid, "logical_id": spec["logical_id"], "case_id": cycle["case_id"],
            **{k: cycle[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")},
            "fact_key": spec["fact_key"], "value": value, "scope": "target_admission_cycle",
            "source_url": record["url"], "source_sha256": record["sha256"],
            "source_pdf_sha256": record["sha256"] if record["kind"] == "pdf" else None,
            "source_kind": record["kind"], "retrieved_at": record["retrieved_at"][:10],
            **({"source_role":spec["source_role"]} if "source_role" in spec else {}),
            **({"related_sources":spec["related_sources"]} if "related_sources" in spec else {}),
            "published_date": spec.get("published_date"), "applicability": spec["applicability"],
            "proofs": proofs, "sentences": substitute(spec["sentences"], groups),
            "temporal_status": spec["temporal_status"], "parent_evidence_id": spec.get("parent_evidence_id"),
            "publication_allowed": False, "profile_version": spec["profile_version"]}


def contract_state(record, registry):
    """User requires ACTIVE: proposed notices must never be promoted on QA alone."""
    definition = registry.get("fact_keys", {}).get(record["fact_key"])
    if not definition or definition.get("status") != "active":
        return "pending_contract"
    required=set(record.get('required_contract_fields',[]))
    if record.get('fact_key')=='generative_ai_policy':
        from .faq_policy import FIELDS
        required |= set(record.get('value',{})) & set(FIELDS)
    for name in required:
        field=definition.get('value',{}).get(name)
        if not field or field.get('type')!='boolean':return 'pending_contract'
    return "candidate"
