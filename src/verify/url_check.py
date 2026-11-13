"""Source URL validation.

Two tiers: format validation (always safe, offline) and live reachability
(opt-in, makes a real network request — callers decide whether that's
appropriate for their context, e.g. nightly batch vs. interactive).
"""
from __future__ import annotations

import dataclasses
import urllib.error
import urllib.request
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"https", "http"}


@dataclasses.dataclass
class UrlCheckResult:
    ok: bool
    reason: str | None = None
    status_code: int | None = None


def check_url_format(url: str) -> UrlCheckResult:
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return UrlCheckResult(False, f"unparseable URL: {exc}")
    if parsed.scheme not in ALLOWED_SCHEMES:
        return UrlCheckResult(False, f"unexpected scheme {parsed.scheme!r}")
    if not parsed.netloc:
        return UrlCheckResult(False, "missing host")
    if parsed.scheme == "http":
        return UrlCheckResult(False, "source should be https, not http (unverifiable/insecure official source)")
    return UrlCheckResult(True)


def _request(url: str, method: str, timeout_seconds: float) -> int:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def check_url_reachable(url: str, *, timeout_seconds: float = 10.0) -> UrlCheckResult:
    """Makes a real HEAD request, falling back to GET if the server rejects
    HEAD outright (405/501 — some official university sites do this).
    Opt-in only — do not call this for every evidence record in a large
    batch without rate limiting; it is meant for spot-checking citations
    before publish.
    """
    fmt = check_url_format(url)
    if not fmt.ok:
        return fmt
    try:
        code = _request(url, "HEAD", timeout_seconds)
        if code in (405, 501):
            code = _request(url, "GET", timeout_seconds)
    except (urllib.error.URLError, TimeoutError) as exc:
        return UrlCheckResult(False, f"unreachable: {exc}")
    if code >= 400:
        return UrlCheckResult(False, f"HTTP {code}", status_code=code)
    return UrlCheckResult(True, status_code=code)
