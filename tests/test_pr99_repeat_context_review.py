"""Independent QA for M1.g6 (PR #99, heads 1037347 and 8ae0a63: `research/inbox/work-g6-candidate-e2e/repeat_context_evidence.py`) and an independent recomputation of the whole-view article QA findings.

Claude-owned QA. The BASELINE tests (section 1) need no Work file: they recompute the gate's findings on the repository's own 13-article current view with the repository's own `src.article_qa`.
The DIAGNOSTIC tests (section 2) are DEFINED ONLY when Work's file exists (SOGH_WORK_G6_DIR may point at the directory) and use invented articles. No article text is asserted or printed: counts, lengths, kinds and ids only.
Passing accepts nothing: the whole-view QA still FAILS (that is the correct, unchanged result), no threshold or rule is changed, and g6 stays unmet (M1 2/8, NOT ACCEPTED). A synthetic update is never counted as g6."""
import ast
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

from src.article_qa import checks
from src.article_qa import duplication_context as dc

REPO = Path(__file__).resolve().parents[1]
VIEW = REPO / "research" / "inbox" / "work-updates-v2" / "samples" / "current" / "active-state.json"
WORK = Path(os.environ.get("SOGH_WORK_G6_DIR") or REPO / "research" / "inbox" / "work-g6-candidate-e2e")
EMPTY_RULES = {"version": "empty-diagnostic", "entries": []}


def windows(articles):
    return {ast.literal_eval(f.detail.rsplit(" appears verbatim", 1)[0]) for f in checks.find_overused_phrases(articles)}


def maximal_segments(articles, phrases, rules):
    """Collapse the overlapping 12-character windows of the gate into maximal repeated runs, per article; return the set of distinct runs (by hash)."""
    out = set()
    for text in articles.values():
        flat, _, lineno = dc._spans(text, rules)
        mark = [False] * len(flat)
        for i in range(max(0, len(flat) - 11)):
            if flat[i:i + 12] in phrases:
                for j in range(i, i + 12):
                    mark[j] = True
        i = 0
        while i < len(flat):
            if not mark[i]:
                i += 1
                continue
            j = i
            while j < len(flat) and mark[j]:
                j += 1
            out.add(hashlib.sha256(flat[i:j].encode()).hexdigest())
            i = j
    return out


# ------------------------------------------------------------------ 1. the baseline, recomputed independently (no Work file)
def test_the_repository_view_gives_299_overused_windows_and_one_near_duplicate_pair_as_reported():
    view = json.loads(VIEW.read_text(encoding="utf-8"))  # a missing sample FAILS here (FileNotFoundError): in this repository a skip is not a pass
    articles = {a["article_id"]: a["text"] for a in view["articles"]}
    assert len(articles) == len(view["articles"]) == 13 and len(view["evidence"]) == 50
    assert len(checks.find_overused_phrases(articles)) == 299
    ids = sorted(articles)
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if checks.near_duplicate_score(articles[a], articles[b], 5) >= 0.85]
    assert len(pairs) == 1 and all(":documents:" in x and "niigata" in x for x in pairs[0])  # the two Niigata "documents" articles (law I, humanities II)


def test_the_299_windows_are_a_few_dozen_repeated_segments_and_the_classifier_counts_the_same_repeats_as_the_gate():
    """What '299 findings' means: every repeated sentence of n characters yields n-11 overlapping windows, so the gate's count is a sum over a few shared segments, not 299 independent template phrases.
    Recomputed here with my own run-merging; the number of distinct maximal runs is pinned as a characterisation of THIS view (it changes if the articles change)."""
    view = json.loads(VIEW.read_text(encoding="utf-8"))
    articles = {a["article_id"]: a["text"] for a in view["articles"]}
    phrases = windows(articles)
    runs = maximal_segments(articles, phrases, dc.load_rules(EMPTY_RULES))
    assert len(phrases) == 299 and len(runs) == 28 and len(runs) * 10 < len(phrases)
    report = dc.classify_repeats(articles, dc.load_rules(EMPTY_RULES))
    assert report["total"] == 299 and dc.gate_unchanged(articles, dc.load_rules(EMPTY_RULES)) and dc.thresholds_are_the_gates()  # the report adds kinds, changes no gate


def test_the_whole_view_still_fails_and_the_failure_is_scaffold_and_template_not_a_changed_fact():
    view = json.loads(VIEW.read_text(encoding="utf-8"))
    articles = {a["article_id"]: a["text"] for a in view["articles"]}
    kinds = Counter()
    for repeat in dc.classify_repeats(articles, dc.load_rules(EMPTY_RULES))["repeats"]:
        kinds.update(repeat["kinds"])
    assert set(kinds) <= {"heading_unregistered", "prose", "cross_line", "cited_fact_sentence", "source_item"}
    assert kinds["source_item"] + kinds["cross_line"] + kinds["heading_unregistered"] > kinds["cited_fact_sentence"]  # the repeats are mostly source lines, headings and line-crossing windows, rarely cited facts
    assert len(checks.find_overused_phrases(articles)) >= 1  # a failing gate is the correct current result: it is never made to pass by a threshold or an exclusion


# ------------------------------------------------------------------ 2. the diagnostic (Work's code), on invented articles
# Head 8ae0a63 ("Trace all article QA windows") REPLACED the earlier "one minimal occurrence per kind" report: `diagnose(view, rules, *, all_articles=False)` now returns `(summary, windows)` where every window of the gate carries
# EVERY occurrence (`locations`: article, 1-based lines, raw and normalised spans, the raw text, the kind and a next action) and the summary lists every near-duplicate pair. These tests are written for that contract.
if (WORK / "repeat_context_evidence.py").exists():
    sys.path.insert(0, str(WORK))
    spec = importlib.util.spec_from_file_location("pr99_repeat_context", WORK / "repeat_context_evidence.py")
    rce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rce)

    SHARED = "これは五つ以上の記事に逐語で現れる共通の合成文ですそのまま"  # 29 characters (len(SHARED) - 11 = 18 windows of its own; neighbouring lines add windows that cross the line break)
    RULES = dc.load_rules(EMPTY_RULES)
    ACTION = {"source_item": "contract_review_preserve_source", "mandatory_notice": "contract_review_preserve_notice", "heading_registered": "contract_review_preserve_heading",
              "heading_unregistered": "review_shared_section_structure", "cited_fact_sentence": "compare_fact_scope_and_preserve_citation",
              "cross_line": "review_whitespace_normalization_boundary", "prose": "review_repeated_editorial_text"}

    def entry(i, lines, series="overview"):
        return {"article_id": f"a{i}", "series": series, "text": "\n".join(lines)}

    def corpus(n=5, with_documents=True):
        entries = [entry(i, [f"記事{i}の固有の導入文はここだけに{i * 7919}あります", SHARED, f"記事{i}の固有の結びの文は別です{i * 104729}", f"秘匿トークン{i}番{i * 65537}は他のどこにも無い行"]) for i in range(n)]
        if with_documents:
            entries[0]["series"] = entries[1]["series"] = "documents"
        return {"articles": entries}

    def independent_trace(articles):
        """For every gate window, every start position in every article, found by my own scan of the whitespace-stripped text: {phrase: [(article, start)]}."""
        trace = {}
        for aid, text in articles.items():
            flat = "".join(ch for ch in text if not ch.isspace())
            for pos in range(max(0, len(flat) - 11)):
                trace.setdefault(flat[pos:pos + 12], []).append((aid, pos))
        gate = windows(articles)
        return {p: trace[p] for p in gate}

    def line_of(text, flat_pos):
        """1-based line of the flat (whitespace-stripped) position, by a separate walk."""
        seen = 0
        for n, line in enumerate(text.splitlines()):
            length = sum(1 for ch in line if not ch.isspace())
            if flat_pos < seen + length:
                return n + 1
            seen += length
        raise AssertionError("position beyond the text")

    def test_every_gate_window_is_reported_with_every_occurrence_and_nothing_else():
        """The trace must be complete and exact: the same set of phrases as the gate, and for each phrase exactly the occurrences my own scan finds (including repeats inside one article)."""
        view = corpus()
        articles = {a["article_id"]: a["text"] for a in view["articles"]}
        summary, index = rce.diagnose(view, RULES)
        expected = independent_trace(articles)
        assert set(index) == set(expected) and summary["total"] == len(expected) >= len(SHARED) - 11 and summary["gate_unchanged"] is True
        for phrase, row in index.items():
            assert row["rule"] == "overused_template_phrase" and row["phrase"] == phrase
            assert sorted((h["article_id"], h["normalized_span"][0]) for h in row["locations"]) == sorted(expected[phrase]), phrase

    def test_a_phrase_that_repeats_inside_one_article_is_traced_at_every_position():
        """Found by mutation: with only one occurrence per article in the invented corpus, a trace that stopped at the first occurrence in each article looked complete."""
        view = corpus()
        for i in (1, 3):  # two articles carry the shared sentence twice, with different lines between the two copies
            view["articles"][i]["text"] += "\n" + f"間に入る固有の行{i * 99991}\n" + SHARED
        articles = {a["article_id"]: a["text"] for a in view["articles"]}
        _, index = rce.diagnose(view, RULES)
        expected = independent_trace(articles)
        doubled = [p for p, hits in expected.items() if sum(1 for a, _ in hits if a == "a1") >= 2]
        assert doubled and set(index) == set(expected)
        for phrase in doubled:
            assert sorted((h["article_id"], h["normalized_span"][0]) for h in index[phrase]["locations"]) == sorted(expected[phrase])
            assert sum(1 for h in index[phrase]["locations"] if h["article_id"] == "a1") == 2 and len({tuple(h["lines_1based"]) for h in index[phrase]["locations"] if h["article_id"] == "a1"}) == 2

    def test_each_reported_location_is_where_the_text_really_is_and_the_kind_follows_the_lines():
        view = corpus()
        articles = {a["article_id"]: a["text"] for a in view["articles"]}
        _, index = rce.diagnose(view, RULES)
        checked = 0
        for row in index.values():
            for hit in row["locations"]:
                text = articles[hit["article_id"]]
                start, end = hit["raw_span"]
                assert text[start:end] == hit["raw"]  # the raw span cuts exactly the raw text
                assert "".join(ch for ch in hit["raw"] if not ch.isspace()) == hit["normalized"] == row["phrase"]
                first = line_of(text, hit["normalized_span"][0])
                last = line_of(text, hit["normalized_span"][1] - 1)
                assert hit["lines_1based"] == [first, last]  # equals my own line walk
                assert (hit["kind"] == "cross_line") == (first != last)
                assert hit["next_action"] == ACTION[hit["kind"]]
                checked += 1
        assert checked >= 5 * (len(SHARED) - 11)

    def test_a_window_that_crosses_a_line_break_is_cross_line_over_two_lines_and_the_raw_text_keeps_the_break():
        lines = ["共通の前半はここで", "終わり後半が続きます"]
        entries = [entry(i, [f"固有{i * 31337}", *lines, f"結び{i * 7919}"]) for i in range(5)]
        entries[0]["series"] = entries[1]["series"] = "documents"
        summary, index = rce.diagnose({"articles": entries}, RULES)
        crossing = [h for row in index.values() for h in row["locations"] if h["kind"] == "cross_line"]
        assert crossing and all(h["lines_1based"][1] > h["lines_1based"][0] and "\n" in h["raw"] for h in crossing)  # short lines can make a 12-character window span three lines: "more than one line", not "exactly two"
        assert summary["occurrence_kinds"]["cross_line"] == len(crossing)

    def test_the_raw_text_keeps_whitespace_variants_while_the_normalised_text_and_the_gate_ignore_them():
        variants = [SHARED, SHARED[:6] + " " + SHARED[6:], SHARED[:9] + "　" + SHARED[9:], SHARED[:4] + "\t" + SHARED[4:], SHARED[:12] + "  " + SHARED[12:]]
        entries = [entry(i, [f"固有{i * 31337}導入", variants[i], f"固有{i * 7919}結び"]) for i in range(5)]
        entries[0]["series"] = entries[1]["series"] = "documents"
        articles = {a["article_id"]: a["text"] for a in entries}
        summary, index = rce.diagnose({"articles": entries}, RULES)
        assert set(index) == windows(articles) == windows({k: "".join(ch for ch in v if not ch.isspace()) for k, v in articles.items()})
        spaced = [h for row in index.values() for h in row["locations"] if h["article_id"] == "a1" and h["kind"] == "prose" and " " in h["raw"]]
        assert spaced and all(len(h["raw"]) > 12 and len(h["normalized"]) == 12 for h in spaced)

    def test_the_output_contains_only_window_text_never_a_whole_line_or_an_unrelated_line():
        view = corpus()
        summary, index = rce.diagnose(view, RULES)
        dumped = json.dumps({"summary": summary, "windows": index}, ensure_ascii=False)
        assert "秘匿トークン" not in dumped  # a line that takes part in no repeated window never appears
        assert all(len(h["raw"]) <= 12 + 12 for row in index.values() for h in row["locations"])  # a window's raw text is the 12 characters plus the whitespace inside them

    def test_near_duplicate_pairs_are_exactly_the_gate_pairs_and_all_articles_mode_accepts_any_number_of_documents():
        same = "これは全く同じ内容の長い合成の本文です。" * 6
        entries = [entry(i, [same], series="documents") for i in range(5)] + [entry(9, ["全く別の内容の短い合成の文です。" * 3], series="overview")]
        articles = {a["article_id"]: a["text"] for a in entries}
        with pytest.raises(ValueError, match="expected_two_document_drafts"):
            rce.diagnose({"articles": entries}, RULES)  # the old default still demands exactly two document drafts
        summary, _ = rce.diagnose({"articles": entries}, RULES, all_articles=True)
        pairs = {tuple(p["article_ids"]) for p in summary["near_duplicate_pairs"]}
        gate_pairs = {(a, b) for a in articles for b in articles if a < b and checks.find_near_duplicates({a: articles[a], b: articles[b]})}
        assert pairs == gate_pairs and len(pairs) == 10 and all(p["rule"] == "near_duplicate_article" and p["next_action"] == "review_source_backed_differentiation" for p in summary["near_duplicate_pairs"])
        assert not any("a9" in str(p["article_ids"]) or 9 in p["article_ids"] for p in summary["near_duplicate_pairs"])  # the unrelated article is in no pair

    def test_distinct_articles_give_no_near_duplicate_pair():
        summary, _ = rce.diagnose(corpus(), RULES)
        assert summary["near_duplicate_pairs"] == []

    def test_the_diagnostic_refuses_duplicate_ids_and_an_ambiguous_number_of_document_drafts():
        view = corpus()
        view["articles"][3]["article_id"] = view["articles"][2]["article_id"]
        with pytest.raises(ValueError, match="duplicate_article_id"):
            rce.diagnose(view, RULES)
        for count in (0, 1, 3, 4):
            v = corpus(with_documents=False)
            for i in range(count):
                v["articles"][i]["series"] = "documents"
            with pytest.raises(ValueError, match="expected_two_document_drafts"):
                rce.diagnose(v, RULES)
        assert rce.diagnose(corpus(), RULES)[0]["total"] > 0  # exactly two document drafts is accepted

    def test_the_diagnostic_stops_instead_of_reporting_gate_unchanged_when_its_own_count_differs_from_the_gate(monkeypatch):
        """`gate_unchanged: true` is a constant in the summary; what makes it honest is the check before it. If the parity check says the counts differ, `diagnose` must raise (now a RuntimeError), not report."""
        monkeypatch.setattr(rce, "gate_unchanged", lambda articles, rules: False)
        with pytest.raises(RuntimeError, match="diagnostics_diverge_from_gate"):
            rce.diagnose(corpus(), RULES)

    def test_the_diagnostic_stops_when_its_near_duplicate_pairs_differ_from_the_gate(monkeypatch):
        same = "これは全く同じ内容の長い合成の本文です。" * 6
        entries = [entry(i, [same], series="documents") for i in range(3)]
        monkeypatch.setattr(rce, "find_near_duplicates", lambda pair: [] if len(pair) == 2 else ["x"])  # the per-pair calls say "none", the whole-corpus call says "one": they diverge
        with pytest.raises(RuntimeError, match="pair_diagnostics_diverge_from_gate"):
            rce.diagnose({"articles": entries}, RULES, all_articles=True)

    def test_the_diagnostic_never_changes_the_gate_or_its_thresholds_and_registers_no_rule():
        summary, _ = rce.diagnose(corpus(), RULES)
        assert summary["gate_unchanged"] is True and dc.thresholds_are_the_gates() and RULES["lines"] == {}
        source = (WORK / "repeat_context_evidence.py").read_text(encoding="utf-8")
        assert "min_occurrences=" not in source and "phrase_len=" not in source.replace("def diagnose", "")  # no threshold is passed or overridden

    def test_the_command_line_report_marks_every_batch_with_a_window_or_a_pair_as_fail_and_changes_no_gate(tmp_path):
        """`batch_qa` must be FAIL when any window or near-duplicate pair remains, PASS only when there is none: a failing batch is never reported as passing."""
        import subprocess
        def view(entries):
            path = tmp_path / f"v{len(list(tmp_path.glob('v*.json')))}.json"
            path.write_text(json.dumps({"articles": entries}, ensure_ascii=False), encoding="utf-8")
            return path
        clean = view([entry(i, [f"完全に固有の本文その{i}番は{i * 7919}と{i * 104729}です"], series="documents") for i in range(2)])
        dirty = view(corpus()["articles"])
        for base, revised, expected in ((clean, clean, "PASS"), (dirty, dirty, "FAIL"), (clean, dirty, "FAIL")):
            out = tmp_path / f"out-{base.name}-{revised.name}.json"
            env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1")  # the tool imports `src.article_qa`: it is run from the repository with the repository on the path
            done = subprocess.run([sys.executable, str(WORK / "repeat_context_evidence.py"), "--baseline", str(base), "--revised", str(revised), "--output", str(out)], cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8")
            assert done.returncode == 0, done.stderr[-300:]
            report = json.loads(out.read_text(encoding="utf-8"))
            assert report["batch_qa"] == expected and report["gate_or_threshold_changed"] is False and report["registered_rules"] == 0

    def test_known_issue_pr99_a_missing_series_or_text_raises_a_bare_exception_not_a_controlled_refusal():
        """F-M1-G6-02 (informational). `article['series']` / `article['text']` missing raise KeyError; a non-string text raises a bare exception. Nothing is written, but the refusal is not a controlled ValueError like the duplicate-id and document-count refusals."""
        view = corpus()
        del view["articles"][2]["series"]
        with pytest.raises(KeyError):
            rce.diagnose(view, RULES)
        view = corpus()
        view["articles"][2]["text"] = 5
        with pytest.raises(Exception):
            rce.diagnose(view, RULES)
