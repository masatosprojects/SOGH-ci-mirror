import time
#!/usr/bin/env python3
"""
SOGH Antigravity - Event-Driven Asynchronous Information Processor (Phase 1.8 / Phase 2 Remediation)

Robust, fail-close implementation addressing all audit findings:
1. Grounding verification is MANDATORY: reference_db must be present, valid, and non-empty.
2. Existing file protection: unreadable/corrupted existing candidate files are NEVER overwritten.
3. Complete event identity fingerprinting (payload_fingerprint and origin_url).
4. Distinct classification of identity/source cases (A, B, C, D, E) without business policy IDs.
5. Department-scoped semantic grounding: quotas match only against matching department/college.
6. TOCTOU & Concurrency safe atomic writing with O_CREAT|O_EXCL semantics and conflict quarantine.
7. Explicit synthetic origin labeling (evidence_class: synthetic_mock).
8. Full source edition tracking and edition update preservation.
"""

import os
import sys
import json
import re
import math
import uuid
import hashlib
import difflib
import errno
from datetime import datetime
from urllib.parse import urlparse

class EventValidationError(Exception):
    """Raised when an event fails schema, type, or integrity validation."""
    pass

RECOGNIZED_UNIVERSITIES = {"筑波大学", "University of Tsukuba"}
RECOGNIZED_ADMISSION_TYPES = {"AC入試", "アドミッション・センター入試", "推薦入試", "一般選抜"}
RECOGNIZED_CHANGE_TYPES = {
    "guideline_text_revision",
    "schedule_amendment",
    "quota_adjustment",
    "submission_method_update"
}
ALLOWED_URL_DOMAINS = {"admission.example.com", "admission.example.test", "admission.example.org"}

EVENT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
MD5_HEX_REGEX = re.compile(r"^[a-f0-9]{32}$")

MAX_PAYLOAD_BYTES = 1_000_000  # 1 MB max payload
MAX_TEXT_LEN = 100_000         # 100k chars max per diff text
MAX_NESTING_DEPTH = 5          # Recursion depth limit

def compute_checksum(text: str) -> str:
    """Deterministic MD5 checksum for synthetic payload verification."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def compute_payload_fingerprint(event: dict) -> str:
    """
    Deterministic hash across semantic content (excluding source_url, event_id, and timestamps)
    to enable distinguishing Same-Content-Different-Origin (Case B) from Different-Content (Case C).
    """
    diff = event.get("simulated_diff", {})
    key_fields = {
        "university": event.get("university"),
        "target_academic_year": event.get("target_academic_year"),
        "target_admission_type": event.get("target_admission_type"),
        "change_type": event.get("change_type"),
        "section": diff.get("section"),
        "before_text": diff.get("before_text"),
        "after_text": diff.get("after_text")
    }
    dumped = json.dumps(key_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

def compute_full_fingerprint(event: dict) -> str:
    """Full hash including source_url, target, and diff."""
    payload_fp = compute_payload_fingerprint(event)
    combined = f"{payload_fp}:{event.get('source_url')}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()

def check_nesting_depth(obj, current_depth=1) -> bool:
    """Ensure JSON structure does not exceed maximum nesting depth."""
    if current_depth > MAX_NESTING_DEPTH:
        return False
    if isinstance(obj, dict):
        return all(check_nesting_depth(v, current_depth + 1) for v in obj.values())
    elif isinstance(obj, list):
        return all(check_nesting_depth(v, current_depth + 1) for v in obj)
    return True

def validate_event_payload(event: dict) -> tuple[bool, str]:
    """
    Validates event payload against strict types, ranges, lengths, path safety,
    nesting depth, and scope rules. Never raises unhandled exceptions.
    """
    if not isinstance(event, dict):
        return False, "Payload must be a dictionary"

    # Nesting depth check
    if not check_nesting_depth(event):
        return False, f"Payload exceeds maximum allowed nesting depth ({MAX_NESTING_DEPTH})"

    # Allowed top-level keys
    allowed_keys = {
        "event_id", "source_url", "university",
        "target_academic_year", "target_admission_type",
        "detected_at", "change_type", "checksum_before",
        "checksum_after", "simulated_diff", "pipeline_routing",
        "source_edition", "target_department"
    }
    unknown_keys = set(event.keys()) - allowed_keys
    if unknown_keys:
        return False, f"Unknown top-level fields rejected: {sorted(list(unknown_keys))}"

    if "target_department" in event and event["target_department"] is not None:
        if not isinstance(event["target_department"], str) or len(event["target_department"]) > 100:
            return False, "target_department must be a string <= 100 chars"

    # Required fields
    required_keys = [
        "event_id", "source_url", "university",
        "target_academic_year", "target_admission_type",
        "change_type", "simulated_diff"
    ]
    for k in required_keys:
        if k not in event or event[k] is None:
            return False, f"Missing required field: {k}"

    # 1. event_id validation (Strict Path Traversal & Length Protection)
    event_id = event["event_id"]
    if not isinstance(event_id, str):
        return False, "event_id must be a string"
    if len(event_id) == 0 or len(event_id) > 64:
        return False, "event_id length must be between 1 and 64 characters"
    if not EVENT_ID_REGEX.match(event_id) or ".." in event_id or "/" in event_id or "\\" in event_id:
        return False, f"Invalid event_id format (path traversal or invalid characters detected): {event_id}"

    # 2. university & admission_type validation
    univ = event["university"]
    if not isinstance(univ, str):
        return False, "university must be a string"
    if len(univ) > 100:
        return False, "university exceeds maximum allowed length (100)"
    if univ not in RECOGNIZED_UNIVERSITIES:
        return False, f"Out-of-scope university: {univ}"

    adm_type = event["target_admission_type"]
    if not isinstance(adm_type, str):
        return False, "target_admission_type must be a string"
    if len(adm_type) > 100:
        return False, "target_admission_type exceeds maximum allowed length (100)"
    if adm_type not in RECOGNIZED_ADMISSION_TYPES:
        return False, f"Out-of-scope admission type: {adm_type}"

    # 3. target_academic_year validation (Strict Integer & Range)
    year = event["target_academic_year"]
    if type(year) is not int or isinstance(year, bool):
        return False, f"target_academic_year must be an integer, got {type(year).__name__}"
    if year < 2025 or year > 2035:
        return False, f"target_academic_year {year} out of reasonable range (2025-2035)"

    # 4. change_type validation
    c_type = event["change_type"]
    if not isinstance(c_type, str) or c_type not in RECOGNIZED_CHANGE_TYPES:
        return False, f"Unknown change_type: {c_type}"

    # 5. source_url validation (Restricted Test Domains)
    url = event["source_url"]
    if not isinstance(url, str):
        return False, "source_url must be a string"
    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme: {parsed_url.scheme}"
        if parsed_url.hostname not in ALLOWED_URL_DOMAINS:
            return False, f"Unapproved source_url domain: {parsed_url.hostname}"
    except Exception as e:
        return False, f"Malformed source_url: {str(e)}"

    # 6. simulated_diff validation
    diff = event["simulated_diff"]
    if not isinstance(diff, dict):
        return False, "simulated_diff must be a dictionary"
    diff_allowed_keys = {"section", "before_text", "after_text"}
    if set(diff.keys()) - diff_allowed_keys:
        return False, f"simulated_diff contains unexpected fields: {set(diff.keys()) - diff_allowed_keys}"
    if "before_text" not in diff or "after_text" not in diff:
        return False, "simulated_diff missing before_text or after_text"

    before_text = diff["before_text"]
    after_text = diff["after_text"]
    if not isinstance(before_text, str) or not isinstance(after_text, str):
        return False, "before_text and after_text must be strings"
    if len(before_text) > MAX_TEXT_LEN or len(after_text) > MAX_TEXT_LEN:
        return False, f"Text length exceeds maximum allowed limit ({MAX_TEXT_LEN} chars)"

    # 7. Checksum validation (Hex format & Integrity)
    if "checksum_before" in event and event["checksum_before"]:
        cs_before = str(event["checksum_before"]).lower()
        if not MD5_HEX_REGEX.match(cs_before):
            return False, f"Invalid checksum_before format (must be 32-hex): {cs_before}"
        actual_before = compute_checksum(before_text)
        if cs_before != actual_before:
            return False, f"Checksum mismatch for before_text (expected {cs_before}, got {actual_before})"

    if "checksum_after" in event and event["checksum_after"]:
        cs_after = str(event["checksum_after"]).lower()
        if not MD5_HEX_REGEX.match(cs_after):
            return False, f"Invalid checksum_after format (must be 32-hex): {cs_after}"
        actual_after = compute_checksum(after_text)
        if cs_after != actual_after:
            return False, f"Checksum mismatch for after_text (expected {cs_after}, got {actual_after})"

    return True, "VALID"

def atomic_write_json(file_path: str, data: dict, allow_overwrite: bool = False):
    """
    Writes JSON data atomically.
    When allow_overwrite is False, writes completely to a private temporary file first,
    then exclusively links via os.link to guarantee zero-window TOCTOU protection
    and ensure interrupted writes never leave partial files (A6).
    """
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    temp_path = f"{file_path}.tmp.{uuid.uuid4().hex}"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        if not allow_overwrite:
            try:
                os.link(temp_path, file_path)
            except FileExistsError:
                raise
            except OSError as e:
                is_exists = (
                    isinstance(e, FileExistsError) or
                    getattr(e, "winerror", None) == 183 or
                    getattr(e, "errno", None) == errno.EEXIST
                )
                if is_exists:
                    raise FileExistsError(f"Destination {file_path} already exists (exclusive link failed: {e})")
                raise
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        else:
            os.replace(temp_path, file_path)
    except BaseException:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise

def verify_grounding_against_db(candidate: dict, reference_db: dict, full_after_text: str = "") -> tuple[bool, list[str]]:
    """
    Semantic grounding check against verified official DB with department-scoping:
    - University existence and domain
    - Academic year existence
    - Admission type existence
    - Department-scoped matching: quotas are checked strictly against the matching department
    - Prohibited substitution checks
    - Fail-close when reference DB has multiple colleges and event is ambiguous
    """
    failures = []
    if not reference_db or not isinstance(reference_db, dict) or "universities" not in reference_db:
        return False, ["Invalid or empty reference database supplied"]

    target = candidate.get("target", {})
    univ_name = target.get("university")
    year = target.get("academic_year")
    adm_type = target.get("admission_type")
    target_dept = target.get("department")

    # Match University
    univ_record = next((u for u in reference_db.get("universities", []) if u.get("name") == univ_name), None)
    if not univ_record:
        failures.append(f"University '{univ_name}' not found in official verified DB")
        return False, failures

    # Match Authorized Domain
    source_url = candidate.get("source_url", "")
    parsed_host = urlparse(source_url).hostname
    if parsed_host != univ_record.get("authorized_domain"):
        failures.append(f"Source URL domain '{parsed_host}' does not match official authorized domain '{univ_record.get('authorized_domain')}'")

    # Match Academic Year
    if year not in univ_record.get("academic_years", []):
        failures.append(f"Academic year '{year}' not registered in official DB for {univ_name}")

    # Match Admission Type
    adm_record = next((a for a in univ_record.get("admission_types", []) if a.get("type_name") == adm_type), None)
    if not adm_record:
        failures.append(f"Admission type '{adm_type}' not found in official DB for {univ_name}")
        return False, failures

    # Prepare combined new text
    combined_texts_to_check = [full_after_text] if full_after_text else []
    for delta in candidate.get("dynamic_changes", []):
        if delta.get("new"):
            combined_texts_to_check.append(delta.get("new"))

    # Collect all colleges across clusters for this admission type
    all_colleges = []
    for cluster in adm_record.get("clusters", []):
        for college in cluster.get("colleges", []):
            all_colleges.append(college)

    # Scoped college selection
    matched_colleges = []
    if target_dept:
        matched_colleges = [c for c in all_colleges if c.get("college_name") == target_dept]
        if not matched_colleges:
            failures.append(f"Department '{target_dept}' specified in event not found in official DB for {univ_name}")
            return False, failures
    else:
        # Infer department from text matching college_name
        for c in all_colleges:
            c_name = c.get("college_name", "")
            if c_name and any(c_name in txt for txt in combined_texts_to_check):
                matched_colleges.append(c)

        if not matched_colleges:
            if len(all_colleges) == 1:
                matched_colleges = all_colleges
            elif len(all_colleges) > 1:
                col_names = [c.get("college_name") for c in all_colleges]
                failures.append(f"Ambiguous department: reference DB contains multiple colleges ({col_names}), but event omits target_department and text does not identify it")
                return False, failures

    # Semantic Checks strictly against matched_colleges
    for college in matched_colleges:
        official_quota = college.get("official_quota")
        st1 = college.get("stages", {}).get("stage_1", {})
        prohibited = st1.get("prohibited_substitutions", [])
        prov = college.get("provenance", {})

        if prov.get("verification_status") != "VERIFIED_OFFICIAL":
            failures.append(f"College '{college.get('college_name')}' lacks VERIFIED_OFFICIAL provenance in reference DB")

        for text_chunk in combined_texts_to_check:
            # 0. Strict Output Contract & Anti-Corruption Check (Prompt Leak, ANSI, Null byte)
            from grounding_response_parser import enforce_strict_output_contract
            contract_check = enforce_strict_output_contract(text_chunk)
            if not contract_check["success"] and contract_check["verdict"] == "UNKNOWN_FORMAT_FAIL_CLOSE":
                reason = contract_check["reason"]
                if "CRITICAL:" in reason or "SECURITY_VIOLATION:" in reason or "corruption" in reason:
                    failures.append(f"Security output contract violation in event text: {reason}")

            # 1. Prohibited substitutions check
            for p in prohibited:
                if p in text_chunk:
                    failures.append(f"Grounding violation: prohibited substitution '{p}' found in proposed change text")

            # 2. Numerical Quota contradiction check
            quota_match = re.search(r"(?:定員|募集人数)[^\d]*(\d+)名?", text_chunk)
            if quota_match and official_quota is not None:
                proposed_quota = int(quota_match.group(1))
                if proposed_quota != official_quota:
                    failures.append(f"Grounding violation: proposed quota '{proposed_quota}' contradicts official verified quota '{official_quota}' for {college.get('college_name')}")

    return (len(failures) == 0), failures

def process_diff_event(event_input, base_queue_dir: str, reference_db: dict = None) -> dict:
    """
    Main entry point for event-driven information processing with mandatory grounding,
    safe quarantine, collision-free audit trails, and existing file protection.
    """
    staging_dir = os.path.join(base_queue_dir, "staging_queue") if base_queue_dir else None
    quarantine_dir = os.path.join(base_queue_dir, "quarantine") if base_queue_dir else None
    conflict_dir = os.path.join(base_queue_dir, "conflicts") if base_queue_dir else None

    # Helper for collision-free file naming
    def make_unique_id(prefix: str, identifier: str) -> str:
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(identifier))[:40]
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        short_uuid = uuid.uuid4().hex[:6]
        return f"{prefix}-{safe_id}-{timestamp}-{short_uuid}"

    # Step 0: Input Size & Reading Check
    try:
        if isinstance(event_input, str):
            if not os.path.exists(event_input):
                return {
                    "status": "ERROR_FILE_NOT_FOUND",
                    "candidate": None,
                    "error": f"File not found: {event_input}"
                }
            file_size = os.path.getsize(event_input)
            if file_size > MAX_PAYLOAD_BYTES:
                return {
                    "status": "PAYLOAD_SIZE_EXCEEDED",
                    "candidate": None,
                    "error": f"Payload file size ({file_size} bytes) exceeds limit ({MAX_PAYLOAD_BYTES} bytes)"
                }
            with open(event_input, "r", encoding="utf-8") as f:
                event = json.load(f)
        elif isinstance(event_input, dict):
            dumped_len = len(json.dumps(event_input))
            if dumped_len > MAX_PAYLOAD_BYTES:
                return {
                    "status": "PAYLOAD_SIZE_EXCEEDED",
                    "candidate": None,
                    "error": f"Serialized payload size ({dumped_len} bytes) exceeds limit ({MAX_PAYLOAD_BYTES} bytes)"
                }
            event = event_input
        else:
            return {
                "status": "ERROR_INVALID_INPUT_TYPE",
                "candidate": None,
                "error": "Input must be a file path or dictionary"
            }
    except Exception as e:
        return {
            "status": "ERROR_INVALID_JSON",
            "candidate": None,
            "error": f"JSON parsing failed: {str(e)}"
        }

    # Step 1: Payload Validation
    is_valid, reason = validate_event_payload(event)
    if not is_valid:
        quarantine_id = make_unique_id("QUARANTINE", event.get("event_id", "MALFORMED"))
        quarantine_record = {
            "quarantine_id": quarantine_id,
            "quarantined_at": datetime.now().isoformat(),
            "reason": reason,
            "raw_event": event,
            "validation_status": "REJECTED_QUARANTINED"
        }
        if quarantine_dir:
            q_file = os.path.join(quarantine_dir, f"{quarantine_id}.json")
            atomic_write_json(q_file, quarantine_record, allow_overwrite=True)
        return {
            "status": "REJECTED_QUARANTINED",
            "candidate": None,
            "error": reason,
            "quarantine_record": quarantine_record
        }

    # Step 2: MANDATORY Grounding DB Check
    if not reference_db or not isinstance(reference_db, dict) or not reference_db.get("universities"):
        quarantine_id = make_unique_id("NO_REF_DB", event["event_id"])
        quarantine_record = {
            "quarantine_id": quarantine_id,
            "quarantined_at": datetime.now().isoformat(),
            "reason": "MANDATORY_REFERENCE_DB_MISSING_OR_EMPTY: Grounding check cannot be omitted",
            "raw_event": event,
            "validation_status": "REJECTED_MISSING_REFERENCE_DB"
        }
        if quarantine_dir:
            q_file = os.path.join(quarantine_dir, f"{quarantine_id}.json")
            atomic_write_json(q_file, quarantine_record, allow_overwrite=True)
        return {
            "status": "REJECTED_MISSING_REFERENCE_DB",
            "candidate": None,
            "error": "Grounding verification cannot be bypassed: valid non-empty reference_db is mandatory",
            "quarantine_record": quarantine_record
        }

    # Step 3: No-Change Check
    diff_data = event["simulated_diff"]
    before_text = diff_data["before_text"]
    after_text = diff_data["after_text"]

    if before_text == after_text:
        return {
            "status": "NO_CHANGE_DETECTED",
            "candidate": None,
            "message": "before_text and after_text are identical. Zero candidates produced."
        }

    # Step 4: Dynamic Extraction
    matcher = difflib.SequenceMatcher(None, before_text, after_text)
    extracted_changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            extracted_changes.append({"op": "replace", "old": before_text[i1:i2], "new": after_text[j1:j2]})
        elif tag == "delete":
            extracted_changes.append({"op": "delete", "old": before_text[i1:i2]})
        elif tag == "insert":
            extracted_changes.append({"op": "insert", "new": after_text[j1:j2]})

    event_id = event["event_id"]
    payload_fingerprint = compute_payload_fingerprint(event)
    full_fingerprint = compute_full_fingerprint(event)

    candidate_update = {
        "candidate_id": f"CAND-{event_id}",
        "processed_at": datetime.now().isoformat(),
        "source_event": event_id,
        "source_url": event["source_url"],
        "payload_fingerprint": payload_fingerprint,
        "content_fingerprint": full_fingerprint,
        "source_edition": event.get("source_edition"),
        "target": {
            "university": event["university"],
            "academic_year": event["target_academic_year"],
            "admission_type": event["target_admission_type"],
            "section": diff_data.get("section", "UNKNOWN_SECTION"),
            "department": event.get("target_department")
        },
        "dynamic_changes": extracted_changes,
        "diff_summary": f"Section '{diff_data.get('section')}' revised with {len(extracted_changes)} delta operations.",
        "lifecycle_state": "UNVERIFIED_RAW_CANDIDATE",
        "requires_official_confirmation": True,
        "evidence_class": "synthetic_mock",
        "provenance": "synthetic_fixture"
    }

    # Step 5: Semantic Grounding Verification
    is_grounded, ground_failures = verify_grounding_against_db(candidate_update, reference_db, full_after_text=after_text)
    if not is_grounded:
        quarantine_id = make_unique_id("GROUNDING_FAIL", event_id)
        quarantine_record = {
            "quarantine_id": quarantine_id,
            "quarantined_at": datetime.now().isoformat(),
            "failures": ground_failures,
            "candidate": candidate_update,
            "validation_status": "REJECTED_UNGROUNDED"
        }
        if quarantine_dir:
            q_file = os.path.join(quarantine_dir, f"{quarantine_id}.json")
            atomic_write_json(q_file, quarantine_record, allow_overwrite=True)
        return {
            "status": "REJECTED_UNGROUNDED",
            "candidate": None,
            "failures": ground_failures,
            "quarantine_record": quarantine_record
        }

    candidate_update["lifecycle_state"] = "GROUNDING_CHECK_PASSED_UNCONFIRMED_PROPOSAL"
    candidate_update["validation_status"] = "PENDING_INDEPENDENT_QA"

    # Step 6: Identity, Idempotency, and Conflict Detection
    if staging_dir:
        os.makedirs(staging_dir, exist_ok=True)
        out_file = os.path.join(staging_dir, f"{candidate_update['candidate_id']}.json")

        if os.path.exists(out_file):
            try:
                with open(out_file, "r", encoding="utf-8") as existing_f:
                    existing_data = json.load(existing_f)
            except Exception as read_err:
                # Existing file corrupted: preserve it and quarantine incoming event!
                quarantine_id = make_unique_id("EXISTING_UNREADABLE", event_id)
                quarantine_record = {
                    "quarantine_id": quarantine_id,
                    "quarantined_at": datetime.now().isoformat(),
                    "reason": f"Existing candidate file exists but is unreadable ({str(read_err)}). Preserved existing file without overwrite.",
                    "existing_file": out_file,
                    "incoming_candidate": candidate_update,
                    "validation_status": "EXISTING_CANDIDATE_UNREADABLE_QUARANTINED"
                }
                if quarantine_dir:
                    q_file = os.path.join(quarantine_dir, f"{quarantine_id}.json")
                    atomic_write_json(q_file, quarantine_record, allow_overwrite=True)
                return {
                    "status": "EXISTING_CANDIDATE_UNREADABLE_QUARANTINED",
                    "candidate": None,
                    "error": f"Existing candidate file {out_file} is unreadable. Overwrite prevented.",
                    "quarantine_record": quarantine_record
                }

            existing_payload_fp = existing_data.get("payload_fingerprint")
            existing_url = existing_data.get("source_url")
            incoming_url = candidate_update.get("source_url")
            existing_edition = existing_data.get("source_edition")
            incoming_edition = event.get("source_edition")

            if existing_payload_fp == payload_fingerprint:
                if existing_url == incoming_url:
                    # Same ID, same content, same URL: check edition update
                    if incoming_edition != existing_edition and incoming_edition is not None:
                        # Edition update with concurrency protection to prevent edition loss (A7)
                        lock_file = f"{out_file}.lock"
                        acquired = False
                        start_lock_t = time.monotonic()
                        while time.monotonic() - start_lock_t < 10.0:
                            try:
                                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0))
                                os.write(fd, f"pid={os.getpid()},time={time.time()}".encode("utf-8"))
                                os.close(fd)
                                acquired = True
                                break
                            except (FileExistsError, PermissionError):
                                time.sleep(0.01)

                        if not acquired:
                            # Lock timed out: fail-close! DO NOT modify or overwrite candidate (A9).
                            q_id = make_unique_id("LOCK_TIMEOUT", event_id)
                            q_record = {
                                "quarantine_id": q_id,
                                "quarantined_at": datetime.now().isoformat(),
                                "reason": f"Lock acquisition timed out for candidate {out_file}",
                                "event_id": event_id,
                                "attempted_edition": incoming_edition,
                                "original_event": event,
                                "validation_status": "LOCK_TIMEOUT_QUARANTINED"
                            }
                            if quarantine_dir:
                                q_file = os.path.join(quarantine_dir, f"{q_id}.json")
                                try:
                                    atomic_write_json(q_file, q_record, allow_overwrite=True)
                                except Exception:
                                    pass
                            return {
                                "status": "LOCK_TIMEOUT_QUARANTINED",
                                "relationship_case": "CASE_A_LOCK_TIMEOUT",
                                "event_id": event_id,
                                "error": f"Failed to acquire edition lock within timeout for {out_file}",
                                "quarantine_record": q_record
                            }

                        try:
                            # Re-read freshest candidate from disk under lock
                            fresh_data = {}
                            with open(out_file, "r", encoding="utf-8") as f_fresh:
                                fresh_data = json.load(f_fresh)

                            fresh_history = fresh_data.get("edition_history", [])
                            fresh_current_ed = fresh_data.get("source_edition")
                            if not fresh_history and fresh_current_ed:
                                fresh_history.append({"edition": fresh_current_ed, "recorded_at": fresh_data.get("processed_at")})

                            seen_eds = {h.get("edition") for h in fresh_history}
                            if incoming_edition not in seen_eds:
                                fresh_history.append({"edition": incoming_edition, "recorded_at": datetime.now().isoformat()})

                            fresh_data["edition_history"] = fresh_history
                            fresh_data["source_edition"] = incoming_edition
                            fresh_data["last_edition_update"] = datetime.now().isoformat()

                            # Atomic overwrite with retry to handle Windows file lock contention
                            written = False
                            for _ in range(30):
                                try:
                                    atomic_write_json(out_file, fresh_data, allow_overwrite=True)
                                    written = True
                                    break
                                except PermissionError:
                                    time.sleep(0.01)

                            if not written:
                                # Write failed completely after retries! (A8)
                                # Fail-close: quarantine the incoming event and do not report success.
                                q_id = make_unique_id("EDITION_WRITE_FAIL", event_id)
                                q_record = {
                                    "quarantine_id": q_id,
                                    "quarantined_at": datetime.now().isoformat(),
                                    "reason": "Failed to write candidate edition update after retries (PermissionError)",
                                    "event_id": event_id,
                                    "attempted_edition": incoming_edition,
                                    "original_event": event,
                                    "validation_status": "EDITION_UPDATE_FAILED_QUARANTINED"
                                }
                                if quarantine_dir:
                                    q_file = os.path.join(quarantine_dir, f"{q_id}.json")
                                    try:
                                        atomic_write_json(q_file, q_record, allow_overwrite=True)
                                    except Exception:
                                        pass
                                return {
                                    "status": "EDITION_UPDATE_FAILED_QUARANTINED",
                                    "relationship_case": "CASE_A_EDITION_WRITE_FAILED",
                                    "event_id": event_id,
                                    "error": "Failed to write candidate edition update after retries",
                                    "quarantine_record": q_record
                                }

                            return {
                                "status": "EDITION_UPDATED",
                                "relationship_case": "CASE_A_EDITION_UPDATED",
                                "candidate": fresh_data,
                                "file_path": out_file,
                                "message": f"Candidate {candidate_update['candidate_id']} updated with new edition {incoming_edition}."
                            }
                        finally:
                            if acquired:
                                try:
                                    os.remove(lock_file)
                                except OSError:
                                    pass
                    else:
                        # Case A: Pure duplicate
                        return {
                            "status": "DEDUPLICATED_SKIPPED",
                            "relationship_case": "CASE_A_SAME_ID_SAME_CONTENT_SAME_ORIGIN",
                            "candidate": existing_data,
                            "file_path": out_file,
                            "message": f"Candidate {candidate_update['candidate_id']} already exists with identical content and origin. Skipped rewrite."
                        }
                else:
                    # Case B: Same ID + Same Content + Different URL -> Conflict!
                    conflict_id = make_unique_id("CONFLICT_ORIGIN", event_id)
                    conflict_record = {
                        "conflict_id": conflict_id,
                        "relationship_case": "CASE_B_SAME_ID_SAME_CONTENT_DIFFERENT_ORIGIN",
                        "detected_at": datetime.now().isoformat(),
                        "event_id": event_id,
                        "existing_origin": existing_url,
                        "incoming_origin": incoming_url,
                        "existing_edition": existing_edition,
                        "incoming_edition": incoming_edition,
                        "old_edition": existing_edition,
                        "new_edition": incoming_edition,
                        "incoming_candidate": candidate_update,
                        "validation_status": "CONFLICT_QUARANTINED"
                    }
                    if conflict_dir:
                        c_file = os.path.join(conflict_dir, f"{conflict_id}.json")
                        atomic_write_json(c_file, conflict_record, allow_overwrite=True)
                    return {
                        "status": "CONFLICT_QUARANTINED",
                        "relationship_case": "CASE_B_SAME_ID_SAME_CONTENT_DIFFERENT_ORIGIN",
                        "candidate": None,
                        "message": f"Conflict detected: event_id '{event_id}' has different source origin ('{incoming_url}' vs '{existing_url}'). Preserved existing file.",
                        "conflict_record": conflict_record
                    }
            else:
                # Case C: Same ID + Different Content -> Conflict!
                conflict_id = make_unique_id("CONFLICT_CONTENT", event_id)
                conflict_record = {
                    "conflict_id": conflict_id,
                    "relationship_case": "CASE_C_SAME_ID_DIFFERENT_CONTENT",
                    "detected_at": datetime.now().isoformat(),
                    "event_id": event_id,
                    "existing_edition": existing_edition,
                    "incoming_edition": incoming_edition,
                    "old_edition": existing_edition,
                    "new_edition": incoming_edition,
                    "existing_payload_fingerprint": existing_payload_fp,
                    "incoming_payload_fingerprint": payload_fingerprint,
                    "incoming_candidate": candidate_update,
                    "validation_status": "CONFLICT_QUARANTINED"
                }
                if conflict_dir:
                    c_file = os.path.join(conflict_dir, f"{conflict_id}.json")
                    atomic_write_json(c_file, conflict_record, allow_overwrite=True)
                return {
                    "status": "CONFLICT_QUARANTINED",
                    "relationship_case": "CASE_C_SAME_ID_DIFFERENT_CONTENT",
                    "candidate": None,
                    "message": f"Conflict detected: event_id '{event_id}' already exists with different payload. Preserved existing file, quarantined incoming event.",
                    "conflict_record": conflict_record
                }

        # Case D & E: Check against other candidates in staging_dir
        for fname in os.listdir(staging_dir):
            if fname.endswith(".json") and fname != f"{candidate_update['candidate_id']}.json":
                fpath = os.path.join(staging_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f_existing:
                        item = json.load(f_existing)

                    # Check Case E (Document Revision / New Edition)
                    if (item.get("target") == candidate_update.get("target") and
                        item.get("source_url") == candidate_update.get("source_url") and
                        event.get("source_edition") and
                        item.get("source_edition") and
                        event.get("source_edition") != item.get("source_edition")):
                        candidate_update["relationship_case"] = "CASE_E_DOCUMENT_REVISION_NEW_EDITION"
                        candidate_update["revises_candidate"] = item.get("candidate_id")

                    # Case D: Same Content
                    elif item.get("payload_fingerprint") == payload_fingerprint:
                        # Only consolidate as duplicate if source_url also matches!
                        if item.get("source_url") == candidate_update.get("source_url"):
                            candidate_update["duplicate_of"] = item.get("candidate_id")
                            candidate_update["relationship_case"] = "CASE_D_DIFFERENT_ID_SAME_INFORMATION"
                            candidate_update["possible_duplicate_of"] = item.get("candidate_id")
                        else:
                            candidate_update.setdefault("related_candidates", []).append(item.get("candidate_id"))
                except Exception:
                    pass

        # Atomic exclusive write of candidate update with race and IO error handling
        try:
            atomic_write_json(out_file, candidate_update)
            candidate_update["staging_file"] = out_file
        except FileExistsError as race_err:
            # Race condition: another process created the candidate file concurrently (A1 & A2)
            conflict_id = make_unique_id("CONFLICT_RACE", event_id)
            existing_data_race = {}
            try:
                with open(out_file, "r", encoding="utf-8") as f_ex:
                    existing_data_race = json.load(f_ex)
            except Exception:
                pass
            conflict_record = {
                "conflict_id": conflict_id,
                "relationship_case": "CASE_A_RACE_CONCURRENCY_CONFLICT",
                "detected_at": datetime.now().isoformat(),
                "event_id": event_id,
                "existing_candidate": existing_data_race,
                "incoming_candidate": candidate_update,
                "validation_status": "CONFLICT_QUARANTINED"
            }
            if conflict_dir:
                c_file = os.path.join(conflict_dir, f"{conflict_id}.json")
                try:
                    atomic_write_json(c_file, conflict_record, allow_overwrite=True)
                except Exception:
                    pass
            return {
                "status": "CONFLICT_QUARANTINED",
                "relationship_case": "CASE_A_RACE_CONCURRENCY_CONFLICT",
                "candidate": None,
                "message": f"Concurrency conflict: candidate file '{out_file}' created concurrently. Preserved existing file, quarantined incoming event.",
                "conflict_record": conflict_record
            }
        except OSError as io_err:
            # Staging write failure (A3)
            quarantine_id = make_unique_id("STAGE_WRITE_FAIL", event_id)
            quarantine_record = {
                "quarantine_id": quarantine_id,
                "quarantined_at": datetime.now().isoformat(),
                "reason": f"Failed to write candidate to staging queue: {str(io_err)}",
                "raw_event": event,
                "validation_status": "QUARANTINED_WRITE_ERROR"
            }
            if quarantine_dir:
                q_file = os.path.join(quarantine_dir, f"{quarantine_id}.json")
                try:
                    atomic_write_json(q_file, quarantine_record, allow_overwrite=True)
                except Exception:
                    pass
            return {
                "status": "QUARANTINED_WRITE_ERROR",
                "candidate": None,
                "error": f"Staging write failed: {str(io_err)}. Event preserved in quarantine.",
                "quarantine_record": quarantine_record
            }

    return {
        "status": "CANDIDATE_GENERATED",
        "candidate": candidate_update
    }

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mock_diff = os.path.join(base_dir, "fixtures", "synthetic", "mock_site_diff.json")
    queue_dir = os.path.join(base_dir, "handoff", "event_pipeline_run")
    ref_db_file = os.path.join(base_dir, "fixtures", "synthetic", "mock_official_db.json")

    with open(ref_db_file, "r", encoding="utf-8") as f:
        db = json.load(f)

    res = process_diff_event(mock_diff, queue_dir, reference_db=db)
    print(json.dumps(res, indent=2, ensure_ascii=False))
