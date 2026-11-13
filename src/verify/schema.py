"""JSON Schema for the evidence / claim records that back an article.

An "evidence record" is one verified fact pulled from an official source
(a university's own announcement page or PDF) that an article can cite.
An "article claim" is one factual statement inside an article that cites
one or more evidence record ids.

These schemas are deliberately independent of any existing database's
internal column names — Work's real schema is still in flux. They define
the *contract* a record needs to satisfy for the Phase C/D checkers in
this repo to verify it; adapting Work's actual export format to this
contract is Phase E (see docs/INTEGRATION_PLAN.md), not here.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import jsonschema

EVIDENCE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "EvidenceRecord",
    "type": "object",
    "required": [
        "evidence_id",
        "university",
        "faculty",
        "admission_method",
        "fiscal_year",
        "source_url",
        "retrieved_at",
    ],
    "properties": {
        "evidence_id": {"type": "string", "minLength": 1},
        "university": {"type": "string", "minLength": 1},
        "faculty": {"type": "string", "minLength": 1},
        "department": {"type": ["string", "null"]},
        "admission_method": {"type": "string", "minLength": 1},
        "fiscal_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
        "quota": {"type": ["integer", "null"], "minimum": 0},
        "source_url": {"type": "string", "format": "uri"},
        "source_pdf_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
        "retrieved_at": {"type": "string", "format": "date"},
    },
    "additionalProperties": True,
}

ARTICLE_CLAIM_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ArticleClaim",
    "type": "object",
    "required": ["claim_text", "evidence_ids", "fiscal_year"],
    "properties": {
        "claim_text": {"type": "string", "minLength": 1},
        "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 0},
        "fiscal_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
    },
    "additionalProperties": True,
}


def _is_absolute_uri(value: object) -> bool:
    # jsonschema's built-in "uri" check silently does nothing unless an optional
    # package (rfc3987 / rfc3986-validator) is installed, so a clean CI
    # environment would accept garbage. Check explicitly instead.
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    parsed = urlparse(value)
    if not parsed.scheme:
        return False
    if parsed.scheme in ("http", "https"):
        return bool(parsed.netloc)
    return True


def _format_checker() -> jsonschema.FormatChecker:
    checker = jsonschema.FormatChecker()
    checker.checks("uri")(_is_absolute_uri)
    return checker


def validate_evidence(record: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(EVIDENCE_SCHEMA, format_checker=_format_checker())
    return [e.message for e in sorted(validator.iter_errors(record), key=str)]


def validate_article_claim(record: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(ARTICLE_CLAIM_SCHEMA, format_checker=_format_checker())
    return [e.message for e in sorted(validator.iter_errors(record), key=str)]
