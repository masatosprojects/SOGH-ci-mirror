"""Independent mutation tests of Work's H-1 fix (PR #99, head 64c06db: `candidate_e2e.verify_unaffected`): the articles that an update must NOT change are compared, field by field,
with a snapshot frozen BEFORE generation, against the export read back from disk.

Claude-owned QA. DEFINED ONLY when Work's directory exists (absent, not skipped, until PR #99 is merged). SYNTHETIC_ONLY: invented articles. The first review (head f062fdd) found that the former
check could not fail (it compared the export with objects it had been built from); the old finding is now a regression test: every kind of tampering below must be refused, and a harmless
re-ordering must not be. Work's code is imported and called, never edited."""
import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("SOGH_WORK_G6_DIR") or REPO / "research" / "inbox" / "work-g6-candidate-e2e")

if (WORK / "candidate_e2e.py").exists():
    _spec = importlib.util.spec_from_file_location("pr99_driver", WORK / "candidate_e2e.py")
    D = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(D)

    def articles():
        return [{"article_id": f"case-{k}:overview:{k}", "base_article_id": f"case-{k}:overview:{k}", "case_id": f"case-{k}", "series": "overview", "title": f"記事{k}", "text": f"本文{k}［EV-{k}］。",
                 "evidence_ids": [f"EV-{k}"], "publish_allowed": False, "meta": {"n": k, "flag": False, "ratio": 0.5}} for k in "abcde"]

    def run(mutate=None, replace=("c",)):
        original = articles()
        snapshot = D.article_snapshot(original)  # frozen before "generation"
        exported = deepcopy(original)
        replacements = {}
        for k in replace:  # the affected articles are replaced by revisions with new ids
            old_id = f"case-{k}:overview:{k}"
            i = next(n for n, a in enumerate(exported) if a["article_id"] == old_id)
            exported[i] = dict(exported[i], article_id=old_id + ":revision:r1", parent_article_id=old_id, text="改訂された本文")
            replacements[old_id] = old_id + ":revision:r1"
        if mutate:
            mutate(exported, original)
        return D.verify_unaffected(snapshot, json.loads(json.dumps(exported)), replacements)

    def test_an_export_that_differs_only_in_the_replaced_articles_passes():
        assert run() is True

    def test_a_harmless_reordering_of_the_array_is_not_a_false_alarm():
        assert run(lambda ex, o: ex.reverse()) is True
        assert run(lambda ex, o: ex.insert(0, ex.pop())) is True

    @pytest.mark.parametrize("name,mutate", [
        ("text", lambda ex, o: ex[0].update(text=ex[0]["text"] + "。")),
        ("title", lambda ex, o: ex[1].update(title="別の題")),
        ("metadata_value", lambda ex, o: ex[0]["meta"].update(n=99)),
        ("metadata_bool_to_int", lambda ex, o: ex[0]["meta"].update(flag=0)),
        ("metadata_int_to_float", lambda ex, o: ex[0]["meta"].update(n=1.0)),
        ("metadata_key_added", lambda ex, o: ex[0]["meta"].update(extra=1)),
        ("metadata_key_removed", lambda ex, o: ex[0]["meta"].pop("ratio")),
        ("evidence_version", lambda ex, o: ex[0].update(evidence_ids=["EV-a2"])),
        ("publish_allowed", lambda ex, o: ex[0].update(publish_allowed=True)),
        ("publish_allowed_type", lambda ex, o: ex[0].update(publish_allowed=0)),
        ("field_added", lambda ex, o: ex[3].update(note="x")),
        ("field_removed", lambda ex, o: ex[3].pop("series")),
        ("unicode_lookalike", lambda ex, o: ex[0].update(text=ex[0]["text"].replace("本", "夲"))),
    ], ids=lambda x: x if isinstance(x, str) else "")
    def test_any_change_to_an_unaffected_article_is_refused(name, mutate):
        with pytest.raises(ValueError, match="unaffected_article_changed|unexpected_article_id_set"):
            run(mutate)

    def test_an_unaffected_article_whose_id_changed_is_refused():
        with pytest.raises(ValueError, match="unexpected_article_id_set"):
            run(lambda ex, o: ex[0].update(article_id="case-a:overview:a:revision:x"))

    def test_a_missing_an_extra_and_a_duplicated_article_are_refused():
        with pytest.raises(ValueError, match="unexpected_article_id_set"):
            run(lambda ex, o: ex.pop(0))
        with pytest.raises(ValueError, match="unexpected_article_id_set"):
            run(lambda ex, o: ex.append(dict(ex[0], article_id="case-z:overview:z")))
        with pytest.raises(ValueError, match="duplicate_article_id"):
            run(lambda ex, o: ex.append(deepcopy(ex[0])))

    def test_a_replacement_that_reuses_the_id_of_an_unaffected_article_is_refused():
        original = articles()
        snapshot = D.article_snapshot(original)
        exported = deepcopy(original)
        with pytest.raises(ValueError, match="unexpected_article_id_set"):
            D.verify_unaffected(snapshot, exported, {"case-c:overview:c": "case-a:overview:a"})  # the new id collides with an existing one

    def test_a_replacement_of_an_article_that_never_existed_is_refused():
        original = articles()
        with pytest.raises(ValueError, match="unknown_replacement_parent"):
            D.verify_unaffected(D.article_snapshot(original), deepcopy(original), {"case-zz:overview:zz": "case-zz:overview:zz:revision:r1"})

    def test_two_replacements_with_the_same_new_id_are_refused():
        original = articles()
        with pytest.raises(ValueError, match="unexpected_article_id_set"):
            D.verify_unaffected(D.article_snapshot(original), deepcopy(original), {"case-b:overview:b": "x", "case-c:overview:c": "x"})

    def test_mutating_the_original_objects_after_the_snapshot_cannot_hide_a_difference():
        """The snapshot is a frozen JSON string: changing the live objects later (as a buggy generator might) makes the export differ from the frozen text, not equal to the mutated objects."""
        original = articles()
        snapshot = D.article_snapshot(original)
        exported = deepcopy(original)
        original[0]["text"] = "mutated afterwards"
        exported[0]["text"] = "mutated afterwards"  # export and live object agree with each other, but not with the frozen snapshot
        with pytest.raises(ValueError, match="unaffected_article_changed"):
            D.verify_unaffected(snapshot, exported, {})

    def test_a_non_finite_number_cannot_be_snapshotted():
        with pytest.raises(ValueError):
            D.article_snapshot([{"article_id": "a", "x": float("nan")}])

    # ---- H-2 (path separation, head 9a5d467): the QA body is the generated body; the synthetic warning is added only for display -------------------------------------

    def test_h2_the_base_body_reaches_the_generator_unchanged_and_only_the_root_id_is_normalised():
        article = dict(articles()[0], article_id="case-a:overview:a:revision:r0", base_article_id="case-a:overview:a")
        base = D.revision_base(article)
        assert base["text"] == article["text"] and base["article_id"] == "case-a:overview:a" and article["article_id"].endswith(":revision:r0")  # the input was not mutated

    def test_h2_the_display_helper_adds_the_warning_to_a_copy_for_synthetic_unpublished_drafts_only():
        draft = dict(articles()[0], synthetic_only=True, publish_allowed=False)
        shown = D.display_draft(draft)
        assert shown.startswith(D.BANNER) and shown.endswith(draft["text"]) and draft["text"] == "本文a［EV-a］。"  # the QA body is untouched
        for bad in (dict(draft, synthetic_only=False), {k: v for k, v in draft.items() if k != "synthetic_only"}, dict(draft, publish_allowed=True), {k: v for k, v in draft.items() if k != "publish_allowed"}):
            with pytest.raises(ValueError, match="synthetic_unpublished_display_only"):
                D.display_draft(bad)

    def test_h2_this_separation_removes_one_path_difference_it_does_not_make_the_run_a_real_update():
        """H-2 still needs a REAL live official input, an accepted source meaning/scope, a global QA that passes under an agreed contract, approval, and interruption/concurrency evidence
        (docs/G6_QA_ROOT_CAUSE_AND_REAL_UPDATE_CONDITIONS.md). The driver still builds its source from a synthetic fixture and says so."""
        source = (WORK / "candidate_e2e.py").read_text(encoding="utf-8")
        assert "synthetic.invalid" in source and "'real_official_update':False" in source.replace('"', "'") and "finalize" not in source.split("def main")[1].replace("finalize_called", "")