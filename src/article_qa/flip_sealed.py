"""Sealed evaluation set D for meaning flips (Issue #9 follow-up, "generalisation to unseen wordings").

Protocol — what makes the number a generalisation estimate:
* D was written BEFORE any rule was changed for it and is committed first (see git history).
* D is measured on the code before and after the improvement, as NUMBERS (by family). Its undetected examples are
  read once, at the end, to be reported — never to write a rule. After that D is spent: a later change that is
  tuned with D in view must say so and cannot call D independent.
* Rules and lexicons are improved on the DEVELOPMENT sets only: `FLIPS`, `FLIPS_HELD_OUT`, `_B`, `_C`
  (all now contaminated by design; C was independent only until its survivors were used).
* False positives are measured separately, on every real draft (they must stay at zero).

Same tuple format as `flip_sweep.FLIPS`: (id, family, regex in the draft, replacement, label).
"""
from __future__ import annotations

FLIPS_SEALED_D: list[tuple[str, str, str, str, str]] = [
    ("d_need_none_to_prerequisite", "polarity", "必要としない", "前提条件とする", "「必要としない」→「前提条件とする」"),
    ("d_need_none_to_compulsory", "polarity", "必要としない", "強制する", "「必要としない」→「強制する」"),
    ("d_unneeded_to_prerequisite", "polarity", "不要", "前提となります", "「不要」→「前提となります」"),
    ("d_unneeded_to_indispensable", "polarity", "不要", "不可欠です", "「不要」→「不可欠です」"),
    ("d_exempt_to_included", "polarity", "免除", "の対象に含まれます", "「免除」→「の対象に含まれます」"),
    ("d_exempt_to_binding", "polarity", "免除", "を必ず行う", "「免除」→「を必ず行う」"),
    ("d_allowed_to_forbidden", "polarity", "認められています", "禁じられています", "「認められています」→「禁じられています」"),
    ("d_allowed_to_declined", "polarity", "認められています", "断られています", "「認められています」→「断られています」"),
    ("d_needed_to_unasked", "polarity", "必要です", "問われません", "「必要です」→「問われません」"),
    ("d_needed_to_skippable", "polarity", "必要です", "省略できます", "「必要です」→「省略できます」"),
    ("d_needed_to_out_of_scope", "polarity", "必要です", "対象外です", "「必要です」→「対象外です」"),
    ("d_needed_to_not_applicable", "polarity", "必要です", "該当しません", "「必要です」→「該当しません」"),
    ("d_visit_no_to_direct", "exception", "持参はできません", "直接持ち込めます", "「持参はできません」→「直接持ち込めます」"),
    ("d_visit_no_to_accepted", "exception", "持参はできません", "持参も受け付けています", "「持参はできません」→「持参も受け付けています」"),
    ("d_visit_not_accepted_to_handover", "exception", "持参は受け付けません", "手渡しで提出できます", "「持参は受け付けません」→「手渡しで提出できます」"),
    ("d_extension_to_never", "exception", "延長する場合があるため", "延長はありえないため", "「延長する場合がある」→「延長はありえない」"),
    ("d_extension_to_not_happen", "exception", "延長する場合があるため", "延長されることはないため", "「延長する場合がある」→「延長されることはない」"),
    ("d_hedge_to_principle", "hedge", "場合があります", "のが原則です", "「場合があります」→「のが原則です」"),
    ("d_hedge_to_usual", "hedge", "場合があります", "のが通例です", "「場合があります」→「のが通例です」"),
    ("d_hedge_b_to_normal", "hedge", "場合もあります", "のが普通です", "「場合もあります」→「のが普通です」"),
    ("d_any_to_both_sides", "logic", "いずれか", "双方", "「いずれか」→「双方」"),
    ("d_any_to_two", "logic", "いずれか", "二つとも", "「いずれか」→「二つとも」"),
    ("d_applicable_to_all_of", "logic", "のいずれかに該当する", "のすべてに該当する", "「のいずれかに該当」→「のすべてに該当」"),
    ("d_limit_to_regardless", "limit", "に限り、", "を問わず、", "「〜に限り」→「〜を問わず」"),
    ("d_limit_to_whenever", "limit", "に限り、", "のときはいつでも、", "「〜に限り」→「〜のときはいつでも」"),
    ("d_caveat_to_not_needed_now", "caveat", "別途必要です", "不要になりました", "注意書き「別途必要です」→「不要になりました」"),
    ("d_caveat_to_omitted", "caveat", "別途必要です", "は省略されます", "注意書き「別途必要です」→「は省略されます」"),
    ("d_caveat_to_complete", "caveat", "別途必要です", "は完了しています", "注意書き「別途必要です」→「は完了しています」"),
    ("d_caveat_confirm_to_unneeded", "caveat", "別途確認が必要です", "確認しなくて構いません", "注意書き「別途確認が必要です」→「確認しなくて構いません」"),
]
