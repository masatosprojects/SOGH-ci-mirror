# M1 g6 SELF_TEST: first REAL pair of editions (Tsukuba AC, 令和8年度 -> 令和9年度) (2026-11-13)

Status: SELF_TEST by the author (Claude). NOT an independent QA and NOT an acceptance of g6. Two real editions of ONE document. The oracle is a plain string search.
Reproduce (manual, needs the PDF and the pinned file): `python -m pytest tests/qa_g6_real_pair_real_clone.py -q -p no:cacheprovider`, or `python scripts/g6_real_pair_e2e.py <disposable-migrated-copy.sqlite> <old.pdf>` (JSON, exit 0 only when all 16 checks hold). No original document text is committed: this file holds hashes, counts and excerpts of at most 30 characters with page numbers.

## Editions

- OLD (rev 1): official Tsukuba AC guideline for 令和8年度 (2026 admission), `AC-2026-youkou_sec.pdf`, SHA-256 `81a8635f...f571`, 15 pages, PyMuPDF raw page text (series text 16,622 chars).
- NEW (rev 2): the stored edition for 令和9年度, source sha `49cb4d7d...`, 15 pages from `source_pages` of the clone (17,125 chars). The series edition hash is over the joined page text (`74fc4ac2...` / `61f13f48...`), not the PDF SHA.
- Clone: copy of the pinned v06 file (SHA-256 `a8e48b5b...539578`, checked at the end: unchanged), migrated 0002..0014 on the copy. Old PDF SHA also re-checked unchanged.

## Method

Series registered with `src/versioning/series.py` (0014 tables), lineage and rows verified; diff and impact from `src/versioning/*` unchanged. Direction: the stored evidence was taken from the NEW edition, so the OLD edition is passed to `assess_export` as the edition to check against (the stored new edition is its "old snapshot", which gives `page_changed`). A sanity run of the stored evidence against its own edition: all intact.
Independent oracle: for each proof of each evidence whose source is `49cb4d7d`, NFKC + whitespace-free string search of the quote in the old page of the same number, else in any old page; absent everywhere = CHANGED. Articles: oracle uses (a) the citations in the head article text and (b) the clone's `article_evidence` table (by base article id).

## Numbers (real run)

| Item | Result |
|---|---|
| Evidence of the stored new edition | 14 evidence, 19 proofs (the 46 facts / 57 proofs of the whole DB include the other three sources, which have no old edition here) |
| Oracle proofs | unchanged on the same page 12, moved to another old page 1, CHANGED 6 |
| Oracle evidence changed | 5: EV-T27-05, -06, -09, -10, -11 (one of them, -09, has two changed proofs) |
| Product evidence flagged (reworded 4, value_change 1) | the same 5; proof-level statuses agree with the oracle on all 19 proofs (0 mismatches) |
| Product other evidence | page_changed 9 (intact quote on a page with other value changes), intact 35, unassessed 6 (EV-U-*: no stored pages), moved 0 |
| Articles (6 heads) flagged `revision_candidate` | 2 (the Tsukuba `overview` and `interview` articles); equals the oracle by text citations AND by the `article_evidence` table |
| Not flagged | 4 (two Keio articles, two Tsukuba general-front articles); none cites changed evidence; `review_same_page` 0 |
| Recorded impacts (0014 table) | 7 rows (overview x 5 evidence, interview x 2 evidence), 2 distinct articles |
| Diff old -> new | pages added 3, removed 3 (page matching, not moved), changed 11, changed lines 27, lines with value changes 20 |
| Guards | 7 of 7 refused (`G-06 VIOLATION`); edition rows 2 before and 2 after |
| Original tables | 41 tables, 930 rows: identical row for row before and after; only `source_document_series_editions` (0 -> 2) and `series_revision_article_impacts` (0 -> 7) grew |

No disagreement between the product and the oracle was found.

## Genuine changes found (evidence-bearing statements; old value -> new value; the quotes are in the NEW edition)

All six are date changes; the quota cell (EV-T27-01) and the other quotas are unchanged between the editions.

| Evidence | New page | Old excerpt | New excerpt |
|---|---|---|---|
| EV-T27-05 | 9 | `令和7年8月7日(木)9:00` | `令和8年8月6日(木)9:00` (registration/fee start) |
| EV-T27-06 | 9 | `令和7年9月1日(月)~9月3日(水` | `令和8年9月1日(火)~9月3日(木)` (mailing of documents) |
| EV-T27-09 | 11 | `図書館学類10月9日(木)` | `図書館学類10月8日(木)` |
| EV-T27-09 | 4 | `令和7年10月8日` (2nd selection) | `令和8年10月7日` |
| EV-T27-10 | 12 | `令和7年11月4日(火)10:00` (final result) | `令和8年11月2日(月)10:00` |
| EV-T27-11 | 4 | `令和7年9月29日(月)10:00` (1st result) | `令和8年10月1日(木)10:00` |

The diff also reports changes outside the evidence (cover page year 令和8->9, page 2 and 13 numbers, page 6 eligibility dates, page 8 fee area, page 9-10 documents deadline `7月31日 -> 7月30日`, added sentences on pages 7, 10, 11, 13); these carry no stored evidence and are NOT mapped to articles. The old and new excerpts are for human review only.

## Tests

`tests/test_m1_g6_real_pair_e2e.py` (9 tests, never skipped, no PDF, no real DB; synthetic fixture from `tests/db_support.py`, fictional text): changed quota flags only the citing article (both directions); a quote that only moved is not a change; a sentence missing in the old edition flags a second article; identical text and unmigrated DB / wrong prefix / same hash / no pages are refused without a write; old rows unchanged and series title not SIMULATED; excerpt limit; CLI prints UTF-8 JSON even under `PYTHONIOENCODING=ascii`; CLI argument errors exit 2. Manual: `tests/qa_g6_real_pair_real_clone.py` (no `test_` prefix; fails if a file is missing) asserts the numbers above. With the earlier g6 test files: 55 passed.

## Limits (read before relying on this)

- SELF_TEST by the author; no independent QA; no acceptance of g6 claimed. Two real editions of ONE document (one university, one cycle change); says nothing about other documents or layout re-typesetting.
- The oracle is string-based (NFKC, whitespace removed, exact substring): it and the product share the same normalisation idea, so a systematic extraction difference would affect both. Dates are compared as text; a changed weekday alone counts as a change.
- Only evidence of the stored `49cb4d7d` source can be checked (14 of 55 evidence). `EV-U-*` evidence (6) stays `unassessed`; each flagged article also cites 2 such unassessed evidence, and 2 articles are product-`unassessed` for that reason. Changes without a stored quote are not mapped to any article.
- The relation text-citations vs `article_evidence` differs for all 6 heads (heads cite `EV-U-*` that the table lacks; the general-front heads miss `EV-G27-01` in the text); it does not affect the flagged set.
- Whole-article QA FAIL (13 articles) is NOT addressed. The 6 articles are unpublished heads in the pinned file.
- The series stores raw extracted text including odd control characters; the series hash is over joined text. 0014 has no metadata column, so the "REAL / official" label lives only in the series title.
- Nothing was written to the real database or the PDF; nothing published; no Work-owned file touched; no network access.
