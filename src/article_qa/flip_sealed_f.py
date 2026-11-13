"""Sealed evaluation set F for meaning flips — written BEFORE any rule is changed for D/E/F, never to be tuned on.

Why F exists: D and E were read (their undetected examples were reported), so a rule written after reading them is
tuned with them in view. They are DEVELOPMENT sets from now on. F is committed first, measured as numbers before and after
the improvement, and its undetected examples are read once, at the end, only to be reported. Wordings are new (none of A-E).

Same tuple format as `flip_sweep.FLIPS`: (id, family, regex in the draft, replacement, label).
"""
from __future__ import annotations

FLIPS_SEALED_F: list[tuple[str, str, str, str, str]] = [
    ("f_need_none_to_binding", "polarity", "必要としない", "拘束力のある要件とする", "「必要としない」→「拘束力のある要件とする」"),
    ("f_need_none_to_obliged", "polarity", "必要としない", "提出する責任を負う", "「必要としない」→「提出する責任を負う」"),
    ("f_unneeded_to_imperative", "polarity", "不要", "を欠かすことはできません", "「不要」→「を欠かすことはできません」"),
    ("f_unneeded_to_mandatory_item", "polarity", "不要", "は必ず確認される項目です", "「不要」→「は必ず確認される項目です」"),
    ("f_exempt_to_checked", "polarity", "免除", "を確認します", "「免除」→「を確認します」"),
    ("f_exempt_to_required_again", "polarity", "免除", "には再度の提出が伴います", "「免除」→「には再度の提出が伴います」"),
    ("f_allowed_to_not_in_scope", "polarity", "認められています", "の範囲外とされています", "「認められています」→「の範囲外とされています」"),
    ("f_allowed_to_refused", "polarity", "認められています", "拒まれています", "「認められています」→「拒まれています」"),
    ("f_needed_to_not_checked", "polarity", "必要です", "確認の対象ではありません", "「必要です」→「確認の対象ではありません」"),
    ("f_needed_to_left_to_you", "polarity", "必要です", "ご自身でお決めください", "「必要です」→「ご自身でお決めください」"),
    ("f_needed_to_not_part", "polarity", "必要です", "には含まれません", "「必要です」→「には含まれません」"),
    ("f_needed_to_as_wished", "polarity", "必要です", "お好みで構いません", "「必要です」→「お好みで構いません」"),
    ("f_visit_no_to_welcome_in_person", "exception", "持参はできません", "直接のご提出を歓迎します", "「持参はできません」→「直接のご提出を歓迎します」"),
    ("f_visit_no_to_front_desk", "exception", "持参はできません", "事務室でも預かります", "「持参はできません」→「事務室でも預かります」"),
    ("f_visit_not_accepted_to_taken", "exception", "持参は受け付けません", "持参分も預かります", "「持参は受け付けません」→「持参分も預かります」"),
    ("f_extension_to_never_moved", "exception", "延長する場合があるため", "終了時刻が動くことはないため", "「延長する場合がある」→「終了時刻が動くことはない」"),
    ("f_extension_to_strictly", "exception", "延長する場合があるため", "厳守されるため", "「延長する場合がある」→「厳守される」"),
    ("f_hedge_to_practice", "hedge", "場合があります", "のが実情です", "「場合があります」→「のが実情です」"),
    ("f_hedge_to_unvarying", "hedge", "場合があります", "と例外なく定められています", "「場合があります」→「と例外なく定められています」"),
    ("f_hedge_b_to_rule", "hedge", "場合もあります", "ことになります", "「場合もあります」→「ことになります」"),
    ("f_any_to_together", "logic", "いずれか", "そろって", "「いずれか」→「そろって」"),
    ("f_any_to_in_full", "logic", "いずれか", "漏れなく全部", "「いずれか」→「漏れなく全部」"),
    ("f_applicable_to_fulfil_each", "logic", "のいずれかに該当する", "のそれぞれを満たす", "「のいずれかに該当」→「のそれぞれを満たす」"),
    ("f_limit_to_general_case", "limit", "に限り、", "のほか広く、", "「〜に限り」→「〜のほか広く」"),
    ("f_limit_to_in_any_case", "limit", "に限り、", "いずれの場合も、", "「〜に限り」→「〜いずれの場合も」"),
    ("f_caveat_to_nothing_left", "caveat", "別途必要です", "残っていません", "注意書き「別途必要です」→「残っていません」"),
    ("f_caveat_to_unneeded_now", "caveat", "別途必要です", "はもう要りません", "注意書き「別途必要です」→「はもう要りません」"),
    ("f_caveat_to_covered", "caveat", "別途必要です", "は網羅されています", "注意書き「別途必要です」→「は網羅されています」"),
    ("f_caveat_confirm_to_ignore", "caveat", "別途確認が必要です", "気にする必要はありません", "注意書き「別途確認が必要です」→「気にする必要はありません」"),
]
