# fact_key 登録簿（自動生成）

登録簿バージョン: **1.7.1**（schema 1、更新 2026-11-01）

このファイルは `python -m src.verify.fact_registry markdown` で `src/verify/data/fact_keys.json` から生成される。
**直接編集しない**（テストが生成結果との一致を確認する）。追加手順は [FACT_KEYS.md](FACT_KEYS.md)。

## fact_key 一覧

| fact_key | 意味 | 状態 | since | 段階 | 値の項目（型・種類） | 手がかり（cues） |
|---|---|---|---|---|---|---|
| `quota` | 募集人員 | active | 1.0.0 | - | `count`*:integer[persons], `unit`:string, `period`:string, `qualifier`:string, `entry_months`:integer_list, `summer_autumn_only_count`:integer[persons] | 募集人員・募集人数・定員・募集枠・欠員・正規表現:人数 |
| `entry` | 入学時期 | active | 1.0.0 | - | `months`*:iso_month_list | 入学時期・入学月・正規表現:入学 |
| `online_period` | オンライン出願（登録・申請）の期間 | active | 1.0.0 | - | `start`*:iso_datetime, `end`*:iso_datetime, `timezone`:string, `qualifier`:string | オンライン・出願登録・申請・登録・出願期間 |
| `maintenance` | 出願システムの休止期間 | active | 1.0.0 | - | `start`*:iso_datetime, `end`*:iso_datetime, `timezone`:string, `qualifier`:string | 休止・メンテナンス |
| `postal_period` | 出願書類の郵送（提出）期間 | active | 1.0.0 | - | `start`*:iso_datetime, `end`*:iso_datetime, `timezone`:string, `qualifier`:string, `late_arrival_domestic_registered_express_postmark_by`:iso_date | 郵送・書類の提出・提出期間・消印・必着・持参 |
| `eligibility` | 出願資格 | active | 1.0.0 | - | `logic`*:string, `details_page`:integer[page_ref], `qualifier`:string | 出願資格・資格・条件・該当 |
| `common_test` | 大学入学共通テストの要否 | active | 1.0.0 | - | `required`*:boolean | 共通テスト・教科・科目 |
| `first_stage` | 第1次選考の方式 | active | 1.0.0 | 1 | `text`*:string | 正規表現:第?[1１一]次選考は・書類で選考・により選考・選考する方式 |
| `first_stage_result` | 第1次選考の結果発表 | active | 1.0.0 | 1 | `date`*:iso_date, `time`:clock_time, `timezone`:string | 正規表現:(第?[1１一]次).{0,10}(結果|合格|発表) |
| `second_stage_date` | 第2次選考（面接等）の実施日 | active | 1.0.0 | 2 | `dates`*:iso_date_list, `selection`:string, `qualifier`:string | 正規表現:第?[2２二]次選考日・選考日・試験日・面接日・実施日 |
| `final_result` | 最終合格発表 | active | 1.0.0 | - | `date`*:iso_date, `time`:clock_time, `timezone`:string | 最終合格・最終段階・正規表現:最終.{0,6}発表 |
| `policy` | アドミッション・ポリシー（求める人物・評価の観点） | active | 1.0.0 | - | `text`*:string | 方針・求める・アドミッション・正規表現:評価する |
| `interview` | 面接（口述試験）の時間・日時・種類 | active | 1.0.0 | - | `minutes`:integer[minutes], `type`:string, `qualifier`:string, `date`:iso_date, `time`:clock_time, `dates`:iso_date_list, `selection`:string | 面接日・正規表現:面接は・開始時刻・所要時間・実施時間・分程度・時間は |
| `interview_scope` | 面接で扱う内容 | active | 1.0.0 | - | `topic_types`:string_list, `text`:string | 面接の配点・正規表現:面接には・正規表現:(面接|口述試験)(・口述試験)?(で|では)、?[^。]{0,40}(扱|評価|問)・評価を含 |
| `interview_language` | 面接の使用言語 | active | 1.0.0 | - | `choice_required`:boolean, `languages`*:string_list, `preference_options`:string_list | 言語・日本語または英語・どちらでも可 |
| `statement_length` | 志願理由書・小作文などの提出する文章の文字数の上限 | active | 1.0.0 | - | `max_characters`*:integer[chars], `language`:string, `specified_form`:boolean | 理由書・小作文・志望理由・志願理由 |
| `recommendation_format` | 自己推薦書の様式 | active | 1.0.0 | - | `body_format`:string, `body_pages`:string, `cover_and_activity_report`:string, `supporting_materials`:boolean | 自己推薦書・様式・表紙・活動経過報告書 |
| `personal_statement` | 志望理由・学習計画・自己アピールの分量（文章・自由記述） | active | 1.0.0 | - | `essay_max_ja_chars`*:integer[chars], `essay_max_en_chars`:integer[chars], `free_format_a4_pages_max`:integer[pages], `free_format_max_mb`:integer[mb] | 自由記述・メガバイト・A4・正規表現:(日本語|英語).{0,6}字 |
| `optional_materials` | 任意提出資料 | active | 1.0.0 | - | `max_items`*:integer[items] | 任意提出 |
| `referees` | 評価者（推薦者） | active | 1.0.0 | - | `evaluators_required`*:integer[persons], `must_complete_before_submission`:boolean | 評価者 |
| `generative_ai_policy` | 生成AIの利用に関する方針 | active | 1.0.0 | - | `allowed`:string, `not_accepted`:string, `ai_text_underline_required`:boolean, `simple_spellcheck_underline_required`:boolean, `human_advice_underline_required`:boolean, `human_advice_activity_report_required`:boolean, `ai_visual_disclosure_required`:boolean | 生成AI |
| `fee` | 検定料（出願料） | active | 1.0.0 | - | `amount`*:integer[yen], `currency`:string | 検定料・受験料・出願料・円 |
| `maintenance_notice` | 公式サイトの告知：出願システムの一時的なメンテナンス・停止の案内 | active | 1.3.0 | - | `text`*:string, `published_date`*:iso_date, `outage_end`:iso_datetime | メンテナンス・システム・アクセス・復旧 |
| `multilingual_evaluation` | 多言語（ドイツ語・フランス語など）の能力評価の案内 | active | 1.3.0 | - | `languages`*:string_list, `application_required`*:boolean, `text`*:string | 多言語・ドイツ語・フランス語 |
| `fee_refund` | 検定料の返還（例：第1次選考の不合格者が第2次選考分の返還を請求する手続） | active | 1.3.0 | - | `amount`*:integer[yen], `currency`:string, `deadline`*:iso_date, `text`*:string, `fee_paid`:integer[yen] | 返還・検定料・請求 |

`*` は必須の項目。種類（`[persons]` など）は、本文の数量を単位つきで照合するときの分類。

## 数量の種類と単位

| 種類 | 意味 | 本文での単位 |
|---|---|---|
| `persons` | 人数 | 名・人 |
| `minutes` | 時間（分） | 分・時間 |
| `chars` | 文字数 | 字・文字 |
| `words` | 語数 | 語・words・ワード |
| `pages` | 枚数 | 枚・ページ |
| `mb` | 容量（MB） | メガバイト・MB |
| `items` | 点数 | 点 |
| `yen` | 金額 | 円・万円 |
| `ratio` | 倍率・割合 | 倍・% |
| `page_ref` | 要項の参照ページ | p. |

## 適用範囲（scope）

| scope | 種別 | 意味 |
|---|---|---|
| `target_admission_cycle` | cycle | 対象の入試サイクル全体に適用される情報 |
| `department_and_method` | unit | 学部・学科と入試方式の組に限って適用される情報（他の学科へ流用しない） |
| `faculty_annual_AO_aggregate` | aggregate | 年度内に実施する複数回の入試の合計。単独の回・方式の枠ではない |
| `^all_[A-Za-z0-9_]+$`（パターン） | all_units | all_<大学・方式> 形式。その方式のすべての学部・学類に共通する情報 |

## 検証ルール

| ルール | 検出カテゴリ | 内容 | 発動する条件 |
|---|---|---|---|
| `aggregate_total` | `scope_reinterpretation` | 年度内合計の人数は『合計』と書き、『単独』の枠として書かない | `scope` contains `aggregate` |
| `time_window_not_net` | `scope_reinterpretation` | 面接の『実施時間の枠』を、実質の質疑時間として書かない | `value.type` regex `window.*not_net` |
| `one_of_dates` | `scope_reinterpretation` | 『いずれか』の候補日を、両日として書かない | `value.selection` equals `one_of_not_both` |
| `logic_any_of` | `logic_mismatch` | OR条件（いずれか）を、全て満たす条件として書かない | `value.logic` startswith `any_of` |
| `logic_all_of` | `logic_mismatch` | AND条件（全て）を、いずれか1つでよいとして書かない | `value.logic` startswith `all_of` |
| `all_dates_listed` | `date_omitted` | 候補日が複数あるとき、一部だけを書かない | `value.dates` min_items `2` |
