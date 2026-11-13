"""Independent tests of Work's fictional read-only interview contract candidate (PR #109: `research/inbox/work-fictional-read-contract/read_contract.py`).

Claude-owned QA. DEFINED ONLY when Work's directory exists (absent, not skipped, until PR #109 is merged). SYNTHETIC_ONLY: the contract is a fictional envelope, not an accepted DB/Sandbox interface;
passing these tests accepts nothing. Work's code is imported and called, never edited. `test_known_issue_*` / `test_limit_*` pin a weakness or a stated limit of the current code (they assert the CURRENT behaviour; flip them when fixed). Re-reviewed at head 6a9bda9: P-1 and P-2 are fixed and are now regression tests."""
import importlib.util
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_READ_DIR") or REPO / "research" / "inbox" / "work-fictional-read-contract")

if (WORK / "read_contract.py").exists():
    sys.path.insert(0, str(REPO / "sandbox"))
    from interview_sandbox import guards

    _spec = importlib.util.spec_from_file_location("pr109_read_contract", WORK / "read_contract.py")
    C = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(C)
    BASE = json.loads((WORK / "fictional-snapshot.json").read_text(encoding="utf-8"))
    CONFIRMED = next(i for i, f in enumerate(BASE["official_facts"]) if f["status"] == "confirmed_in_fixture")
    UNKNOWN = next(i for i, f in enumerate(BASE["official_facts"]) if f["status"] == "unknown")

    def mutated(fn):
        d = deepcopy(BASE)
        fn(d)
        return d

    def test_the_fixture_is_valid_and_the_validator_returns_a_copy_not_the_input():
        out = C.validate(BASE)
        assert out == BASE and out is not BASE and out["official_facts"] is not BASE["official_facts"]

    def test_the_preview_is_static_has_no_input_script_or_form_and_escapes_everything():
        html = C.render(BASE)
        assert "<script" not in html.lower() and "<form" not in html.lower() and "<input" not in html.lower() and "<button disabled>" in html and "default-src 'none'" in html
        hostile = mutated(lambda d: d["official_facts"][CONFIRMED].update(label="<script>alert(1)</script>", value="<img src=x onerror=alert(1)>"))
        out = C.render(hostile)
        assert "<script>alert" not in out and "<img src=x" not in out and "&lt;script&gt;" in out

    def test_the_preview_says_it_is_fictional_unconnected_and_not_a_guarantee_and_passes_the_sandbox_guard():
        html = C.render(BASE)
        for phrase in ("架空データの画面試作", "実際の大学・入試・提供サービスではありません", "未接続", "合格可能性は保証しません", "回答・録音・志望理由書は収集しません"):
            assert phrase in html, phrase
        assert guards.forbidden_claims_in(html) == []  # the denial 'not the same as the real interview ... not guaranteed' is allowed (guard fix); an assertion would not be

    @pytest.mark.parametrize("name,fn,error", [
        ("extra_field", lambda d: d.update(user_answer="私の回答"), "unexpected_fields"),
        ("answer_inside_scope", lambda d: d["scope"].update(answer="x"), "unexpected_fields"),
        ("not_fictional", lambda d: d["scope"].update(case_id="real-001"), "fictional_scope_required"),
        ("real_university_label", lambda d: d["scope"].update(university="筑波大学"), "fictional_scope_required"),
        ("not_read_only", lambda d: d.update(read_only=False), "fictional_read_only_required"),
        ("persistence", lambda d: d.update(storage={"session": "disk", "personal_data": True}), "no_personal_persistence"),
        ("payment_enabled", lambda d: d.update(purchase={"price": 1000, "payment_enabled": True}), "no_payment"),
        ("experience_reports_present", lambda d: d.update(experience_state={"status": "available", "count": 3, "consent_scope": "public"}), "experience_not_available"),
        ("cross_case_source", lambda d: d["official_facts"][CONFIRMED]["source"].update(case_id="fiction-other"), "cross_scope_source"),
        ("cross_year_source", lambda d: d["official_facts"][CONFIRMED]["source"].update(entry_year=d["scope"]["entry_year"] + 1), "cross_scope_source"),
        ("cross_stage_source", lambda d: d["official_facts"][CONFIRMED]["source"].update(stage="別の段階"), "cross_scope_source"),
        ("year_as_string", lambda d: d["scope"].update(entry_year=str(d["scope"]["entry_year"])), "invalid_year"),
        ("year_as_bool", lambda d: d["scope"].update(exam_year=True), "invalid_year"),
        ("unknown_with_a_value", lambda d: d["official_facts"][UNKNOWN].update(value="10分"), "unknown_has_no_value_or_source"),
        ("unknown_with_a_source", lambda d: d["official_facts"][UNKNOWN].update(source=deepcopy(BASE["official_facts"][CONFIRMED]["source"])), "unknown_has_no_value_or_source"),
        ("confirmed_with_an_unknown_note", lambda d: d["official_facts"][CONFIRMED].update(unknown_explanation="未確認"), "confirmed_not_unknown"),
        ("bad_source_hash", lambda d: d["official_facts"][CONFIRMED]["source"].update(sha256="Z" * 64), "invalid_source_sha"),
        ("bad_position", lambda d: d["official_facts"][CONFIRMED]["source"].update(normalized_start=9, normalized_end=3), "invalid_position"),
        ("duplicate_fact_id", lambda d: d["official_facts"].append(deepcopy(d["official_facts"][CONFIRMED])), "duplicate_fact_id"),
        ("official_labelled_practice", lambda d: d["practice_material"][0].update(kind="official_fact"), "practice_must_not_be_official"),
        ("practice_grounded_in_unknown", lambda d: d["practice_material"][0].update(basis_fact_ids=[d["official_facts"][UNKNOWN]["fact_id"]]), "unsupported_practice_basis"),
        ("practice_grounded_in_nothing_known", lambda d: d["practice_material"][0].update(basis_fact_ids=["no-such-fact"]), "unsupported_practice_basis"),
    ], ids=lambda x: x if isinstance(x, str) else "")
    def test_every_scope_unknown_or_boundary_violation_is_refused(name, fn, error):
        with pytest.raises(ValueError, match=error):
            C.validate(mutated(fn))

    def test_the_unknown_stays_unknown_in_the_preview_and_is_never_filled_in():
        html = C.render(BASE)
        assert "未確認：" in html and "推測しません" in html
        assert all(BASE["official_facts"][UNKNOWN]["label"] in html for _ in [0])

    # ---- re-review of head 6a9bda9: P-1 / P-2 are fixed, so the former `known_issue` pins are now REGRESSION tests (the same attack input must be refused) ----------------------

    def _facts(d):
        return d["official_facts"]

    def _set_note(text):
        return lambda d: d["unverified_notes"].append(text)

    # every field whose text reaches a screen or an identifier: the guard must run at each boundary, not only at the notes
    FIELD_SETTERS = {
        "fact_label": lambda t: (lambda d: _facts(d)[CONFIRMED].update(label=t)),
        "fact_value": lambda t: (lambda d: _facts(d)[CONFIRMED].update(value=t)),
        "unknown_explanation": lambda t: (lambda d: _facts(d)[UNKNOWN].update(unknown_explanation=t)),
        "practice_text": lambda t: (lambda d: d["practice_material"][0].update(text=t)),
        "unverified_note": lambda t: _set_note(t),
        "department": lambda t: (lambda d: d["scope"].update(department=t)),
        "faculty": lambda t: (lambda d: d["scope"].update(faculty=t)),
        "offering": lambda t: (lambda d: d["scope"].update(offering=t)),
        "method": lambda t: (lambda d: d["scope"].update(method=t)),
        "stage": lambda t: (lambda d: d["scope"].update(stage=t)),
        "fact_id": lambda t: (lambda d: _facts(d)[CONFIRMED].update(fact_id=t)),
        "question_id": lambda t: (lambda d: d["practice_material"][0].update(question_id=t)),
        "source_document_id": lambda t: (lambda d: _facts(d)[CONFIRMED]["source"].update(document_id=t)),
        "source_revision_id": lambda t: (lambda d: _facts(d)[CONFIRMED]["source"].update(revision_id=t)),
    }
    ASSERTED = ["この面接は合格できます", "必ず聞かれる質問です。", "大学公認の対策です", "合格率80%", "合格率は 80% です", "合格率：８０％", "完全に再現した面接", "実際の面接と同じです", "80点満点で採点"]
    CONTACT = ["連絡先 taro@example.invalid", "ｔａｒｏ＠ｅｘａｍｐｌｅ．ｉｎｖａｌｉｄ", "taro(at)example.invalid", "電話 090-0000-0000", "電話０９０－０００００００００", "+81 90 0000 0000",
               "https://example.invalid/x", "ｈｔｔｐｓ：／／example.invalid", "www.example.invalid", "mailto:a@b.invalid", "連絡は @someone まで", "〒100-0000"]

    @pytest.mark.parametrize("field", sorted(FIELD_SETTERS))
    @pytest.mark.parametrize("payload", ASSERTED + CONTACT)
    def test_p1_regression_a_forbidden_claim_contact_or_link_is_refused_at_every_text_boundary(field, payload):
        with pytest.raises(ValueError, match="forbidden_claim_in_snapshot|contact_information_in_snapshot|link_in_snapshot"):
            C.render(mutated(FIELD_SETTERS[field](payload)))

    @pytest.mark.parametrize("payload", ["大学公認ではありません", "合格可能性は保証しません", "実際の面接と同じではありません", "必ず聞かれるとは限りません", "大学公認でもありません"])
    def test_p1_a_denial_of_a_forbidden_claim_is_allowed_in_the_snapshot(payload):
        assert C.validate(mutated(_set_note(payload)))["unverified_notes"][-1] == payload
        assert guards.forbidden_claims_in(C.render(mutated(_set_note(payload)))) == []

    def test_p1_the_contact_and_claim_checks_are_the_unchanged_sandbox_guards_of_this_tree_not_a_copy():
        src = (WORK / "read_contract.py").read_text(encoding="utf-8")
        assert "from interview_sandbox.guards import forbidden_claims_in, has_personal" in src and "re.compile" not in src.split("def text")[0]  # no private copy of the patterns above the text check
        assert guards.forbidden_claims_in("合格率は 80% です") and guards.has_personal("taro(at)example.invalid")

    def test_p1_no_text_that_survives_validation_makes_the_rendered_page_fail_the_sandbox_guard():
        html = C.render(BASE)
        assert guards.forbidden_claims_in(html) == [] and not guards.has_personal(html)

    def test_p2_regression_two_confirmed_facts_under_one_label_with_different_values_are_refused():
        def conflicting(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["value"] = "conflicting-1", "全く異なる値（食い違い）"
            _facts(d).append(f)
        with pytest.raises(ValueError, match="conflicting_confirmed_label"):
            C.validate(mutated(conflicting))

    def test_p2_the_same_value_under_one_label_is_a_corroboration_and_is_allowed():
        def same(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"] = "corroborating-1"
            _facts(d).append(f)
        assert len(C.validate(mutated(same))["official_facts"]) == len(BASE["official_facts"]) + 1

    @pytest.mark.parametrize("decorate", [lambda x: x + " ", lambda x: x + "　", lambda x: "　" + x], ids=["space", "ideographic-space", "leading-ideographic"])
    def test_p2_a_label_that_differs_only_by_whitespace_is_the_same_label(decorate):
        def conflicting(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["value"], f["label"] = "c2", "別の値", decorate(f["label"])
            _facts(d).append(f)
        with pytest.raises(ValueError, match="conflicting_confirmed_label"):
            C.validate(mutated(conflicting))

    def test_p2_a_full_width_spelling_of_a_label_with_ascii_letters_is_the_same_label():
        def go(d):
            _facts(d)[CONFIRMED]["label"] = "Time"
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["label"], f["value"] = "c2", "Ｔｉｍｅ", "別の値"
            _facts(d).append(f)
        with pytest.raises(ValueError, match="conflicting_confirmed_label"):
            C.validate(mutated(go))

    # ---- what stays true of the unknown, the synthetic label and the scope --------------------------------------------------------------------------------------------

    def test_an_unknown_department_is_shown_as_unspecified_and_never_guessed_from_other_fields():
        assert BASE["scope"]["department"] is None
        assert "未指定（推測しません）" in C.render(BASE)
        with pytest.raises(ValueError, match="unknown_department_not_guessed"):
            C.validate(mutated(lambda d: d["scope"].update(department=5)))

    def test_an_unknown_fact_is_rendered_as_unconfirmed_and_its_value_never_appears():
        html = C.render(BASE)
        label = BASE["official_facts"][UNKNOWN]["label"]
        assert "未確認：" in html and label in html
        guessed = mutated(lambda d: d["official_facts"][UNKNOWN].update(value="約10分"))
        with pytest.raises(ValueError, match="unknown_has_no_value_or_source"):
            C.render(guessed)

    def test_a_fictional_official_source_is_never_presented_as_officially_verified():
        html = C.render(BASE)
        assert "実在大学の公式情報ではありません" in html and "架空資料の確認例" in html
        for claim in ("公式サイトで確認", "公式確認済み", "検証済み", "認証済み", "official_site_authenticity"):
            assert claim not in html, claim
        for kind in ("official_source", "collector_verified", "fictional_official_source "):
            with pytest.raises(ValueError, match="fictional_source_required"):
                C.validate(mutated(lambda d, k=kind: _facts(d)[CONFIRMED]["source"].update(source_kind=k)))

    def test_the_preview_does_not_promote_a_synthetic_fact_to_the_authenticity_or_meaning_vocabulary_of_real_evidence():
        out = C.preview(BASE)
        assert out["sandbox_connected"] is False
        assert all(f["status"] in ("confirmed_in_fixture", "unknown") for f in out["official_fixture_facts"])  # never the real 'confirmed' / 'pass' of SOURCE_EVIDENCE_LEVELS

    @pytest.mark.parametrize("key", ["faculty", "method", "offering", "exam_year", "department"])
    def test_limit_a_source_has_no_slot_for_faculty_method_offering_or_exam_year_so_a_source_for_another_one_cannot_be_detected(key):
        """Information (limit, W-3): a source is bound to case_id / entry_year / stage only (those mismatches ARE refused, see the parametrized test above). A confirmed fact whose source belongs to another
        faculty, method, offering or exam year cannot be recognised, because the source carries no such field and extra fields are refused. Flip this test when Work adds the binding."""
        with pytest.raises(ValueError, match="unexpected_fields"):
            C.validate(mutated(lambda d: _facts(d)[CONFIRMED]["source"].update({key: "x"})))

    @pytest.mark.parametrize("contract", ["fictional-interview-read-candidate-v2", "", None, 1])
    def test_a_snapshot_of_another_contract_version_is_refused(contract):
        with pytest.raises(ValueError, match="fictional_read_only_required"):
            C.validate(mutated(lambda d: d.update(contract=contract)))

    @pytest.mark.parametrize("key", ["document_id", "revision_id"])
    def test_a_source_without_a_document_or_revision_identifier_is_refused(key):
        for bad in ("", None, 5):
            with pytest.raises(ValueError, match="invalid_text"):
                C.validate(mutated(lambda d, b=bad: _facts(d)[CONFIRMED]["source"].update({key: b})))

    @pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "g" * 64, "", None])
    def test_a_source_hash_that_is_not_64_lowercase_hex_is_refused(bad):
        with pytest.raises(ValueError, match="invalid_source_sha"):
            C.validate(mutated(lambda d: _facts(d)[CONFIRMED]["source"].update(sha256=bad)))

    # ---- invisible characters and wording the known-pattern guard cannot see (information for Work; the contract states that it is not a semantic detector) ----------

    # ---- P-3 (head 65d316a): Work refuses every Cf character in `text`. The former pin is now a REGRESSION test, and the residue it leaves is pinned as P-3b ----------------

    import unicodedata as _ud

    def _cf(cp):
        return chr(cp)

    # invisible format characters (category Cf) an attacker can put inside a claim, a label, an id or a scope value
    CF_ATTACKS = [0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060, 0x00AD, 0x180E, 0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x2061, 0x2062, 0x2063, 0x2064, 0xE0001, 0xE0020]

    def test_the_attack_list_really_is_category_cf():
        assert all(_ud.category(chr(cp)) == "Cf" for cp in CF_ATTACKS)

    @pytest.mark.parametrize("cp", CF_ATTACKS, ids=lambda cp: f"U+{cp:04X}")
    def test_p3_regression_an_invisible_format_character_splitting_a_forbidden_claim_is_refused(cp):
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(_set_note("合格" + _cf(cp) + "できます")))

    @pytest.mark.parametrize("cp", CF_ATTACKS, ids=lambda cp: f"U+{cp:04X}")
    def test_p3_regression_a_label_split_by_an_invisible_character_cannot_evade_the_conflict_check(cp):
        def split_label(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["value"] = "c2", "別の値"
            f["label"] = f["label"][:1] + _cf(cp) + f["label"][1:]
            _facts(d).append(f)
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(split_label))

    # every boundary where a string reaches the screen or is used as an identifier or a scope value
    P3_BOUNDARIES = {
        "fact_label": lambda t: (lambda d: _facts(d)[CONFIRMED].update(label=t)),
        "fact_value": lambda t: (lambda d: _facts(d)[CONFIRMED].update(value=t)),
        "unknown_explanation": lambda t: (lambda d: _facts(d)[UNKNOWN].update(unknown_explanation=t)),
        "practice_text": lambda t: (lambda d: d["practice_material"][0].update(text=t)),
        "unverified_note": lambda t: _set_note(t),
        "department": lambda t: (lambda d: d["scope"].update(department=t)),
        "faculty": lambda t: (lambda d: d["scope"].update(faculty=t)),
        "method": lambda t: (lambda d: d["scope"].update(method=t)),
        "offering": lambda t: (lambda d: d["scope"].update(offering=t)),
        "stage": lambda t: (lambda d: d["scope"].update(stage=t)),
        "fact_id": lambda t: (lambda d: _facts(d)[CONFIRMED].update(fact_id=t)),
        "question_id": lambda t: (lambda d: d["practice_material"][0].update(question_id=t)),
        "source_document_id": lambda t: (lambda d: _facts(d)[CONFIRMED]["source"].update(document_id=t)),
        "source_revision_id": lambda t: (lambda d: _facts(d)[CONFIRMED]["source"].update(revision_id=t)),
    }

    @pytest.mark.parametrize("field", sorted(P3_BOUNDARIES))
    @pytest.mark.parametrize("cp", [0x200B, 0xFEFF, 0x202E, 0x2066, 0x00AD, 0xE0001], ids=lambda cp: f"U+{cp:04X}")
    def test_p3_regression_the_invisible_character_is_refused_at_every_text_boundary_including_ids_and_scope_values(field, cp):
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(P3_BOUNDARIES[field]("正常な値" + _cf(cp) + "です")))

    def test_p3_the_fixture_and_ordinary_japanese_text_are_not_refused_by_the_cf_rule():
        """The design (refuse every Cf) must not reject normal input: kana, kanji, full-width and half-width forms, the ideographic space, the prolonged sound mark, brackets, numbers, ASCII punctuation."""
        assert not any(_ud.category(c) == "Cf" for s in json.dumps(BASE, ensure_ascii=False) for c in s)
        for ok in ("面接は10分程度です（目安）。", "ＡＩ活用の方針：未確認", "志望理由書の提出　あり", "ひらがなとカタカナ、ｶﾀｶﾅ、ー〜・「」『』〈〉", "Q&A 2027-04 #1 (a/b) 50%"):  # the ideographic-variation-selector sample moved to its own known_issue test (F-M1-G1-01): head 14df2c4 refuses it
            assert not any(_ud.category(c) == "Cf" for c in ok), ok
            assert C.validate(mutated(_set_note(ok)))["unverified_notes"][-1] == ok

    def test_p3_the_refusal_names_the_invisible_character_rule_and_is_checked_before_the_other_guards():
        for payload in ("合格​できます", "連絡先 taro​@example.invalid"):
            with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
                C.validate(mutated(_set_note(payload)))

    # P-3b: what the Cf rule does NOT cover. Characters of other categories are just as invisible and split a claim or a label in the same way.
    # Work's head 14df2c4 ("Close the P3b synthetic invisible-separator regression") refuses variation selectors, the combining grapheme joiner, Hangul fillers and the braille blank, but NOT the line/paragraph
    # separators (Zl, Zp) nor the control characters (Cc): those still split a claim. The first list is FIXED (a regression test now), the second is still a known issue.
    NON_CF_INVISIBLE_FIXED = [0xFE0F, 0xFE00, 0x034F, 0x3164, 0x115F, 0xFFA0, 0x2800]
    NON_CF_INVISIBLE = [0x2028, 0x2029, 0x0001, 0x0008, 0x001F, 0x007F]

    @pytest.mark.parametrize("cp", NON_CF_INVISIBLE_FIXED, ids=lambda cp: f"U+{cp:04X}")
    def test_p3b_resolved_a_non_cf_invisible_character_is_refused_in_a_note_and_in_a_label(cp):
        """P-3b RESOLVED at head 14df2c4 for these code points: "合格<U+FE0F>できます" is refused with `invisible_format_character_in_snapshot`, in a note and in a label (so the label-conflict check cannot be evaded by a split)."""
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(_set_note("合格" + chr(cp) + "できます")))

        def split(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["value"] = "c2", "別の値"
            f["label"] = f["label"][:1] + chr(cp) + f["label"][1:]
            _facts(d).append(f)
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(split))

    def test_known_issue_pr109_p3c_ideographic_variation_selectors_are_refused_although_they_are_legitimate_in_japanese_text():
        """F-M1-G1-01 (minor, a consequence of the P-3b fix). The new deny list includes U+E0100–U+E01EF (ideographic variation selectors, category Mn) and U+FE00–U+FE0F. "辻<U+E0100>" is a valid ideographic variation sequence that real
        Japanese text uses (variant forms of kanji in names and places); it is now refused as `invisible_format_character_in_snapshot`, and so is an emoji presentation selector. For a fictional fixture a conservative deny list is fine; before a
        real official source is connected the list needs a decision: refuse a variation selector only where it does not follow a CJK ideograph (the split attacks put it between kana), or state that variant forms are out of scope. Pinned; flip when decided."""
        with pytest.raises(ValueError, match="invisible_format_character_in_snapshot"):
            C.validate(mutated(_set_note("辻" + chr(0xE0100) + "（異体字セレクタを含む表記）")))

    @pytest.mark.parametrize("cp", NON_CF_INVISIBLE, ids=lambda cp: f"U+{cp:04X}")
    def test_known_issue_pr109_p3b_a_non_cf_invisible_character_still_splits_a_forbidden_claim(cp):
        """PR #109 finding P-3b (warning, found by this re-review of 65d316a): the Cf rule leaves variation selectors (Mn, 259 code points), the combining grapheme joiner, Hangul fillers (Lo), the braille blank
        (So), the line and paragraph separators (Zl, Zp) and the control characters (Cc) outside. "合格<U+FE0F>できます" is accepted: the Sandbox guard does not match the split text and the label check sees a different label.
        Expected after the fix: check a SKELETON (drop Cf, Cc, Zs/Zl/Zp, variation selectors, fillers and the braille blank, then NFKC) for forbidden claims, contact data and label identity, or refuse these
        categories as well. Flip this test when fixed. (Plain spacing, "合 格 で き ま す", is the same class and is listed as a limit above.)"""
        d = C.validate(mutated(_set_note("合格" + chr(cp) + "できます")))
        assert d["unverified_notes"][-1] == "合格" + chr(cp) + "できます"
        assert guards.forbidden_claims_in(C.render(mutated(_set_note("合格" + chr(cp) + "できます")))) == []  # the guard does not see the claim in the rendered page either

    @pytest.mark.parametrize("cp", [0x2028, 0x2029, 0x0001, 0x007F], ids=lambda cp: f"U+{cp:04X}")
    def test_known_issue_pr109_p3b_the_same_split_with_a_separator_or_a_control_character_still_evades_the_label_conflict_check(cp):
        """The label split with a variation selector is refused now (see the resolved test above); a split with a line separator or a control character is still accepted."""
        def split(d):
            f = deepcopy(_facts(d)[CONFIRMED])
            f["fact_id"], f["value"] = "c2", "別の値"
            f["label"] = f["label"][:1] + chr(cp) + f["label"][1:]
            _facts(d).append(f)
        assert len(C.validate(mutated(split))["official_facts"]) == len(BASE["official_facts"]) + 1

    def test_limit_wording_outside_the_known_patterns_passes_by_design():
        """Information (limit, stated by Work in P1_P2_FOLLOWUP.md): paraphrases ("合格は確実です"), hiragana ("ごうかくできます"), spaced letters, a person's name, a messenger ID and a guessed number in an
        explanation of an unknown ("10分程度と推測されます") are not detected. These are for human review before a real source is ever connected; they are listed so that nobody reads the guard as a
        semantic check. Flip any of them when a stronger check is agreed."""
        for text in ("合格は確実です", "ごうかくできます", "合 格 で き ま す", "山田太郎さんの体験談", "LINE: abc123"):
            assert C.validate(mutated(_set_note(text)))["unverified_notes"][-1] == text
        guess = C.validate(mutated(lambda d: _facts(d)[UNKNOWN].update(unknown_explanation="10分程度と推測されます")))
        assert "10分程度" in C.render(guess)  # an unknown can still be 'explained' with a number: nothing in the contract forbids it (W-4)

    def test_a_confirmed_and_an_unknown_fact_under_one_label_are_both_accepted_today():
        """Information (W-5): the conflict check compares confirmed facts only; a label that is confirmed in one entry and unknown in another is shown twice. Not a defect while the fixture is read by a person,
        but the future real-source contract has to say which one wins."""
        def go(d):
            _facts(d).append({"fact_id": "u2", "label": _facts(d)[CONFIRMED]["label"], "value": None, "status": "unknown", "source": None, "unknown_explanation": "未確認"})
        assert len(C.validate(mutated(go))["official_facts"]) == len(BASE["official_facts"]) + 1

    # ---- compatibility with the Sandbox (rubric v1.2 and the guards) ---------------------------------------------------------------------------------------------------

    def _context_from(snapshot, categories=("志望理由", "これまでの活動", "学びたいこと")):
        """An adapter written for this test, not part of Work's code. It exposes two gaps of the candidate: the snapshot has no question `category` (so the adapter has to supply one) and it carries
        both `entry_year` and `exam_year` while the Sandbox has one `fiscal_year` (so the adapter has to choose)."""
        from interview_sandbox.models import InterviewContext, OfficialFact, PracticeQuestion, SessionPlan
        s = snapshot["scope"]
        facts = tuple(OfficialFact(f["fact_id"], f["label"], f["value"], "confirmed" if f["status"] == "confirmed_in_fixture" else "unknown",
                                   (f["source"]["document_id"] + "@" + f["source"]["revision_id"]) if f["source"] else "-") for f in snapshot["official_facts"])
        qs = tuple(PracticeQuestion(q["question_id"], categories[i % len(categories)], q["text"], tuple(q["basis_fact_ids"])) for i, q in enumerate(snapshot["practice_material"]))
        return InterviewContext(s["case_id"], s["university"], s["faculty"], s["method"], s["entry_year"], facts, (), qs, SessionPlan(categories[:1], 300), True)

    def test_the_validated_snapshot_can_drive_a_sandbox_session_and_keeps_the_four_kinds_apart():
        from interview_sandbox.engine import InterviewSession
        from interview_sandbox.feedback import RUBRIC_VERSION
        ctx = _context_from(C.validate(BASE))
        session = InterviewSession(ctx)
        first = session.start()
        assert first.origin == "ai_practice_material" and "架空" in ctx.university
        briefing = session.briefing().text()
        assert BASE["official_facts"][UNKNOWN]["label"] in briefing  # the unknown is listed as unknown, not dropped
        result = session.answer(first.turn_id, "高校の探究活動で地域の課題を調べました。担当は聞き取りでした。", 40)
        assert result.accepted
        if not result.ended:
            session.end("user")
        report = session.feedback()
        assert report.rubric_version == RUBRIC_VERSION == "practice-rubric-v1.2" and report.case_id == ctx.case_id
        for t in [briefing] + [x.text for x in session.turns if x.role == "interviewer"]:
            assert guards.forbidden_claims_in(t) == [] and not guards.has_personal(t)

    def test_a_snapshot_with_zero_experience_reports_yields_a_context_without_any_experience_report():
        ctx = _context_from(C.validate(BASE))
        assert ctx.experience_reports == () and C.validate(BASE)["experience_state"]["count"] == 0

    def test_the_sandbox_still_refuses_an_assertion_that_a_future_snapshot_field_might_carry():
        from interview_sandbox.models import PracticeQuestion
        from interview_sandbox.guards import assert_clean
        with pytest.raises(ValueError):
            assert_clean("この面接は合格できます")

    # ---- no persistence, no communication ---------------------------------------------------------------------------------------------------------------------------

    def test_validate_preview_and_render_do_no_network_database_or_file_writing(monkeypatch, tmp_path):
        import builtins
        import io
        import socket
        import sqlite3
        import urllib.request

        def boom(*a, **k):
            raise AssertionError("forbidden I/O in a read-only preview")
        real_open = io.open

        def guarded_open(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                boom()
            return real_open(file, mode, *a, **k)
        for target, name in ((socket, "socket"), (socket, "create_connection"), (socket, "getaddrinfo"), (sqlite3, "connect"), (urllib.request, "urlopen"), (io, "open"), (builtins, "open")):
            monkeypatch.setattr(target, name, guarded_open if name == "open" else boom)
        monkeypatch.chdir(tmp_path)
        C.validate(BASE)
        C.preview(BASE)
        C.render(BASE)
        assert list(tmp_path.iterdir()) == []

    def test_the_command_line_writes_only_the_one_new_output_file_and_refuses_to_overwrite(tmp_path):
        import subprocess
        out = tmp_path / "preview.html"
        cmd = [sys.executable, "-X", "utf8", str(WORK / "read_contract.py"), "--input", str(WORK / "fictional-snapshot.json"), "--output", str(out)]
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        first = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp_path)
        assert first.returncode == 0 and sorted(p.name for p in tmp_path.iterdir()) == ["preview.html"] and out.read_text(encoding="utf-8") == C.render(BASE)
        again = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp_path)
        assert again.returncode != 0 and "new_output_file_required" in again.stderr and out.read_text(encoding="utf-8") == C.render(BASE)

    def test_the_command_line_writes_nothing_for_an_unsafe_snapshot(tmp_path):
        import subprocess
        bad = mutated(_set_note("連絡先 taro@example.invalid"))
        src = tmp_path / "in.json"
        src.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "out.html"
        done = subprocess.run([sys.executable, "-X", "utf8", str(WORK / "read_contract.py"), "--input", str(src), "--output", str(out)], capture_output=True, text=True,
                              env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"), cwd=tmp_path)
        assert done.returncode != 0 and "contact_information_in_snapshot" in done.stderr and not out.exists()

    def test_the_rendered_page_contains_no_external_reference_and_is_byte_stable():
        html = C.render(BASE)
        assert not re.search(r'\b(?:src|href|action|srcset|poster)\s*=', html, re.I) and "url(" not in html.lower() and "@import" not in html.lower()
        assert C.render(BASE) == html and C.render(deepcopy(BASE)) == html

    def test_the_candidate_is_labelled_as_a_candidate_not_an_accepted_interface():
        text = (WORK / "README.md").read_text(encoding="utf-8")
        assert "NOT a DB/Sandbox accepted interface" in text and "Claude owns contract acceptance" in text
        assert C.preview(BASE)["sandbox_connected"] is False and C.preview(BASE)["contract_candidate"] == C.VERSION
