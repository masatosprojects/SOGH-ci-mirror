"""Practice feedback: stages (not scores) against a practice rubric, each tied to the exact place in the person's own answer, with a concrete improvement example and the limits.

The rubric is a practice aid, not an official or university marking. The stage of an item is computed from simple, visible rules, so the same answers always give the same feedback (a real AI
evaluator would vary; that is stated). An improvement example only reshapes the person's own words and leaves visible blanks for facts: it never invents an experience, a number or an official fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import guards
from .engine import ACTIVITY, REASON, VAGUE, InterviewSession, analysable

RUBRIC_VERSION = "practice-rubric-v1.2"  # v1.1: a short first sentence made only of broad words is no longer "clear". v1.2: a number does not rescue it, an absolute word ("必ず") caps it too
ABSOLUTE = ("絶対", "必ず", "間違いなく", "完璧", "確実に", "100%", "100％", "１００％")  # a bare assertion of certainty: this tool cannot tell whether it is true, and does not rate it as "clear"
WITHHELD = "（この部分は、この練習ツールが言ってはいけない種類の断定を含むため、引用していません）"
STAGES = ("要改善", "一部できている", "できている")  # ordered: a retry is compared by this order
NOT_ENOUGH = "判定できません（回答が足りません）"
LIMITS = (
    "これは練習用のルーブリック（版 " + RUBRIC_VERSION + "）です。大学の公式の採点ではなく、大学公認でもありません。",
    "段階は、この練習の中の回答の書き方についての目安です。合格・不合格や、実際の面接との一致を示すものではありません。",
    "このモックは同じ回答なら同じ結果を返します。実際の AI や人の評価は、同じ回答でも揺れることがあります。",
)


@dataclass(frozen=True)
class Evidence:
    turn_id: str
    start: int
    end: int
    text: str  # the person's own words (personal details masked); `truncated` says that the sentence continues
    truncated: bool = False
    redacted: bool = False  # True: the words contain a claim this tool must never make, so they are not repeated; start/end still say where they are in the answer


@dataclass(frozen=True)
class RubricItem:
    key: str
    label: str
    stage: str  # one of STAGES or NOT_ENOUGH
    why: str
    evidence: Evidence | None
    improvement: str  # a concrete example with blanks; never an invented fact


@dataclass
class FeedbackReport:
    case_id: str
    rubric_version: str
    items: list[RubricItem]
    answered: int
    ended_because: str | None
    limits: tuple[str, ...] = LIMITS
    notes: list[str] = field(default_factory=list)

    def stage_of(self, key: str) -> str:
        return next(i.stage for i in self.items if i.key == key)

    def text(self) -> str:
        out = [f"練習のフィードバック（{self.case_id}・回答 {self.answered} 件）", ""]
        for i in self.items:
            out.append(f"■ {i.label}：{i.stage}")
            out.append(f"  理由：{i.why}")
            if i.evidence:
                out.append(f"  あなたの回答の該当箇所：「{i.evidence.text}{'…' if i.evidence.truncated else ''}」")
            out.append(f"  改善の例：{i.improvement}")
        out += ["", "【この評価の限界】"] + list(self.limits) + [""] + self.notes
        return guards.assert_clean("\n".join(out))


def _quote(turn, a: int, b: int, limit: int = 60) -> Evidence:
    text = turn.text
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1] in "。！？!?\n ":
        b -= 1
    cut = min(b, a + limit)
    if guards.forbidden_claims_in(text[a:cut]) or guards.forbidden_claims_in(text[a:b]):
        return Evidence(turn.turn_id, a, cut, WITHHELD, cut < b, redacted=True)
    return Evidence(turn.turn_id, a, cut, text[a:cut], cut < b)


def _first(turn, pred):
    for a, b in analysable(turn.text):
        if pred(turn.text[a:b]):
            return a, b
    return None


def _item(key, label, stage, why, ev, template) -> RubricItem:
    quote = ev.text if ev else "（該当する回答がありません）"
    if ev and ev.redacted:  # the example would repeat words that are not quoted: give a generic one that still leaves the facts blank
        return RubricItem(key, label, stage, why, ev, "例：断定の言葉を、ご自身の経験に基づく言い方に言い換えてみましょう。「〇〇という経験から、△△と考えています」（〇〇・△△はあなたの言葉で）")
    return RubricItem(key, label, stage, why, ev, guards.assert_clean(template.format(q=quote)))


def build_feedback(session: InterviewSession) -> FeedbackReport:
    cands = [t for t in session.candidate_turns() if analysable(t.text)]
    if not cands:
        items = [_item(k, label, NOT_ENOUGH, "分析できる回答がありませんでした。", None, "まず質問に 2〜3 文で答えてみましょう。") for k, label in RUBRIC]
        return FeedbackReport(session.context.case_id, RUBRIC_VERSION, items, 0, session.end_reason, notes=["回答がないため、段階を付けていません。"])
    items = []
    # 1 clarity: the first sentence of the first answer states the point briefly
    t0 = cands[0]
    a, b = analysable(t0.text)[0]
    n = len(t0.text[a:b].strip("。！？!? \n"))
    stage = STAGES[2] if n <= 60 else STAGES[1] if n <= 90 else STAGES[0]
    first = t0.text[a:b]
    first_vague = any(w in first for w in VAGUE)  # v1.2: a number in the same sentence ("いろいろな活動を3回") does not make broad words concrete
    first_absolute = any(w in first for w in ABSOLUTE)
    why = f"最初の一文は {n} 文字です（60 文字以内なら結論が伝わりやすい目安）。"
    if first_vague and stage == STAGES[2]:  # short is not clear when the sentence only says "a lot" or "very"
        stage, why = STAGES[1], why + "ただし「いろいろ」「頑張った」のような広い言葉で、何を言いたいかが短くても伝わりにくいです（数字があっても、何の数字かが分からないと具体的になりません）。"
    elif first_absolute and stage == STAGES[2]:
        stage, why = STAGES[1], why + "ただし「絶対」「必ず」のような断定の言葉があります。この練習では、それが正しいかは判断できません。根拠になる経験や数字を添えると伝わりやすくなります。"
    items.append(_item("clarity", "答えの明確さ", stage, why, _quote(t0, a, b),
                       "例：「{q}」→ 結論を先に短く言い、そのあとに理由を足します。「私は〇〇です。理由は△△だからです。」（〇〇・△△はあなたの言葉で）"))
    # 2 specificity: a number or an explicit example
    digit = [(t, _first(t, lambda s: re.search(r"\d", s) is not None)) for t in cands]
    marker = [(t, _first(t, lambda s: any(w in s for w in ("例えば", "たとえば", "具体的には", "その結果")))) for t in cands]
    has_d, has_m = any(s for _, s in digit), any(s for _, s in marker)
    vague = next(((t, s) for t in cands if (s := _first(t, lambda x: any(w in x for w in VAGUE) and not re.search(r"\d", x)))), None)
    if has_d and has_m:
        t, s = next((t, s) for t, s in digit if s)
        items.append(_item("specificity", "具体性", STAGES[2], "数字と具体例の両方が入っています。", _quote(t, *s), "例：この調子で、「{q}」のほかの主張にも場面や数字を足しましょう。"))
    elif has_d or has_m:
        t, s = next((t, s) for t, s in (digit + marker) if s)
        items.append(_item("specificity", "具体性", STAGES[1], "数字か具体例のどちらかはありますが、両方ではありません。", _quote(t, *s), "例：「{q}」→「{q}。具体的には、〇〇の場面で△△をして、□□という結果になりました。」"))
    else:
        t, s = vague if vague else (cands[0], analysable(cands[0].text)[0])
        why = "「いろいろ」「頑張った」のような広い言葉があり、数字や具体例がありません。" if vague else "数字も具体例もありません。"
        items.append(_item("specificity", "具体性", STAGES[0], why, _quote(t, *s), "例：「{q}」→「{q}。具体的には、〇〇の場面で△△を◇回行い、□□という結果になりました。」（〇〇・△△・◇・□□はあなたの経験で）"))
    # 3 consistency: later answers keep the nouns of the first (needs at least two answers)
    if len(cands) < 2:
        items.append(RubricItem("consistency", "一貫性", NOT_ENOUGH, "回答が 1 つだけなので、答えどうしの一貫性は見られません。", None, "もう 1 問以上答えると、一貫性も確認できます。"))
    else:
        def tokens(s: str) -> set[str]:
            return {w for w in re.findall(r"[一-龥ァ-ヴー]{2,}", s)}
        shared = tokens(cands[0].text) & set().union(*(tokens(t.text) for t in cands[1:]))
        stage = STAGES[2] if len(shared) >= 2 else STAGES[1] if shared else STAGES[0]
        t, s = cands[1], analysable(cands[1].text)[0]
        items.append(_item("consistency", "一貫性", stage, f"最初の回答と後の回答で共通して出てくる言葉は {len(shared)} 個です（目安：2 個以上）。", _quote(t, *s),
                           "例：「{q}」→ 最初に述べた関心（〇〇）とのつながりを一言で示します。「先ほどの〇〇とつながっていて、…」"))
    # 4 experience: an activity plus the person's own role
    act = next(((t, s) for t in cands if (s := _first(t, lambda x: any(w in x for w in ACTIVITY)))), None)
    role = any(any(w in t.text for w in ("私は", "担当", "役割", "任され", "リーダー", "自分が")) for t in cands)
    if act and role:
        items.append(_item("experience", "根拠となる経験", STAGES[2], "活動と、その中での自分の役割の両方が述べられています。", _quote(act[0], *act[1]), "例：この「{q}」から、学んだことを 1 つ選び、次の質問の答えにつなげましょう。"))
    elif act:
        items.append(_item("experience", "根拠となる経験", STAGES[1], "活動は出ていますが、自分の役割がはっきりしません。", _quote(act[0], *act[1]), "例：「{q}」→「{q}。そのなかで私は〇〇を担当しました。」"))
    else:
        t, s = cands[0], analysable(cands[0].text)[0]
        items.append(_item("experience", "根拠となる経験", STAGES[0], "主張を支える活動や経験が出てきません。", _quote(t, *s), "例：「{q}」→「{q}。そう考えたきっかけは、〇〇での経験です。」"))
    # 5 learning link: why this university / what to learn
    link = next(((t, s) for t in cands if (s := _first(t, lambda x: any(w in x for w in ("大学で", "学びたい", "研究したい", "将来", "入学後"))))), None)
    reason = any(any(w in t.text for w in REASON) for t in cands)
    if link and reason:
        items.append(_item("learning_link", "学びと志望のつながり", STAGES[2], "学びたいことと、その理由の両方が述べられています。", _quote(link[0], *link[1]), "例：「{q}」の理由を、一つの経験とつなげて締めましょう。"))
    elif link or reason:
        t, s = link or (cands[0], analysable(cands[0].text)[0])
        items.append(_item("learning_link", "学びと志望のつながり", STAGES[1], "学びたいことか理由のどちらかは述べられていますが、つながりが弱いです。", _quote(t, *s), "例：「{q}」→「{q}。そのために、この大学では〇〇を学びたいです。」"))
    else:
        t, s = cands[0], analysable(cands[0].text)[0]
        items.append(_item("learning_link", "学びと志望のつながり", STAGES[0], "入学後に学びたいことと、その理由が述べられていません。", _quote(t, *s), "例：「{q}」→「{q}。大学では〇〇を学びたいです。理由は△△だからです。」"))
    notes = [f"終了の理由：{session.end_reason}"]
    asked_ids = {t.question_id for t in session.turns if t.role == "interviewer" and t.origin == "ai_practice_material"}
    asked = {q.category for q in session.context.practice_questions if q.question_id in asked_ids}
    asked |= {session._doc_category[t.question_id] for t in session.turns if t.role == "interviewer" and t.origin == "document_based"}
    unasked = [c for c in session.context.plan.categories if c not in asked]
    if unasked:  # a session that ended early must not read as if every planned area was practised (found by the quality set: a time-up after the first question still rated all five items)
        notes.append("質問されなかった分野：" + "、".join(unasked) + "。この分野についての回答がないため、関連する項目（特に「学びと志望のつながり」）の段階は参考にしないでください。")
    if session.notices:
        notes.append("練習中のお知らせ：" + " / ".join(sorted({n.code for n in session.notices})))
    return FeedbackReport(session.context.case_id, RUBRIC_VERSION, items, len(cands), session.end_reason, notes=notes)


RUBRIC = (("clarity", "答えの明確さ"), ("specificity", "具体性"), ("consistency", "一貫性"), ("experience", "根拠となる経験"), ("learning_link", "学びと志望のつながり"))


def focus_of(report: FeedbackReport) -> RubricItem | None:
    """The item to work on in the next practice: the judged item with the lowest stage (ties: the rubric order).  None when nothing could be judged or every judged item is already at the top stage."""
    order = [k for k, _ in RUBRIC]
    judged = [i for i in report.items if i.stage in STAGES]
    if not judged:
        return None
    item = min(judged, key=lambda i: (STAGES.index(i.stage), order.index(i.key)))
    return None if item.stage == STAGES[-1] else item


def compare_text(before: FeedbackReport, after: FeedbackReport, focus: RubricItem | None = None) -> str:
    """A plain statement of what changed between two practices.  Only a judged improvement is called an improvement; the practice item is named first."""
    labels = dict(RUBRIC)
    result = compare(before, after)
    lines = ["前回との比較（練習用ルーブリックの段階。合否や実際の面接の出来を示すものではありません）"]
    if focus is not None:
        lines.append(f"前回の練習の焦点「{focus.label}」：{result[focus.key]}")
    lines += [f"・{labels[k]}：{v}" for k, v in result.items() if focus is None or k != focus.key]
    return guards.assert_clean("\n".join(lines))


def compare(before: FeedbackReport, after: FeedbackReport) -> dict[str, str]:
    """Per item: 改善 / 変わらず / 低下 / 比較できません (an item that could not be judged on either side is never counted as a change)."""
    out = {}
    for key, _label in RUBRIC:
        a, b = before.stage_of(key), after.stage_of(key)
        if a not in STAGES or b not in STAGES:
            out[key] = "比較できません"
        else:
            d = STAGES.index(b) - STAGES.index(a)
            out[key] = "改善" if d > 0 else "低下" if d < 0 else "変わらず"
    return out
