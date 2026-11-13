"""Fail-closed extraction profiles for two inspected editions of official PDFs.

These are document-specific parsers, not a claim to support every university.
Unknown hashes, missing/ambiguous anchors and missing exceptions stop extraction.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROFILE_VERSION = "2026-11-01-v1"
EXTRACTOR_VERSION = "2026-11-01-v1.1"
PROFILES = {
    "tsukuba-klis-ac-2027": {
        "code": "T27", "university": "筑波大学", "faculty": "情報学群",
        "department": "知識情報・図書館学類", "admission_method": "アドミッションセンター入試",
        "fiscal_year": 2027, "exam_year": 2026,
        "sha256": "49cb4d7de07f47b13109b0a494f232ed7c83b89223b532ca8a8df5eb136439e3",
        "url": "https://ac.tsukuba.ac.jp/wp/wp-content/uploads/2026/06/AC_youkou2027_sec.pdf",
        "official_index": "https://ac.tsukuba.ac.jp/apply/application-guidelines/",
        "reviewed_visual_pages": [5, 11],
    },
    "keio-environment-ao-2026s-2027": {
        "code": "K27", "university": "慶應義塾大学", "faculty": "環境情報学部",
        "department": None, "admission_method": "2026夏秋AO入試",
        "fiscal_year": 2027, "exam_year": 2026,
        "sha256": "91dad17f3e88ef4a0706cfa0fd02c03eefe8010dac2cda39c8e8c1bb02f46ac6",
        "url": "https://www.keio.ac.jp/files/91dad17f3e88ef4a0706cfa0fd02c03eefe8010dac2cda39c8e8c1bb02f46ac6",
        "official_index": "https://www.keio.ac.jp/ja/admissions/faculty/examinations/ao-sfc-pem/",
        "reviewed_visual_pages": [8, 10, 16, 31],
    },
}


class ExtractionError(ValueError):
    pass


def normalized_with_positions(text):
    chars, positions = [], []
    for i, char in enumerate(text):
        for c in unicodedata.normalize("NFKC", char):
            if not c.isspace():
                chars.append(c)
                positions.append(i)
    return "".join(chars), positions


def normalize(text):
    return normalized_with_positions(text)[0]


def iso_date(year, month, day):
    return date(int(year), int(month), int(day)).isoformat()


@dataclass
class Extracted:
    case_id: str
    profile: dict
    pdf_path: Path
    pages: list[str]
    facts: list[dict]


class Extractor:
    def __init__(self, case_id, pages):
        self.case_id = case_id
        self.profile = PROFILES[case_id]
        self.pages = pages
        self.facts = []

    def match(self, page, pattern):
        text, positions = normalized_with_positions(self.pages[page - 1])
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if len(matches) != 1:
            raise ExtractionError(f"{self.case_id}:page{page}:expected_one_anchor_got_{len(matches)}")
        match = matches[0]
        raw = self.pages[page - 1][positions[match.start()]:positions[match.end()-1]+1]
        proof = {"page": page, "quote": raw, "quote_normalized": match.group(),
                 "normalized_start": match.start(), "normalized_end": match.end(), "pattern": pattern}
        return match.groupdict(), proof

    def add(self, key, value, proofs, *, scope="target_admission_cycle", notes=(), related=()):
        if any(f["key"] == key for f in self.facts):
            raise ExtractionError("duplicate fact key")
        evidence_id = f"EV-{self.profile['code']}-{len(self.facts)+1:02d}-{self.profile['sha256'][:6]}"
        self.facts.append({"evidence_id": evidence_id, "case_id": self.case_id, "key": key,
            "value": value, "scope": scope, "notes": list(notes), "related_keys": list(related),
            "proofs": proofs, "fiscal_year": self.profile["fiscal_year"],
            "source_pdf_sha256": self.profile["sha256"], "source_url": self.profile["url"],
            "verification": "source_checked_for_saved_version", "revision_clearance": "not_cleared_for_publication",
            "profile_version": PROFILE_VERSION})

    def period(self, page, pattern, key, *, reiwa=False, qualifier="", related=()):
        groups, proof = self.match(page, pattern)
        year = int(groups["year"]) + (2018 if reiwa else 0)
        value = {"start": iso_date(year, groups["sm"], groups["sd"]),
                 "end": iso_date(year, groups["em"], groups["ed"]), "timezone": "Asia/Tokyo",
                 "qualifier": qualifier}
        if "sh" in groups:
            value["start"] += f"T{int(groups['sh']):02d}:{int(groups['smin']):02d}:00+09:00"
            value["end"] += f"T{int(groups['eh']):02d}:{int(groups['emin']):02d}:00+09:00"
        self.add(key, value, [proof], related=related)

    def tsukuba(self):
        groups, quota = self.match(5, r"知識情報・図書館学類(?P<policy>.*?)?(?P<count>\d+)体育専門学群")
        _, caveat = self.match(5, r"※この入試の合格者にふさわしい志願者がいない.*?決定されます。")
        self.add("quota", {"count": int(groups["count"]), "unit": "名", "period": "AC_2027_KLIS",
                           "qualifier": "募集人員どおりに合格者を決定しない場合がある"}, [quota, caveat],
                 scope="department_and_method", notes=["同じ情報学群の他学類の人数を流用しない"])
        _, policy = self.match(5, r"社会における情報の伝達や知識の創造に関して幅広く興味を持ち.*?評価します。")
        self.add("policy", {"text": "情報・知識への関心、課題の発見と分析・解決、論理的説明や説得力のある提案を評価"}, [policy])
        _, first = self.match(5, r"出願時に提出された書類等により,第1次選考合格者を決定します。.*?重視します。")
        self.add("first_stage", {"text": "提出書類で選考し、自己推薦書と志願理由書を重視"}, [first], scope="all_tsukuba_AC")
        groups, interview = self.match(5, r"個別に(?P<minutes>\d+)分程度行います。なお,必要に応じ試験時間を延長する場合があります。")
        _, content = self.match(5, r"第1次選考の合格者に対し,面接・口述試験を行い.*?総合的に判定します。")
        self.add("interview", {"minutes": int(groups["minutes"]), "type": "individual_interview_and_oral_exam",
                              "qualifier": "必要に応じて試験時間を延長する場合がある"}, [interview, content], scope="all_tsukuba_AC")
        self.period(9, r"\(1\)出願登録・検定料の払い込み令和(?P<year>\d+)年(?P<sm>\d+)月(?P<sd>\d+)日\([^)]+\)(?P<sh>\d+):(?P<smin>\d+)[~〜～](?P<em>\d+)月(?P<ed>\d+)日\([^)]+\)(?P<eh>\d+):(?P<emin>\d+)",
                    "online_period", reiwa=True, qualifier="出願登録と検定料の払い込み")
        self.period(9, r"\(2\)出願書類の郵送令和(?P<year>\d+)年(?P<sm>\d+)月(?P<sd>\d+)日\([^)]+\)[~〜～](?P<em>\d+)月(?P<ed>\d+)日\([^)]+\)郵送必着\(持参不可\)",
                    "postal_period", reiwa=True, qualifier="郵送必着・持参不可")
        _, eligibility = self.match(6, r"5出願資格次の\(1\)[~〜～]\(3\)のいずれかに該当する者とします。")
        self.add("eligibility", {"logic": "any_of_1_to_3", "details_page": 6,
                                "qualifier": "各区分の条件と個別資格審査の期限は要項で確認"}, [eligibility], scope="all_tsukuba_AC")
        _, common = self.match(6, r"大学入学共通テストの受験は必要としません。")
        self.add("common_test", {"required": False}, [common], scope="all_tsukuba_AC")
        groups, second = self.match(11, r"知識情報・図書館学類(?P<month>\d+)月(?P<day>\d+)日\([^)]+\)")
        year, calendar = self.match(4, r"第2次選考\(面接・口述試験\)令和(?P<year>\d+)年10月7日")
        _, changes = self.match(12, r"今後の社会状況等によっては,実施日を変更する場合があります。")
        self.add("second_stage_date", {"dates": [iso_date(int(year["year"])+2018, groups["month"], groups["day"])],
                                       "selection": "specified_day", "qualifier": "社会状況等により変更の場合がある"}, [second, calendar, changes])
        groups, result = self.match(12, r"\(2\)最終合格者発表・通知令和(?P<year>\d+)年(?P<month>\d+)月(?P<day>\d+)日\([^)]+\)(?P<hour>\d+):(?P<minute>\d+)")
        self.add("final_result", {"date": iso_date(int(groups["year"])+2018, groups["month"], groups["day"]),
                                  "time": f"{int(groups['hour']):02d}:{int(groups['minute']):02d}", "timezone": "Asia/Tokyo"}, [result], scope="all_tsukuba_AC")
        groups, first_result = self.match(4, r"第1次選考結果発表令和(?P<year>\d+)年(?P<month>\d+)月(?P<day>\d+)日\([^)]+\)(?P<hour>\d+):(?P<minute>\d+)")
        self.add("first_stage_result", {"date": iso_date(int(groups["year"])+2018, groups["month"], groups["day"]),
            "time": f"{int(groups['hour']):02d}:{int(groups['minute']):02d}", "timezone": "Asia/Tokyo"}, [first_result], scope="all_tsukuba_AC")
        groups, statement = self.match(7, r"志願する理由を(?P<characters>\d+)字以内にまとめて記入してください。")
        self.add("statement_length", {"max_characters": int(groups["characters"]), "language": "Japanese", "specified_form": True}, [statement])
        _, recommendation = self.match(7, r"本文は様式・枚数自由で,その根拠となる資料を添付してください。")
        _, fixed_forms = self.match(7, r"表紙は,大学入試情報サイト「入試日程と募集要項」ページから所定の「自己推薦書\(表紙\)」と「活動経過報告書」をダウンロードし,所要事項を記入して使用してください。")
        self.add("recommendation_format", {"body_format": "自由", "body_pages": "自由", "supporting_materials": True,
                                           "cover_and_activity_report": "specified_forms"}, [recommendation, fixed_forms])
        _, interview_scope = self.match(5, r"面接・口述試験では,主に,出願時に提出された自己推薦書等の内容及び志願する学群・学類に必要な学習適応性\(学習能力,知識,意欲等\)について,個別に")
        self.add("interview_scope", {"topic_types": ["出願書類", "学習能力", "知識", "意欲"]}, [interview_scope], scope="all_tsukuba_AC")
        return self.facts

    def keio(self):
        groups, quota = self.match(8, r"環境情報学部(?P<count>\d+)名※募集人員は、(?P<year>\d+)年度に実施するAO入試\(4月入学/9月入学\)の合計数")
        self.add("quota", {"count": int(groups["count"]), "unit": "名", "period": "all_AO_held_in_"+groups["year"],
                           "entry_months": [4, 9], "summer_autumn_only_count": None,
                           "qualifier": "年度内に実施するAO入試の合計であり、夏秋AO単独の枠ではない"}, [quota], scope="faculty_annual_AO_aggregate")
        groups, entry = self.match(8, r"2026夏秋AO(?P<first>\d+)年4月、(?P<second>\d+)年9月")
        self.add("entry", {"months": [f"{groups['first']}-04", f"{groups['second']}-09"]}, [entry])
        self.period(9, r"オンライン申請(?P<year>\d+)年(?P<sm>\d+)月(?P<sd>\d+)日\([^)]+\)(?P<sh>\d+):(?P<smin>\d+)[~〜～](?P<em>\d+)月(?P<ed>\d+)日\([^)]+\)(?P<eh>\d+):(?P<emin>\d+)",
                    "online_period", qualifier="オンライン申請。期間内にシステム休止あり", related=["maintenance"])
        self.period(9, r"以下の期間は、メンテナンスのためオンライン出願システムを休止いたします\(ログイン等できません\)。(?P<year>\d+)年(?P<sm>\d+)月(?P<sd>\d+)日\([^)]+\)(?P<sh>\d+):(?P<smin>\d+)[~〜～](?P<em>\d+)月(?P<ed>\d+)日\([^)]+\)(?P<eh>\d+):(?P<emin>\d+)",
                    "maintenance", qualifier="メンテナンス中はログイン等ができない")
        self.period(9, r"出願書類の提出\(郵送\)(?P<year>\d+)年(?P<sm>\d+)月(?P<sd>\d+)日\([^)]+\)[~〜～](?P<em>\d+)月(?P<ed>\d+)日\([^)]+\)※※日本国内は締切日消印有効海外は締切日必着",
                    "postal_period", qualifier="日本国内は締切日消印有効、海外は締切日必着")
        _, eligibility = self.match(10, r"出願者共通以下の1\.[~〜～]4\.の条件を全て満たす者")
        _, commitment = self.match(10, r"2\.総合政策学部・環境情報学部への志望理由や入学後の構想が明確であり、第一志望としていずれかの学部での勉学を希望する者。また、合格した場合に入学することを確約できる者。")
        self.add("eligibility", {"logic": "all_of_1_to_4", "details_page": 10,
            "qualifier": "学歴等の条件に加え、第一志望・合格時の入学確約など全ての条件が必要"}, [eligibility, commitment])
        groups, second = self.match(16, r"環境情報学部●(?P<year>\d+)年(?P<m1>\d+)月(?P<d1>\d+)日\([^)]+\)●(?P=year)年(?P<m2>\d+)月(?P<d2>\d+)日\([^)]+\)のいずれか")
        _, change = self.match(31, r"不測の事態により、所定の日程通りに入学試験や合格発表等を実施することが困難であると本学が判断した場合、延期等の対応措置をとることがあります。")
        self.add("second_stage_date", {"dates": [iso_date(groups["year"], groups["m1"], groups["d1"]), iso_date(groups["year"], groups["m2"], groups["d2"])],
            "selection": "one_of_not_both", "qualifier": "いずれか。集合日時は大学の指定に従う。延期等の場合あり"}, [second, change])
        groups, interview = self.match(31, r"面接試験の実施時間の枠は一人(?P<minutes>\d+)分程度です。")
        _, selection = self.match(31, r"1次選考合格者に対して面接試験を湘南藤沢キャンパスにて行います。.*?総合的に判断します。")
        _, waiting = self.match(31, r"実施の順番によって、待機時間が長くなる場合があります。")
        self.add("interview", {"minutes": int(groups["minutes"]), "type": "allocated_time_window_not_net_question_time",
                               "qualifier": "実施時間の枠。待機時間が長くなる場合もあり、実質質疑時間とは区別する"}, [interview, selection, waiting])
        groups, result = self.match(31, r"2次選考合格発表期間(?P<year>\d+)年(?P<month>\d+)月(?P<day>\d+)日\([^)]+\)(?P<hour>\d+):(?P<minute>\d+)[~〜～]")
        self.add("final_result", {"date": iso_date(groups["year"], groups["month"], groups["day"]),
            "time": f"{int(groups['hour']):02d}:{int(groups['minute']):02d}", "timezone": "Asia/Tokyo"}, [result])
        _, first = self.match(8, r"入力・提出された書類\(資料を含む\)により選考します。")
        self.add("first_stage", {"text": "オンライン入力・提出書類（資料を含む）により選考"}, [first])
        groups, first_result = self.match(31, r"1次選考合格発表受験票の発行期間(?P<year>\d+)年(?P<month>\d+)月(?P<day>\d+)日\([^)]+\)(?P<hour>\d+):(?P<minute>\d+)")
        self.add("first_stage_result", {"date": iso_date(groups["year"], groups["month"], groups["day"]),
            "time": f"{int(groups['hour']):02d}:{int(groups['minute']):02d}", "timezone": "Asia/Tokyo"}, [first_result])
        groups, statement = self.match(19, r"1は、日本語を選択した場合(?P<ja>\d+)字以内で、英語を選択した場合(?P<en>\d+)字以内")
        pages, free = self.match(19, r"2は(?P<mb>\d+)メガバイト以内のPDFファイル\(A4サイズの用紙(?P<pages>\d+)枚以内の大きさ\)")
        self.add("personal_statement", {"essay_max_ja_chars": int(groups["ja"]), "essay_max_en_chars": int(groups["en"]),
            "free_format_a4_pages_max": int(pages["pages"]), "free_format_max_mb": int(pages["mb"])}, [statement, free])
        groups, optional = self.match(19, r"資料として(?P<count>\d+)点まで提出することができます。")
        self.add("optional_materials", {"max_items": int(groups["count"])}, [optional])
        groups, referees = self.match(13, r"評価者(?P<count>\d+)名による評価の入力が必要です。評価者の入力が完了するまで、オンライン申請を完了することはできません。")
        self.add("referees", {"evaluators_required": int(groups["count"]), "must_complete_before_submission": True}, [referees])
        _, ai = self.match(3, r"生成AIを自身の学びを深めるためのひとつの補助的ツールとして利用することはかまいませんが、.*?生成AIによって生成されたものを受験生独自の成果物とはみなしません。")
        self.add("generative_ai_policy", {"allowed": "学びを深める補助として利用", "not_accepted": "AI生成の出願書類を本人独自成果物とすること"}, [ai])
        _, language = self.match(31, r"面接は、日本語または英語で行います。出願時に、面接で使用する言語\(「日本語」・「英語」・「どちらでも可」\)を選択してください。")
        self.add("interview_language", {"languages": ["日本語", "英語"], "choice_required": True,
                                       "preference_options": ["日本語", "英語", "どちらでも可"]}, [language])
        return self.facts


def extract_pdf(case_id, pdf_path):
    import pymupdf
    profile = PROFILES[case_id]
    pdf_path = Path(pdf_path)
    if hashlib.sha256(pdf_path.read_bytes()).hexdigest() != profile["sha256"]:
        raise ExtractionError("PDF edition hash changed; profile must be reviewed before extraction")
    with pymupdf.open(pdf_path) as document:
        pages = [p.get_text() for p in document]
    if str(profile["fiscal_year"]) not in normalize(pages[0]):
        raise ExtractionError("entry year missing on cover")
    extractor = Extractor(case_id, pages)
    facts = extractor.tsukuba() if profile["code"] == "T27" else extractor.keio()
    for fact in facts:
        for proof in fact["proofs"]:
            if proof["quote"] not in pages[proof["page"]-1] or normalize(proof["quote"]) != proof["quote_normalized"]:
                raise ExtractionError("quote does not match the original page")
    return Extracted(case_id, profile, pdf_path.resolve(), pages, facts)
