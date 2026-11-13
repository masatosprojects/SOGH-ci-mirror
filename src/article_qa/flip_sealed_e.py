"""Sealed evaluation set E for meaning flips — written BEFORE it was ever run, never to be tuned on.

Protocol (same as D, see flip_sealed.py): E is committed first, measured as NUMBERS on the code that exists at that
moment, and its numbers are recorded in docs/WORK_RESUME_HANDOFF.md. No rule, lexicon word or pattern may be added in
order to move E. Its undetected examples are read only to REPORT them; a later change made with E in view must say so
and E is then spent (and a new set F is written). The wordings are new: none of A, B, C, D is reused, and they are
written as a different phrasing of the same wrong meaning (a person who has never seen the lexicons would write them).

Same tuple format as `flip_sweep.FLIPS`: (id, family, regex in the draft, replacement, label).
"""
from __future__ import annotations

FLIPS_SEALED_E: list[tuple[str, str, str, str, str]] = [
    ("e_need_none_to_prerequisite_for_entry", "polarity", "必要としない", "出願の条件に含める", "「必要としない」→「出願の条件に含める」"),
    ("e_need_none_to_must_hold", "polarity", "必要としない", "保持していることを求める", "「必要としない」→「保持していることを求める」"),
    ("e_unneeded_to_expected", "polarity", "不要", "期待されます", "「不要」→「期待されます」"),
    ("e_unneeded_to_assumed", "polarity", "不要", "を前提とします", "「不要」→「を前提とします」"),
    ("e_exempt_to_applies_to_all", "polarity", "免除", "を全員に適用", "「免除」→「を全員に適用」"),
    ("e_exempt_to_still_due", "polarity", "免除", "は引き続き必要", "「免除」→「は引き続き必要」"),
    ("e_allowed_to_banned", "polarity", "認められています", "認めない扱いです", "「認められています」→「認めない扱いです」"),
    ("e_allowed_to_unavailable", "polarity", "認められています", "利用できない運用です", "「認められています」→「利用できない運用です」"),
    ("e_needed_to_waived", "polarity", "必要です", "見なくて差し支えありません", "「必要です」→「見なくて差し支えありません」"),
    ("e_needed_to_discretionary", "polarity", "必要です", "各自の判断に任されています", "「必要です」→「各自の判断に任されています」"),
    ("e_needed_to_irrelevant", "polarity", "必要です", "考慮されません", "「必要です」→「考慮されません」"),
    ("e_needed_to_voluntary", "polarity", "必要です", "希望者のみ行います", "「必要です」→「希望者のみ行います」"),
    ("e_visit_no_to_walk_in", "exception", "持参はできません", "窓口まで持って来られます", "「持参はできません」→「窓口まで持って来られます」"),
    ("e_visit_no_to_bring", "exception", "持参はできません", "本人が持参しても結構です", "「持参はできません」→「本人が持参しても結構です」"),
    ("e_visit_not_accepted_to_hand_in", "exception", "持参は受け付けません", "直接お持ちいただけます", "「持参は受け付けません」→「直接お持ちいただけます」"),
    ("e_extension_to_firm_end", "exception", "延長する場合があるため", "延長の予定はないため", "「延長する場合がある」→「延長の予定はない」"),
    ("e_extension_to_no_change", "exception", "延長する場合があるため", "変更されることはないため", "「延長する場合がある」→「変更されることはない」"),
    ("e_hedge_to_assured", "hedge", "場合があります", "と決まっています", "「場合があります」→「と決まっています」"),
    ("e_hedge_to_always", "hedge", "場合があります", "のが常です", "「場合があります」→「のが常です」"),
    ("e_hedge_b_to_standard", "hedge", "場合もあります", "のが標準です", "「場合もあります」→「のが標準です」"),
    ("e_any_to_both_required", "logic", "いずれか", "両者とも", "「いずれか」→「両者とも」"),
    ("e_any_to_the_whole_set", "logic", "いずれか", "一式すべて", "「いずれか」→「一式すべて」"),
    ("e_applicable_to_meet_all", "logic", "のいずれかに該当する", "のどれにも当てはまる", "「のいずれかに該当」→「のどれにも当てはまる」"),
    ("e_limit_to_without_condition", "limit", "に限り、", "という条件なしに、", "「〜に限り」→「〜という条件なしに」"),
    ("e_limit_to_for_everyone", "limit", "に限り、", "でも誰でも、", "「〜に限り」→「〜でも誰でも」"),
    ("e_caveat_to_closed", "caveat", "別途必要です", "不要となっています", "注意書き「別途必要です」→「不要となっています」"),
    ("e_caveat_to_settled", "caveat", "別途必要です", "解決しています", "注意書き「別途必要です」→「解決しています」"),
    ("e_caveat_to_done_already", "caveat", "別途必要です", "実施済みです", "注意書き「別途必要です」→「実施済みです」"),
    ("e_caveat_confirm_to_skip", "caveat", "別途確認が必要です", "確認を省けます", "注意書き「別途確認が必要です」→「確認を省けます」"),
]
