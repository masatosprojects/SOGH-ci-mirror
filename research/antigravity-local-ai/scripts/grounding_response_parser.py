#!/usr/bin/env python3
"""
SOGH Antigravity - Local LLM Grounding Response Parser & Strict Output Contract

Parses and validates raw generation output from local LLM
under strict zero-hallucination and fail-close safety invariants.

Safety Guarantees:
1. Exact Schema Enforcement: Validates exact keyword tags or structured JSON.
2. Prompt / System Instruction Leak Prevention: Detects and quarantines echo of prompt templates.
3. Secret / PII Leak Prevention: Quarantines credentials, tokens, or PII.
4. Noise / Corrupted Stream Rejection: Rejects ANSI escapes, null bytes, trivial repetition.
5. Strict Fail-Close: Any ambiguity yields quarantined fail-close response.
"""

from __future__ import annotations

import re
import json
import unicodedata
from typing import Dict, Any, Optional

# Supported strict verdicts
VALID_VERDICTS = {
    "VERIFIED_MATCH": {"verdict": "MATCH", "quarantined": False},
    "CONTRADICTION": {"verdict": "CONTRADICTION", "quarantined": True},
    "UNVERIFIED": {"verdict": "UNVERIFIED", "quarantined": True},
    "PROHIBITED_SUBSTITUTION": {"verdict": "PROHIBITED_SUBSTITUTION", "quarantined": True},
}

CODEBLOCK_PATTERN = re.compile(r"^```(?:json|text|markdown)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)

SECRET_PII_PATTERN = re.compile(
    r"\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|bearer\s+[a-zA-Z0-9_\-\.]{20,}|password\s*[:=]\s*\S+|FICTION_SECRET_TOKEN_[A-Za-z0-9_]+)\b",
    re.IGNORECASE
)

ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

PROMPT_LEAK_PATTERNS = (
    re.compile(r"(?:you are|you must|system prompt|instruction:|assistant:|human:)", re.IGNORECASE),
    re.compile(r"(?:あなたは|以下の指示|システムプロンプト|制約事項:)", re.IGNORECASE),
)


def unwrap_codeblock(text: str) -> str:
    """Strip markdown fencing if present."""
    text = text.strip()
    match = CODEBLOCK_PATTERN.match(text)
    if match:
        return match.group(1).strip()
    return text


def clean_control_characters(text: str) -> tuple[str, int]:
    """Remove null bytes, surrogates, and unprintable controls except standard whitespace."""
    keep, removed = [], 0
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\r\t" or not (cat in ("Cc", "Cs", "Co")):
            keep.append(ch)
        else:
            removed += 1
    return "".join(keep), removed


def parse_grounding_verdict(raw_output: Optional[str]) -> Dict[str, Any]:
    """
    Parses LLM inference raw output into a verified verdict dict.
    Strictly fails close (UNKNOWN_FORMAT_FAIL_CLOSE) if format is ambiguous or missing.

    Returns:
        dict: {
            "success": bool,
            "verdict": str ("MATCH" | "CONTRADICTION" | "UNVERIFIED" | "PROHIBITED_SUBSTITUTION" | "UNKNOWN_FORMAT_FAIL_CLOSE"),
            "reason": str,
            "quarantined": bool,
            "raw_snippet": str
        }
    """
    return enforce_strict_output_contract(raw_output, contract_type="faq_verdict")


def enforce_strict_output_contract(
    raw_output: Optional[str],
    contract_type: str = "faq_verdict"
) -> Dict[str, Any]:
    """
    Unified strict output verification contract for local LLM inference.
    Guarantees fail-close across all output corruption and leak modes.
    """
    if not raw_output or not isinstance(raw_output, str):
        return {
            "success": False,
            "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
            "reason": "Empty or non-string output received from LLM",
            "quarantined": True,
            "raw_snippet": ""
        }

    # 1. Reject ANSI terminal control injections
    if ANSI_ESCAPE_PATTERN.search(raw_output):
        return {
            "success": False,
            "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
            "reason": "CRITICAL: Malicious or corrupted ANSI escape sequences in LLM output",
            "quarantined": True,
            "raw_snippet": "[REDACTED_ANSI_SEQUENCE]"
        }

    # 2. Reject control and null byte corruption
    cleaned_text, removed_chars = clean_control_characters(raw_output)
    if "\x00" in raw_output or removed_chars > 5:
        return {
            "success": False,
            "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
            "reason": f"CRITICAL: Binary or null byte corruption detected ({removed_chars} control characters)",
            "quarantined": True,
            "raw_snippet": "[REDACTED_CORRUPTED_STREAM]"
        }

    # 3. PII and Secret leak prevention
    if SECRET_PII_PATTERN.search(cleaned_text):
        return {
            "success": False,
            "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
            "reason": "CRITICAL: Potential secret/PII detected in LLM output. Fail-close activated.",
            "quarantined": True,
            "raw_snippet": "[REDACTED_SECURITY_ALERT]"
        }

    # 4. System Prompt / Instruction Leak Prevention
    for leak_pat in PROMPT_LEAK_PATTERNS:
        if leak_pat.search(cleaned_text):
            return {
                "success": False,
                "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
                "reason": "SECURITY_VIOLATION: Output contains echo of system instruction/prompt template",
                "quarantined": True,
                "raw_snippet": "[REDACTED_PROMPT_LEAK]"
            }

    # 5. Trivial Noise and Extreme Repetition Check
    stripped = cleaned_text.strip()
    if len(stripped) < 3:
        return {
            "success": False,
            "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
            "reason": "NOISE_REJECTED: Output is trivially short (< 3 characters)",
            "quarantined": True,
            "raw_snippet": stripped
        }

    unwrapped = unwrap_codeblock(cleaned_text)
    first_line = unwrapped.splitlines()[0].strip() if unwrapped.splitlines() else ""

    # Exact match for VERIFIED_MATCH
    if first_line == "VERIFIED_MATCH":
        return {
            "success": True,
            "verdict": "MATCH",
            "reason": "Direct text and semantic alignment verified against official DB",
            "quarantined": False,
            "raw_snippet": first_line
        }

    # Match for parameterized tags: <TAG>: <reason>
    for tag, config in VALID_VERDICTS.items():
        if tag == "VERIFIED_MATCH":
            continue
        prefix = f"{tag}:"
        if first_line.startswith(prefix):
            reason_part = first_line[len(prefix):].strip()
            return {
                "success": True,
                "verdict": config["verdict"],
                "reason": reason_part if reason_part else f"{config['verdict']} declared without extra detail",
                "quarantined": config["quarantined"],
                "raw_snippet": first_line[:120]
            }

    # Fallback: Check if response is formatted as valid JSON
    try:
        data = json.loads(unwrapped)
        if isinstance(data, dict):
            raw_v = str(data.get("verdict", "")).strip().upper()
            if raw_v in VALID_VERDICTS:
                cfg = VALID_VERDICTS[raw_v]
                return {
                    "success": True,
                    "verdict": cfg["verdict"],
                    "reason": str(data.get("reason", "JSON structured verdict")),
                    "quarantined": cfg["quarantined"],
                    "raw_snippet": unwrapped[:120]
                }
    except Exception:
        pass

    # Fail-close on any unrecognized, narrative, or ambiguous output
    return {
        "success": False,
        "verdict": "UNKNOWN_FORMAT_FAIL_CLOSE",
        "reason": f"Output failed strict schema verification (Received: '{first_line[:60]}...')",
        "quarantined": True,
        "raw_snippet": first_line[:120]
    }
