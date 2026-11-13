#!/usr/bin/env python3
"""
SOGH Antigravity - Local AI Input/Output Security & Grounding Sanitizer

Dedicated exclusively to Antigravity's role:
Enforcing local model execution boundaries, privacy preservation, and hostile
input sanitization without duplicating Claude Code's interview engine or PR #252.

Status Note:
Strategy PR #252 is an unapproved proposal (PROPOSAL_ONLY / NOT_USER_APPROVED).
Keyword presence does NOT prove semantic understanding and is never claimed as such.

Core Local AI Safety Safeguards:
1. Hostile Input Sanitization:
   - Strips invisible formatting characters, zero-width spaces, BOM, control characters.
   - Enforces MAX_INPUT_CHARS limit to prevent memory/CPU exhaustion.
2. Privacy & Secret Containment:
   - Masks PII (emails, phone numbers, handles, postal codes, URLs) and synthetic tokens.
   - 100% pure in-memory execution; zero external network egress.
3. Forbidden & Hallucinated Claim Detection:
   - Detects ungrounded marketing promises (合格確実, 完全再現, etc.).
   - Rejects unverified official claims (倍率, 定員, 締切, etc.) without official DB backing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

MAX_INPUT_CHARS = 4000

OFFICIAL_CLAIM_WORDS = (
    "倍率", "定員", "募集人員", "締切", "出願期間", "出願期限",
    "募集要項", "公式", "配点", "合格最低点", "選考日程", "試験日"
)
OFFICIAL_CLAIM_PATTERN = re.compile(r"(面接|試験|選考|出願|入試)[^。！？\n]{0,12}[0-9０-９]")
PROVENANCE_PREFIX = "あなたが入力した"

_DENIAL = r"(?![^。、]{0,24}(?:とは限りません|とは限らない|ではありません|ではない|ものではありません|を意味しません|保証しません|しません|できません))"
FORBIDDEN_CLAIMS = (
    re.compile(r"合格(率|確率|可能性)\s*(?:は|が|[:：])?\s*(?:約|およそ)?\s*\d"),
    re.compile(r"合格(できます|間違い|保証|確実)" + _DENIAL),
    re.compile(r"(大学|学校)(公認|公式認定)(?!でも(ありません|ない)|ではありません|ではない)"),
    re.compile(r"完全(に)?再現" + _DENIAL),
    re.compile(r"再現度\s*\d"),
    re.compile(r"必ず(出題|聞かれ)" + _DENIAL),
    re.compile(r"(出題|質問)(されます|される予定)" + _DENIAL),
    re.compile(r"実際の(入試|面接)(と同じ|そのまま)" + _DENIAL),
    re.compile(r"\d+\s*(点|％|%)\s*(満点|で合格)"),
)

SECRET_TOKEN_PATTERN = re.compile(r"FICTION_SECRET_TOKEN_[A-Za-z0-9_]+")
_D = "0-9０-９"
_SEP = r"[-\s‐-―−－ー]?"
_AT = r"(?:[@＠]|\s*[\(\[（［]\s*(?:at|AT|アット)\s*[\)\]）］]\s*)"
EMAIL_PATTERN = re.compile(rf"[\w.+\-]+{_AT}[\w\-]+(?:[.．][\w\-]+)+")
PHONE_PATTERN = re.compile(rf"(?:[+＋]\s?[8８][1１]{_SEP}|[0０])[{_D}]{{1,4}}{_SEP}[{_D}]{{1,4}}{_SEP}[{_D}]{{3,4}}")
URL_PATTERN = re.compile(r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.I)
HANDLE_PATTERN = re.compile(r"(?<![\w@＠])[@＠][A-Za-z0-9_]{3,15}(?![\w@＠])")
POSTAL_PATTERN = re.compile(rf"〒\s?[{_D}]{{3}}{_SEP}[{_D}]{{4}}")


@dataclass(frozen=True)
class SanitizationResult:
    is_safe: bool
    verdict: str  # e.g. "SAFE_GROUNDED", "REJECTED_UNGROUNDED_CLAIM", "REJECTED_FORBIDDEN_CLAIM", "REJECTED_OVERSIZED_INPUT"
    reason: str
    cleaned_text: str
    details: Dict[str, Any]


def clean_hostile_characters(text: str) -> Tuple[str, int]:
    """
    Remove control characters, zero-width characters, BOM, bidi overrides,
    and private-use characters. Returns cleaned text and removed count.
    """
    keep, removed = [], 0
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\t" or not (cat in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")):
            keep.append(ch)
        else:
            removed += 1
    return "".join(keep), removed


def mask_secrets_and_pii(text: str) -> str:
    """Mask synthetic secrets and all PII shapes safely."""
    masked = SECRET_TOKEN_PATTERN.sub("[MASKED_TOKEN]", text)
    masked = EMAIL_PATTERN.sub("[メール]", masked)
    masked = URL_PATTERN.sub("[リンク]", masked)
    masked = HANDLE_PATTERN.sub("[アカウント名]", masked)
    masked = POSTAL_PATTERN.sub("[郵便番号]", masked)
    masked = PHONE_PATTERN.sub("[電話番号]", masked)
    return masked


def extract_quoted_segments(text: str) -> List[str]:
    """Extract all text within 「」 brackets."""
    return re.findall(r"「([^」]+)」", text)


def sanitize_and_validate_local_output(
    output_text: str,
    reference_context: Optional[str] = None
) -> SanitizationResult:
    """
    Sanitize and validate local model output against security and anti-hallucination boundaries.
    Ensures:
    1. Size within MAX_INPUT_CHARS.
    2. Hostile / invisible control characters stripped.
    3. Secrets and PII masked.
    4. Prohibits marketing guarantees and ungrounded official claims.
    5. If reference_context is provided and output contains quotes 「...」, quotes must match reference.
    """
    if not output_text or not isinstance(output_text, str):
        return SanitizationResult(
            is_safe=False,
            verdict="REJECTED_EMPTY_OUTPUT",
            reason="Output text is empty or non-string",
            cleaned_text="",
            details={}
        )

    if len(output_text) > MAX_INPUT_CHARS:
        return SanitizationResult(
            is_safe=False,
            verdict="REJECTED_OVERSIZED_INPUT",
            reason=f"Output exceeds character limit ({len(output_text)} > {MAX_INPUT_CHARS})",
            cleaned_text="",
            details={"length": len(output_text), "limit": MAX_INPUT_CHARS}
        )

    cleaned, removed_count = clean_hostile_characters(output_text)
    masked = mask_secrets_and_pii(cleaned)

    # Check for unmasked secret leaks
    if SECRET_TOKEN_PATTERN.search(cleaned):
        return SanitizationResult(
            is_safe=False,
            verdict="REJECTED_SECRET_LEAK",
            reason="Output leaks unmasked synthetic secret token",
            cleaned_text=masked,
            details={}
        )

    # Prohibit forbidden marketing claims
    for pat in FORBIDDEN_CLAIMS:
        if pat.search(cleaned):
            return SanitizationResult(
                is_safe=False,
                verdict="REJECTED_FORBIDDEN_CLAIM",
                reason=f"Output makes forbidden marketing guarantee: {pat.pattern}",
                cleaned_text=masked,
                details={"pattern": pat.pattern}
            )

    # Prohibit ungrounded official claims
    for word in OFFICIAL_CLAIM_WORDS:
        if word in cleaned:
            return SanitizationResult(
                is_safe=False,
                verdict="REJECTED_UNGROUNDED_CLAIM",
                reason=f"Output asserts unverified official claim term: '{word}'",
                cleaned_text=masked,
                details={"prohibited_term": word}
            )

    if OFFICIAL_CLAIM_PATTERN.search(cleaned):
        return SanitizationResult(
            is_safe=False,
            verdict="REJECTED_UNGROUNDED_CLAIM",
            reason="Output contains unverified official date/number pattern",
            cleaned_text=masked,
            details={"pattern": "OFFICIAL_CLAIM_PATTERN"}
        )

    # If reference context provided, verify verbatim quotation integrity
    if reference_context:
        cleaned_ref, _ = clean_hostile_characters(reference_context)
        quotes = extract_quoted_segments(cleaned)
        for q in quotes:
            if q not in cleaned_ref:
                return SanitizationResult(
                    is_safe=False,
                    verdict="REJECTED_FABRICATED_QUOTE",
                    reason=f"Quoted phrase 「{q}」 does not appear in reference context",
                    cleaned_text=masked,
                    details={"unverified_quote": q}
                )

    return SanitizationResult(
        is_safe=True,
        verdict="SAFE_GROUNDED",
        reason="Output safely sanitized, bounds verified, zero ungrounded claims",
        cleaned_text=masked,
        details={"removed_hostile_chars": removed_count}
    )
