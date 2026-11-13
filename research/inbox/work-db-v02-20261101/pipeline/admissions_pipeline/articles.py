"""Local evidence-bound drafts and a stronger gate around Claude's heuristics."""
import hashlib
import json
import re
from datetime import date, datetime

from .extract import extract_pdf
from .store import canonical

TEMPLATE_VERSION = "source-draft-2026-11-01-v3"


def period_text(value):
    def display(s):
        if "T" in s:
            d = datetime.fromisoformat(s)
            return f"{d.year}年{d.month}月{d.day}日 {d.hour:02d}:{d.minute:02d}"
        d = date.fromisoformat(s)
        return f"{d.year}年{d.month}月{d.day}日"
    return display(value["start"]) + "〜" + display(value["end"])


def render_fact(fact):
    v, key = fact["value"], fact["key"]
    cite = "[" + fact["evidence_id"] + "]"
    if key == "quota":
        if fact["scope"] == "faculty_annual_AO_aggregate":
            year = v["period"].removeprefix("all_AO_held_in_")
            return f"募集要項に記載された環境情報学部の募集人員は{v['count']}名{cite}です。この人数は、{year}年度に実施するAO入試（4月入学・9月入学）の合計です。夏秋AO単独の募集枠として読み替えないよう注意してください。"
        return f"知識情報・図書館学類のAC入試の募集人員は{v['count']}名{cite}です。ただし、{v['qualifier']}と要項に記されています。"
    if key == "policy":
        return v["text"] + "する方針です。" + cite
    if key == "first_stage":
        return "第1次選考は、" + v["text"] + "する方式です。" + cite
    if key == "interview":
        if v["type"] == "allocated_time_window_not_net_question_time":
            return f"面接試験の実施時間の枠は一人{v['minutes']}分程度{cite}です。これは要項上の実施時間枠です。実質的な質疑時間が同じ長さだとは断定できません。待機時間が長くなる場合もあるため、集合日時と大学からの案内を確認してください。"
        return f"第1次選考の合格者には、面接・口述試験を個別に{v['minutes']}分程度{cite}実施し、提出書類なども含めて総合的に判定します。{v['qualifier']}ため、所要時間を固定して考えないようにしましょう。"
    if key == "online_period":
        suffix = "出願登録と検定料の払い込みを行う期間です。" if "払い込み" in v["qualifier"] else "期間内にはシステム休止日があるため、下記の休止期間も確認してください。"
        return "オンラインでの登録・申請期間は" + period_text(v) + "です。" + suffix + cite
    if key == "maintenance":
        return "要項に記載されたシステム休止期間は" + period_text(v) + "です。メンテナンス中はログイン等ができないため、手続きの計画からこの時間帯を外す必要があります。" + cite
    if key == "postal_period":
        qualifier = "書類は郵送必着で、持参はできません。" if "持参不可" in v["qualifier"] else "日本国内は締切日消印有効、海外は締切日必着です。"
        return "郵送書類の提出期間は" + period_text(v) + "です。" + qualifier + "オンラインの締切と郵送の扱いを分けて確認してください。" + cite
    if key == "eligibility":
        if v["logic"] == "any_of_1_to_3":
            return f"出願資格は募集要項p.{v['details_page']}の（1）〜（3）のいずれかに該当することが条件です。各区分の学歴・卒業見込みや個別の入学資格審査などの条件は、原文の全体を確認してください。ここでは個人の出願可否の判定は行いません。{cite}"
        return f"出願資格は募集要項p.{v['details_page']}の共通条件（1）〜（4）を全て満たすことが必要です。学歴等の条件だけでなく、第一志望としての勉学希望、合格した場合の入学確約などの条件もあります。自分の区分と証明書類を原文に照らして確認してください。{cite}"
    if key == "common_test":
        if v["required"] is not False:
            raise ValueError("unsupported common-test state")
        return "このAC入試では、大学入学共通テストの受験は必要としないと要項に記載されています。" + cite
    if key == "second_stage_date":
        dates = [date.fromisoformat(d) for d in v["dates"]]
        days = "・".join(f"{d.year}年{d.month}月{d.day}日" for d in dates)
        suffix = "のいずれか" if v["selection"] == "one_of_not_both" else ""
        qualifier = "集合日時は大学の指定に従ってください。不測の事態により延期等となる場合もあります。" if suffix else "社会状況等によって実施日が変更される場合もあります。"
        return "対象の学部・学類の第2次選考日は" + days + suffix + "と要項に記載されています。" + qualifier + cite
    if key in ("final_result", "first_stage_result"):
        d = date.fromisoformat(v["date"])
        label = "最終段階の合格発表" if key == "final_result" else "第1次選考の結果発表"
        return f"要項に記載された{label}は、{d.year}年{d.month}月{d.day}日 {v['time']}（日本時間）からです。{cite}"
    if key == "statement_length":
        return f"志願理由書は所定の様式を使い、{v['max_characters']}字以内でまとめる指定です。作成前に様式と記入欄を確認してください。{cite}"
    if key == "recommendation_format":
        return "自己推薦書の本文は様式・枚数自由で、根拠となる資料を添付します。一方、表紙と活動経過報告書には所定の様式を使います。本文の自由度と、指定様式の必要性を分けて確認してください。" + cite
    if key == "interview_scope":
        return "要項は、提出した自己推薦書等の内容と、志願する学群・学類に必要な学習適応性（学習能力・知識・意欲等）を面接・口述試験で扱うとしています。これは公表された範囲の説明であり、個別の過去の質問内容を示すものではありません。" + cite
    if key == "personal_statement":
        return f"志望理由・入学後の学習計画・自己アピールは、文章と自由記述を組み合わせます。文章は日本語{v['essay_max_ja_chars']}字以内、英語{v['essay_max_en_chars']}字以内です。自由記述はA4サイズ{v['free_format_a4_pages_max']}枚以内、{v['free_format_max_mb']}メガバイト以内のPDFという指定です。{cite}"
    if key == "optional_materials":
        return f"任意提出資料は{v['max_items']}点まで提出できます。必要性と、自分の活動や構想とのつながりを整理して選んでください。{cite}"
    if key == "referees":
        return f"オンライン申請には評価者{v['evaluators_required']}名{cite}による評価入力が必要です。評価者の入力が完了するまではオンライン申請を完了できないため、本人が行う作業と評価者側の作業の進み方を分けて管理してください。"
    if key == "generative_ai_policy":
        return "生成AIを自身の学びを深める補助的なツールとして使うことは認められていますが、AIが生成した志望理由・学習計画・自己アピール・任意提出資料を受験生独自の成果物とはみなさないとされています。出願書類は自分で考え、自分の責任で作成することが前提です。" + cite
    if key == "interview_language":
        return "面接は日本語または英語で行われます。出願時に希望する言語を「日本語」「英語」「どちらでも可」から選ぶため、出願画面の指定も確認してください。" + cite
    if key == "entry":
        return "入学時期は" + "または".join(s.replace("-04", "年4月").replace("-09", "年9月") for s in v["months"]) + "です。出願時に選ぶ入学時期を確認してください。" + cite
    raise ValueError("unknown fact renderer: " + key)


def verify_pack(pack):
    """Re-extract the original instead of trusting a model, JSON or DB flag."""
    extracted = extract_pdf(pack["cycle"]["case_id"], pack["source"]["local_path"])
    expected = {f["evidence_id"]: f for f in extracted.facts}
    errors = []
    actual_ids = {f["evidence_id"] for f in pack["facts"]}
    if actual_ids != expected.keys():
        errors.append("fact_set_differs_from_original_profile")
    for fact in pack["facts"]:
        if fact["evidence_id"] not in expected or canonical(fact) != canonical(expected[fact["evidence_id"]]):
            errors.append("fact_differs_from_original:" + fact["evidence_id"])
    for field in ("university", "faculty", "department", "admission_method", "fiscal_year", "exam_year"):
        if pack["cycle"][field] != extracted.profile[field]:
            errors.append("cycle_mismatch:" + field)
    if pack["source"]["sha256"] != extracted.profile["sha256"]:
        errors.append("source_hash_mismatch")
    if pack["source"]["url"] != extracted.profile["url"]:
        errors.append("source_url_mismatch")
    return errors


def build_article(pack, series, as_of):
    errors = verify_pack(pack)
    if errors:
        raise ValueError(";".join(errors))
    cycle = pack["cycle"]
    facts = {f["key"]: f for f in pack["facts"]}
    subject = cycle["university"] + " " + cycle["faculty"] + (" " + cycle["department"] if cycle["department"] else "") + " " + cycle["admission_method"]
    claims = []
    def paragraphs(keys):
        selected = []
        for key in keys:
            if key in facts:
                fact = facts[key]
                text = render_fact(fact)
                claims.append({"key": key, "text": text, "evidence_id": fact["evidence_id"]})
                selected.append(text)
        return "\n\n".join(selected)
    if series == "overview":
        title = f"【{cycle['fiscal_year']}年度入学】{subject}｜出願・選考の要点を公式要項で確認"
        body = "\n\n".join([
            "## 最初に押さえたい募集枠と出願条件", paragraphs(["quota", "entry", "eligibility", "common_test"]),
            "## オンライン申請と郵送を分けて確認する", paragraphs(["online_period", "maintenance", "postal_period"]),
            "## 選考と結果発表", paragraphs(["first_stage", "first_stage_result", "second_stage_date", "final_result"]),
            "## 書類と面接をつなげて準備する", paragraphs(["policy", "interview"]),
            "## 出願書類の指定を先に確認する", paragraphs(["statement_length", "recommendation_format", "personal_statement", "optional_materials", "referees", "generative_ai_policy"]),
            "### 読者向けの整理のしかた（編集上の助言）\n\nまず自分が該当する出願資格と証明書類を原文で照合し、オンライン手続と郵送を別々のチェック欄に整理してください。次に、提出した説明と面接で伝える内容に食い違いがないか確認すると、準備することを具体化できます。この助言は合否を保証するものではありません。",
        ])
    elif series == "interview":
        title = f"【{cycle['fiscal_year']}年度入学】{subject}｜面接の公式情報と準備の整理"
        body = "\n\n".join([
            "## 面接の日程と所要時間の読み方", paragraphs(["second_stage_date", "interview"]),
            "## 大学が示している選考の前提", paragraphs(["first_stage", "policy", "interview_scope", "interview_language", "eligibility"]),
            "## 結果を確認する", paragraphs(["final_result"]),
            "### 練習を組み立てるヒント（編集上の助言）\n\n提出した書類を読み直し、自分が取り組んだこと、その理由、調べた方法、分かったこと、今後学びたいことを自分の言葉で説明できるか確かめてみてください。答えに詰まった部分は、根拠と説明のつながりを見直す手がかりになります。\n\nこれは練習のための整理例です。大学が実際に尋ねた過去問や、非公表の採点基準を再現したものではありません。予定時間だけを目安に暗記するより、質問に応じて説明を組み立てられる状態を目指すとよいでしょう。",
        ])
    else:
        raise ValueError("unknown article series")
    past = all(date.fromisoformat(facts[k]["value"]["end"][:10]) < as_of for k in ("online_period", "postal_period") if k in facts)
    notice = f"作業基準日：{as_of.isoformat()}。保存した公式要項の内容を整理した未公開草案です。"
    if past:
        notice += "記載する出願期間・面接日は既に経過しています。制度と実施日程の振り返り、および次の手続の確認に使ってください。"
    used_ids = sorted({c["evidence_id"] for c in claims})
    used = [f for f in pack["facts"] if f["evidence_id"] in used_ids]
    sources = []
    for fact in used:
        pages = "・".join(str(p) for p in sorted({q["page"] for q in fact["proofs"]}))
        sources.append(f"- [{fact['evidence_id']}] 公式募集要項 PDF p.{pages}：{fact['source_url']}#page={fact['proofs'][0]['page']}")
    text = "\n\n".join(["# " + title, notice, body,
        "## 確認してから次の行動へ\n\n最新情報は大学公式サイトでご確認ください。訂正や当日の案内が出ている場合は、その内容を優先してください。出願資格の個別判定と公開前の最新版確認は別途必要です。",
        "## 根拠資料\n\n" + "\n".join(sources)]) + "\n"
    input_hash = hashlib.sha256(canonical({"pack": pack, "series": series, "as_of": as_of.isoformat(),
                                          "template_version": TEMPLATE_VERSION}).encode()).hexdigest()
    article_id = cycle["case_id"] + ":" + series + ":" + input_hash[:16]
    return {"article_id": article_id, "case_id": cycle["case_id"], "series": series,
        "input_hash": input_hash, "title": title, "text": text, "claims": claims,
        "as_of": as_of.isoformat(), "template_version": TEMPLATE_VERSION,
        "evidence_ids": used_ids, "claim": {k: cycle[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")},
        "publish_allowed": False}


def validate_article(article, pack):
    errors = verify_pack(pack)
    facts = {f["evidence_id"]: f for f in pack["facts"]}
    if article.get("publish_allowed") is not False:
        errors.append("publication_not_authorized")
    try:
        expected = build_article(pack, article["series"], date.fromisoformat(article["as_of"]))
        for field in ("title", "text", "claims", "evidence_ids", "input_hash", "template_version"):
            if article.get(field) != expected[field]:
                errors.append("template_or_source_bound_content_changed:" + field)
    except (ValueError, KeyError):
        errors.append("invalid_article_provenance")
    for field, value in article["claim"].items():
        if pack["cycle"].get(field) != value:
            errors.append("article_scope_mismatch:" + field)
    for claim in article["claims"]:
        fact = facts.get(claim["evidence_id"])
        if fact is None or claim["key"] != fact["key"] or claim["text"] != render_fact(fact):
            errors.append("claim_not_derived_from_source:" + claim["evidence_id"])
        elif claim["text"] not in article["text"]:
            errors.append("claim_missing_from_article:" + claim["evidence_id"])
    cited = set(re.findall(r"\[(EV-[A-Za-z0-9_-]+)\]", article["text"]))
    if cited != set(article["evidence_ids"]) or not cited <= facts.keys():
        errors.append("citation_set_mismatch")
    # A date or unsupported number inserted elsewhere in the body must also be
    # detected, rather than passing Claude's narrower 人/名-only heuristic.
    remainder = article["text"]
    for claim in article["claims"]:
        remainder = remainder.replace(claim["text"], "", 1)
    remainder = remainder.split("## 根拠資料")[0]
    dates = re.findall(r"作業基準日：(\d{4})-(\d{2})-(\d{2})", article["text"])
    allowed = set(re.findall(r"\d+", article["title"])) | (set(dates[0]) if dates else set())
    if not set(re.findall(r"\d+", remainder)) <= allowed:
        errors.append("number_outside_source_derived_claims")
    return errors


def claude_export(packs, articles):
    evidence = {}
    for pack in packs:
        c, s = pack["cycle"], pack["source"]
        for fact in pack["facts"]:
            record = {k: c[k] for k in ("university", "faculty", "department", "admission_method", "fiscal_year")}
            record.update({"evidence_id": fact["evidence_id"], "source_url": s["url"],
                           "source_pdf_sha256": s["sha256"], "retrieved_at": s["retrieved_at"],
                           "fact_key": fact["key"], "value": fact["value"], "scope": fact["scope"],
                           "proofs": fact["proofs"], "verification": fact["verification"],
                           "publication_allowed": False})
            if fact["key"] == "quota":
                record["quota"] = fact["value"]["count"]
            evidence[fact["evidence_id"]] = record
    return {"evidence": evidence, "articles": articles}
