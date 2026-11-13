"""Independent check of ONE evidence-correction candidate before a corrected evidence version may be created (contract: docs/EVIDENCE_CORRECTION_VERSION_CONTRACT.md).

A correction never overwrites the predecessor. This module only READS: the candidate item (as Work wrote it), the predecessor record (from a read-only audit copy) and the raw per-page text that the
named extractor produced from the SAVED source file. It returns findings; it opens no database, writes nothing and never calls the network. `error` findings block a corrected version; `warning`
findings need a human decision; `info` is context. It does not check what the source MEANS (`meaning_checked` stays `not_run`): it checks that the correction is anchored in the saved source.

Rules (each is a finding code):
  C-META       the item is an unapplied proposal: applied is False, new_evidence_id is None, meaning_checked is not claimed, an independent review is required
  C-PRED       predecessor_record_sha256 equals the canonical hash of the predecessor record handed in (the diff is against what really exists, not a stale copy)
  C-SOURCE     the source hash and URL of the item equal the predecessor's
  C-LOCATOR    each locator: the quote slice hash and the page-text hash (SHA-256 of the extractor's RAW page text, UTF-8, before normalisation) are recomputed from the page text
  C-PATH       a correction may change only /proofs/<n>/section, /applicability and /published_date; never a quote, a position, a hash, the source or the scope
  C-OLD        every edit's `old` equals the predecessor's current value at that path
  C-SECTION    a proposed section heading occurs before its quote, and no other heading-like line lies between them (it is the NEAREST heading)
  C-YEAR       a proposed applicability text contains a year (4 digits or 令和N年) only if that year occurs in the source; an `old` value with an unsupported year is reported as info
  C-DATE       published_date may be replaced by null only with a separate document-date candidate that really occurs in the source (the date written IN the document is not the publication date)
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

ALLOWED_PATHS = (re.compile(r"^/proofs/\d+/section$"), re.compile(r"^/applicability$"), re.compile(r"^/published_date$"))


def norm(text: str) -> str:
    """Per character NFKC, then drop whitespace: the rule the proofs were recorded with."""
    out: list[str] = []
    for ch in text:
        out.extend(c for c in unicodedata.normalize("NFKC", ch) if not c.isspace())
    return "".join(out)


def canonical_sha256(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _is_heading(line: str) -> bool:
    return line.strip().endswith(("？", "?"))


def _at(record, path: str):
    node = record
    for part in path.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _years(text: str) -> set[int]:
    flat = norm(text)
    found = {int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", flat)}
    found |= {2018 + int(n) for n in re.findall(r"令和(\d{1,2})年", flat)}
    return found


def check_candidate(item: dict, predecessor: dict, page_texts: list[str], *, source_sha256: str, is_heading=_is_heading) -> list[dict]:
    f: list[dict] = []

    def add(code, level, detail):
        f.append({"code": code, "level": level, "detail": detail})

    if item.get("applied") is not False or item.get("new_evidence_id") is not None or item.get("meaning_checked") not in ("not_run", None) or item.get("requires_independent_review") is not True:
        add("C-META", "error", "the item must be an unapplied proposal: applied False, new_evidence_id None, meaning_checked not claimed, requires_independent_review True")
    if item.get("predecessor_record_sha256") != canonical_sha256(predecessor):
        add("C-PRED", "error", "predecessor_record_sha256 does not equal the hash of the predecessor record: the proposal was made against another record")
    pred_sha = predecessor.get("source_pdf_sha256") or predecessor.get("source_sha256")
    if not (item.get("source_sha256") == pred_sha == source_sha256) or item.get("source_url") != predecessor.get("source_url"):
        add("C-SOURCE", "error", "source hash or URL differs from the predecessor's, or the saved file does not hash to it")

    norm_pages = [norm(p) for p in page_texts]
    for loc in item.get("locators", []):
        page_no = loc.get("page")
        if not isinstance(page_no, int) or not 1 <= page_no <= len(page_texts):
            add("C-LOCATOR", "error", f"proof {loc.get('proof_index')}: page {page_no} does not exist")
            continue
        sl = norm_pages[page_no - 1][loc["normalized_start"]:loc["normalized_end"]]
        if hashlib.sha256(sl.encode()).hexdigest() != loc.get("quote_sha256") or not sl:
            add("C-LOCATOR", "error", f"proof {loc.get('proof_index')}: the quote slice does not hash to quote_sha256")
        if hashlib.sha256(page_texts[page_no - 1].encode()).hexdigest() != loc.get("source_page_text_sha256"):
            add("C-LOCATOR", "error", f"proof {loc.get('proof_index')}: source_page_text_sha256 is not the hash of the extractor's raw page text")
    spans = [(l.get("page"), l.get("normalized_start"), l.get("normalized_end")) for l in item.get("locators", [])]
    if len(spans) != len(set(spans)):
        add("C-LOCATOR", "warning", "two proofs cite the same span: one of them adds no evidence")

    locators = {l["proof_index"]: l for l in item.get("locators", []) if "proof_index" in l}
    for edit in item.get("proposed_edits", []):
        path = edit.get("path", "")
        if not any(p.match(path) for p in ALLOWED_PATHS):
            add("C-PATH", "error", f"{path}: a correction may not change this field")
            continue
        try:
            current = _at(predecessor, path)
        except (KeyError, IndexError, ValueError):
            add("C-OLD", "error", f"{path}: the predecessor has no such field")
            continue
        if current != edit.get("old"):
            add("C-OLD", "error", f"{path}: `old` is not the predecessor's current value")
        if path.endswith("/section"):
            idx = int(path.split("/")[2]); loc = locators.get(idx)
            if loc is None or not isinstance(loc.get("page"), int) or not 1 <= loc["page"] <= len(page_texts):
                add("C-SECTION", "error", f"proof {idx}: no valid locator to anchor the heading")
                continue
            lines = page_texts[loc["page"] - 1].split("\n"); pos = 0; heads = []
            for ln in lines:
                if is_heading(ln):
                    heads.append((pos, norm(ln)))
                pos += len(norm(ln))
            before = [h for h in heads if h[0] < loc["normalized_start"]]
            if not before or before[-1][1] != norm(edit["proposed"]):
                add("C-SECTION", "error", f"proof {idx}: the proposed heading is not the nearest heading before the quote (nearest: {before[-1][1][:30] if before else None})")
        elif path == "/applicability":
            source_years = set().union(*[_years(p) for p in page_texts]) if page_texts else set()
            unsupported = _years(edit.get("proposed") or "") - source_years
            if unsupported:
                add("C-YEAR", "error", f"the proposed applicability names year(s) {sorted(unsupported)} that do not occur in the source")
            if _years(edit.get("old") or "") - source_years:
                add("C-YEAR", "info", f"the old applicability names year(s) {sorted(_years(edit['old']) - source_years)} that the source does not contain")
        elif path == "/published_date":
            doc_date = edit.get("document_date_separate_candidate")
            if edit.get("proposed") is not None:
                add("C-DATE", "error", "a corrected publication date may only be null here: the date inside a document is not its publication date")
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", doc_date or "")
            if not m:
                add("C-DATE", "error", "a null published_date needs the document date as a separate candidate (YYYY-MM-DD)")
            else:
                y, mo, d = (int(x) for x in m.groups())
                flat = norm("\n".join(page_texts))
                western = f"{y}年{mo}月{d}日" in flat
                reiwa = f"令和{y - 2018}年{mo}月{d}日" in flat
                if not (western or reiwa):
                    add("C-DATE", "error", f"the document date {doc_date} does not occur in the source")
    return f


def blocking(findings: list[dict]) -> list[dict]:
    return [x for x in findings if x["level"] == "error"]
