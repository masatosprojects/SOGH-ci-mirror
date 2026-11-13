# fact_key 登録簿と、新しい fact_key の登録手順

Issue: #19　登録簿の本体: [src/verify/data/fact_keys.json](../src/verify/data/fact_keys.json)
一覧（自動生成）: [FACT_KEYS_REFERENCE.md](FACT_KEYS_REFERENCE.md)　実装: [src/verify/fact_registry.py](../src/verify/fact_registry.py)

## 何のためにあるか

根拠レコード（evidence）の `fact_key`（`quota`、`interview`、`online_period` …）は、種類ごとに意味が違う。
「この値は人数か、分か、文字数か」「どの話題の文で引用されるべきか」「第1次選考の情報か」「年度内合計か単独枠か」。
以前はこれが Python のコードに埋め込まれていて、大学・方式が増えるたびにコード変更が要った。
**今は登録簿（データ）が持つ。** 新しい種類は、データを足すだけで、単位つきの数値照合・話題の照合・選考段階の照合が効く。

登録簿が持つもの：

| 項目 | 内容 |
|---|---|
| `registry_version` / `schema_version` | 登録簿の版（semver）／ファイル構造の版 |
| `kinds` | 数量の種類と、本文での単位（人数＝名・人、分、字、枚、MB、点、円 …） |
| `scopes` / `scope_patterns` | 適用範囲の語彙と意味（`faculty_annual_AO_aggregate`＝年度内合計、`all_*`＝方式の全学部共通 …） |
| `rules` | 検証ルール（検出カテゴリ、本文に必要な／あってはならない言い回し） |
| `semantic_triggers` | どの値のときに、どのルールを適用するか |
| `fact_keys` | キーごとの 意味・状態・since・選考段階・適用範囲・話題キーワード・**手がかり（`cues`）**・**値の項目（型・種類・単位・必須）**・出来事の言い回し（`temporal_keywords`） |
| `temporal_cues` | 時間の言い回し：『過去』（締切済み、既に経過 …）と『これから』（これから実施、受付中 …）。作業基準日の検証（#11）で使う |

## 未登録のものの扱い（黙って成功にしない）

| 重大度 | カテゴリ | 意味 | 記事QA・取り込みゲート |
|---|---|---|---|
| **error** | `unregistered_fact_key` | `fact_key` が登録簿に無い | **失敗**。検証済みとして扱わない |
| error | `missing_required_field` | 必須の値の項目が無い／null | 失敗 |
| error | `value_type_mismatch` | 型が違う（人数が文字列、日付が不正、など） | 失敗 |
| error | `value_not_object` | `value` がオブジェクトでない | 失敗 |
| warning | `unregistered_value_field` | 登録済みキーに、未登録の値の項目がある | 失敗しない。ただし報告（名前ベースの推定で照合は続ける） |
| warning | `unregistered_value` | 既知の値の一覧に無い値（例 `selection` が未知の値） | 報告 |
| warning | `unregistered_scope` / `scope_unusual_for_key` | 未登録の適用範囲／そのキーでは通常使わない範囲 | 報告 |
| warning | `fact_key_deprecated` | 廃止予定のキー | 報告（`replaced_by` を示す） |
| notice | `fact_key_proposed` | 提案中。使えるが仕様は未合意 | 報告 |
| notice | `legacy_no_fact_key` | `fact_key` の無い旧形式（`quota` のみ） | 従来どおり照合し、報告 |

未登録のキーでも、**数値・日付・単位の照合は続く**（名前ベースの推定）。未登録は「照合されない」ではなく「失敗として報告される」。
内容で発動するルール（年度内合計、時間枠、いずれか、OR/AND、候補日の欠落）も、未登録のキーに対して効く。

## Work が新しい fact_key を使いたいとき（手順）

1. **提案する**（Issue #19 または #22 にコメント）。次を書く：
   - 名前（`lower_snake_case`）と意味（何の情報か）
   - 値の項目：名前、型（下表）、数量なら種類（`persons`/`minutes`/`chars`/…）、必須か、null を許すか
   - 適用範囲（`scope`）の候補
   - その情報が書かれる文に出る言葉（話題キーワード）と、**他のキーと取り違えにくい手がかり（`cues`）**：例「第1次…結果」「最終…発表」。`active` にするには必須。一般的すぎる語（「面接」「発表」）だけにしない
   - 選考段階に属するなら 1 か 2
   - 日付を持つ出来事なら、本文での呼び名（`temporal_keywords`：例「出願期間」「面接日」「合格発表」）。作業基準日の検証が、引用の無い文を根拠に結び付けるために使う
   - 既存のルール（合計/時間枠/いずれか/OR・AND）が当てはまるか
2. **Claude が `proposed` として登録**する（PR、`registry_version` の minor を上げる）。この時点から Work はそのキーを出力でき、QA は失敗にならない（「提案中」の注意が出る）。
3. Work は出力を**自己点検**する：
   ```
   python -m src.verify.fact_registry check <export.json>
   ```
   `unregistered_fact_keys` が空で、`by_severity.error` が 0 であること。
4. 仕様が合意されたら `status` を `active` にする（PR）。
5. **既存のキーに値の項目を足すとき**も、先に提案する（未登録の項目は警告として出続ける）。

`master` の登録簿を、Work が直接書き換えない。破壊的な変更（意味の変更、キーの削除、型の変更）は、必ず Issue で合意してから。

## 登録簿に fact_key を足す方法（コードは不要）

`src/verify/data/fact_keys.json` の `fact_keys` に追加する。例：

```json
"waitlist": {
  "description": "補欠合格",
  "status": "proposed",
  "since": "1.1.0",
  "stage": 2,
  "scopes": ["target_admission_cycle"],
  "topic_keywords": ["補欠"],
  "value": {
    "seats":             {"type": "integer", "kind": "persons", "required": true, "description": "補欠の人数"},
    "minutes_to_answer": {"type": "integer", "kind": "minutes"}
  }
}
```

これだけで、本文の「8名」「20分」が根拠の値と照合され、「補欠」と無関係な文での引用が検出され、「第1次選考」と書くと段階の不一致になる。

確認と更新：
```
python -m src.verify.fact_registry validate          # 登録簿そのものの検査（構造・型・ルール・正規表現）
python -m pytest tests/ -q                           # 既存の全テスト（skip 0）
python -c "from pathlib import Path; from src.verify.fact_registry import get_registry, render_markdown; \
  Path('docs/FACT_KEYS_REFERENCE.md').write_text(render_markdown(get_registry()), encoding='utf-8', newline='\n')"
```
`FACT_KEYS_REFERENCE.md` は生成物で、テストが登録簿との一致を確認する（直接編集しない）。

### 値の型

`integer` / `number` / `string` / `boolean` / `iso_date`（YYYY-MM-DD）/ `iso_datetime`（日付、または日時）/ `clock_time`（HH:MM）/
`string_list` / `integer_list` / `iso_month_list`（YYYY-MM の一覧）/ `iso_date_list`。`bool` を整数として受け付けない。

### 値の項目の指定

`type`（必須）、`required`、`nullable`、`kind`（数量の種類。整数/数値の項目のみ）、`unit`（説明用）、`known_values`（既知の値。外れると警告）、
`role`（`logic`＝any_of_1_to_N／all_of_1_to_N、`period_label`＝`all_AO_held_in_2026` 形式、`entry_months`）、`paper_size`（A4 → 4）。

## 定性的な規則（登録簿 1.5.0、Issue #9）

登録簿は、数字のない意味の検証規則もデータとして持つ。コードは要らない（`docs/STRICT_VALIDATION.md` の「定性的な誤り」）。

- `fact_keys.<key>.assertions[]`：`when`（値の項目の条件。`equals` / `contains` / `regex` / `nonempty`）→ `must_any`（段落に必要な言い回し）、
  `forbid_any`（その文に出てはならない言い回し）、`echo_all_field`（リスト項目が全部本文に出る）、`category`、`message`。
- `qualitative_rules[]`：根拠の `qualifier`（注記）に対する、全レコード共通の規則（ヘッジ・限定・延長・持参・無条件化）。
- `article_rules[]`：根拠なしで全段落に効く定型注意書きの規則（`forbid_any` のみ）。
- `article_sentence_rules[]`（1.6.1）：`applies_to` に当たる定型の注意書きの文は、`must_any`（確認・必要という行為の述語）を保たねばならない。反転の言い回しを列挙しない、文の構造による保護。
- `lexicons`：同義語集。規則からは `lex:NAME`（集合まるごと）、`re:` パターンの中では `{lex:NAME}` で参照。**反対側の集合に含まれる語は入れない**。
- 文字列は部分一致。`re:` で始めると正規表現。壊れた正規表現・未知の同義語集・未知の `category` は登録簿の検証エラー。
- `category` は `polarity_mismatch` / `qualifier_dropped` / `qualifier_contradicted` / `unconditional_assertion` / `listed_item_omitted`。

新しい fact_key の真偽値・注記に規則が無ければ、QA は**エラーにせず**、`semantic_coverage` に「未検証」と出す。規則を足すときは、
先に Work の実データで誤検出0を確認する。

## generative_ai_policy の下線条件（登録簿 1.6.0、Issue #39）

筑波AC FAQ の下線の例外を、5つの**任意の真偽値**で構造化する（Work の提案を Claude が確定）。名前・意味・規則：

| 項目 | 意味（対象 × 要求） | AC FAQ の値 |
|---|---|---|
| `ai_text_underline_required` | AI（文章チェックを含む）が生成・修正した箇所と、その修正で間接的に影響した箇所の**下線** | true |
| `simple_spellcheck_underline_required` | 文書校正機能による**単純な誤字脱字の修正だけ**の下線（AIが内容を生成・修正する場合全般の免除ではない） | false |
| `human_advice_underline_required` | 他人の添削・助言による修正の下線（AIの修正とは別の対象） | false |
| `human_advice_activity_report_required` | 上記の他人の添削・助言による修正を**活動経過報告書**に記載することが必須（『下線不要』は『報告不要』を意味しない） | true |
| `ai_visual_disclosure_required` | AIで作成した画像・図・表等の**使用を説明文や脚注に明示**（文章の下線とは別の義務） | true |

- いずれも**任意・null不可**（`boolean`）。既存の記録（`allowed` / `not_accepted` だけ）は有効のまま。**不明な項目は省略する（falseへの置換は禁止）**。省略は『未検証』になる。
- 本文の検査は、**対象と要求の組合せを同じ文の中で**照合する（`assertions`）。同じ段落に別の対象の『不要』『必須』が残っていても通さない。
  AI修正の『下線不要』化、誤字脱字の例外の『必要』化・削除、他人の助言の『下線必要』化、活動報告の『任意』『不要』化、画像・図・表の『明示不要』化・削除を検出する。
- `field_proofs`（項目ごとの原文位置）を持つ記録で、真偽値に位置が無い項目は『未検証』に出る（持たない記録は従来どおり）。
- 適用範囲：その FAQ の AC 節と、その入試周期（`case_id`・年度・方式）に限る。他方式・翌年度への自動転用は不可（QAは記事の claim と根拠の対象の不一致を従来どおり検出する）。
- 参考文：Work が値から生成する3文（現行の配信と同一）が正例。書き換えは、`tests/test_underline_contract.py` の負例12系統で全て検出する。

## `claim_wording`（登録簿 1.7.0、Issue #47）

義務・禁止・免除を述べる節を見分ける語句（`obligation`：文字列／`re:` 正規表現）と、内容語の比較で除く語（`stop_terms`）。データなので、語を足すのにコードは要らない。
該当する節は、規則が照合したか、未検証（`unsupported_obligation` / `obligation_without_rule`）として必ず報告される（`docs/STRICT_VALIDATION.md`）。

## バージョン

- `registry_version`（semver）：**patch**＝説明・キーワードの修正／**minor**＝キーや項目の追加（後方互換）／**major**＝意味・型の変更、削除。
- `schema_version`：ファイル構造の版。変わると読み込みが失敗する（黙って古い読み方をしない）。
- QA のレポート（`run_qa_suite`、`validate_export`、`fact_registry check`）に、使った `registry_version` が入る。

## 出典の種類（PDF / HTML）

公式の募集要項は PDF、告知・FAQ は HTML のことが多い。根拠レコードの出典は次の契約に従う（登録簿の `source_kinds`）。

| `source_kind` | `source_pdf_sha256` | `source_sha256` | `proofs[].page` |
|---|---|---|---|
| `pdf` | **必須**（原本ファイルの sha256、64桁） | 同じ値でよい | PDFのページ |
| `html` | **null**（HTML を PDF と偽らない） | **必須**（ページ本文のバイトの sha256） | 論理ページ `1` |

- 違反は `source_contract_violation`（HTML に PDF ハッシュがある、`source_sha256` が無い／不正、PDF にハッシュが無い：**エラー**。HTML のページが 1 以外：警告）。
- `source_kind` の無い旧形式のレコードは、従来どおり（登録簿は何も言わない）。
- 版管理（`docs/VERSIONING.md`）は、版のハッシュとして `source_pdf_sha256`、無ければ `source_sha256` を使う。HTML 告知の更新も、PDF と同じ仕組みで検出できる。
- 独立監査（`audit_handoff`）は、HTML の根拠を **PDF として照合しない**。一覧にして「PDFでは検査できていない」と報告する（成功とは書かない）。

## 出来事の終了日（`event_end_field`）

日付を持つ事実が「いつ終わるか」を、キーごとに指定できる（例：`fee_refund` は `deadline`、`maintenance_notice` は `outage_end`）。
作業基準日の検証（#11）が、「締切済み」「これから」の判定に使う。指定した項目が null なら「終了日は不明」で、公開日など他の日付で代用しない。
指定が無いキーは、`end` / `date` / `dates` の最大を使う。

## 後方互換

- 既存の 30 事実・4 草案の QA 結果は変わらない（テストで固定：登録簿の単位分類が、従来の名前ベースの推定と完全に一致することも検証）。
- 登録簿に無い項目は、従来の名前ベースの推定に戻る。**登録簿の導入で、検査が弱くなる箇所は無い。**
- `fact_key` の無い旧形式の根拠も、従来どおり照合される。
