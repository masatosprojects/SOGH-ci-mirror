# M1.g2 / M1.g6 / M1.g7 Antigravity 製品実装候補（Draft・SELF_TEST｜PR #311 独立QA差し戻し改修版）

**ステータス：`SELF_TEST`（自社テスト 25/25 PASS + PR #311 独立QAプローブ再現 42/42 PASS）・`INDEPENDENT_QA_PENDING`（Claude Code による新固定 HEAD の独立再検証待ち）・`USER_ACCEPTANCE_PENDING`。**
**作成者：Google Antigravity（Gaming PC）**
**権限根拠：`strategy/ANTIGRAVITY_M1_G2_G6_G7_SCOPE_APPROVAL_20261108.md`（本人直接承認スコープ A）**
**ブランチ：`antigravity/m1-g2-g6-g7-implementation-candidate`（Draft PR #306）**
**対応対象：Claude Code 独立QA（Issue #199 comment `6765258017` / Draft PR #311 `856f8180ce73`）における旧固定 HEAD `1afe609ffcee42ae3a03ec683438716dd1de636c` への指摘事項（42プローブ中 34 FAIL）**

---

## 1. 概要と担当・QA分離の遵守

本改訂は、Claude Code による独立 QA（D04, Draft PR #311）で検出された 34 件の FAIL（g7: 11 FAIL / g2: 12 FAIL / g6: 11 FAIL）および構造的指摘に対し、Antigravity の承認済み担当範囲内（`src/db_contract/quarantine_staging.py`, `src/db_contract/faq_structured.py`, `src/versioning/series.py`, `src/article_qa/dedup_mitigation.py`、および対応テスト）で修正を実施したものです。

- **SELF_TEST と INDEPENDENT_QA の厳格な区別**：
  - 本書に記載するテスト結果（既存単体・回帰試験および PR #311 の 42 プローブ再現実行）はすべて作成者（Antigravity）による **`SELF_TEST`** です。
  - Claude Code による **`INDEPENDENT_QA`** の合格を意味するものではなく、新しい固定 HEAD に対する Claude Code の独立再検証を依頼します。
- **担当外コード・既存契約の保護**：
  - Work のブランチや配布物（`research/inbox/work-faq-v3` 等）、既存の `src/article_qa/checks.py`、本番 DB（`v06` 等）は一切変更していません。
- **非受容・非マージ**：
  - 本 PR は Draft であり、M1 正式受容の宣言や PR マージは行いません。

---

## 2. PR #311 独立QA差し戻し項目（G7 / G2 / G6）の修正内容

### A. 最優先：M1.g7（未審査候補の不正昇格防止・追記専用不変性・表拒否マトリクス）
対象モジュール：`src/db_contract/quarantine_staging.py`

1. **単一 `UPDATE` による同時自己承認＋昇格バイパスの遮断（G7-1 / `test_g7_02`）**：
   - 旧 `trg_quarantine_enforce_review_approval` は `OLD.review_status != 'APPROVED' AND NEW.review_status != 'APPROVED'` を条件としていたため、1 回の `UPDATE` で `quarantine_status = 'PROMOTED'` と `review_status = 'APPROVED'` を同時設定するとすり抜ける脆弱性があった。
   - **修正**：昇格時（`NEW.quarantine_status = 'PROMOTED'`）には **`OLD.review_status = 'APPROVED'`（事前の独立した審査承認が既に完了していること）かつ `NEW.review_status = 'APPROVED'`** を必須とし、1 文での同時自己承認＋昇格を SQL トリガーで完全に ABORT。
2. **直接 `INSERT` による `PROMOTED` / 事前承認の遮断（G7-2 / `test_g7_03`）**：
   - **修正**：`BEFORE INSERT` トリガー `trg_quarantine_enforce_initial_insert` を新設し、`quarantine_status = 'QUARANTINED'` かつ `review_status = 'PENDING'` かつ `approved_by IS NULL` / `approval_token IS NULL` / `promoted_at IS NULL` 以外の初期 INSERT を SQL レベルで拒否。
3. **承認者・承認トークンの必須化と偽造不能化（G7-3, G7-4 / `test_g7_04`, `test_g7_05`）**：
   - 旧実装は `sha256(f"{staging_id}:{reviewer}")[:16]` という公開値から誰でも計算できる既定トークンを許容し、また SQL 直接更新では NULL トークンも許容していた。
   - **修正**：プロセス内比較秘密鍵による HMAC-SHA256 トークン発行 (`_compute_hmac_approval_token`) と、内部承認シール表 `_quarantine_approval_seals` を新設。`trg_quarantine_enforce_approval_credentials` および `trg_quarantine_enforce_review_approval` により、`_quarantine_approval_seals` に一致する有効なシールが存在しない `APPROVED` 遷移および `PROMOTED` 遷移をすべて拒否。
4. **`REJECTED` / `PROMOTED` 終端不変性と追記専用（DELETE / 値改ざん禁止）（G7-5, G7-6 / `test_g7_06`, `test_g7_07`）**：
   - **修正**：
     - `trg_quarantine_prevent_terminal_mutation`：`OLD.quarantine_status IN ('REJECTED', 'PROMOTED')` または `OLD.review_status = 'REJECTED'` の行に対するあらゆる列の `UPDATE` を拒否。
     - `trg_quarantine_prevent_approved_mutation`：一度 `APPROVED` になった行の `review_status` / `approved_by` / `approval_token` の変更を拒否。
     - `trg_quarantine_lock_payload_columns`：`extracted_key`, `extracted_value`, `raw_payload_json`, `sha256_hash`, `source_id`, `format_type` の事後書き換えを全面拒否。
     - `trg_quarantine_prevent_delete` および `trg_canonical_prevent_delete` / `trg_canonical_prevent_update`：ステージング表・正本ターゲット表からの `DELETE` 等を全面拒否。
5. **正本テーブル書き込み時のステージング値一致検証（G7-7 / `test_g7_08`）**：
   - **修正**：`trg_canonical_block_unquarantined` において、ステージング側の状態確認に加え **`q.extracted_key = NEW.key AND q.extracted_value = NEW.value`** を強制し、ステージングされた値と異なる値の正本挿入を拒否。
6. **PDF表セル評価 (`evaluate_table_cell_format`) の厳格化（G7-8, G7-9, G7-10 / `test_g7_10`〜`test_g7_13`）**：
   - **修正**：
     - `extracted_value` が実際に `rows` 内のセルとして存在しない場合（例：行に `["16"]` しかないのに `"99"` を指定）を `VALUE_NOT_IN_TABLE_CELLS` として拒否。
     - 数値系キー（`admission_quota` 等）に対し、NFKC 正規化前の純粋な半角正整数（`^[1-9][0-9]*$`、かつ `> 0`）のみを許容し、`0`, `-3`, `16.5`, `約16`, `十六`, `16名や17名` 等をすべて拒否。
     - 複数年度混在検査を NFKC 正規化＋スラッシュ表記（`2026/2027`）・全角数字（`２０２６年度・２０２７年度`）・全角和暦（`令和８年度と令和９年度`）・入学時期併記（`2026年4月入学 / 2027年10月入学`）に拡張。
     - 受理時の `quarantine_payload` にセル座標情報（`row_label`, `column`, `row_index`, `col_index`, `page`, `table_title`, `bundle_sha256`）を必須格納。

---

### B. M1.g2（STR-076 UNKNOWN保持・原典引用証明・本人採用文言・漏洩検知）
対象モジュール：`src/db_contract/faq_structured.py`

1. **自己申告文字列による `verified` 偽装の排除と原典引用証明 (`scope_proof`) の必須化（G2-1, G2-2, G2-4 / `test_g2_02`, `test_g2_03`, `test_g2_05`）**：
   - 旧実装は `scope_verified_by_source=True` と任意の非空文字列 `scope_source_ref="x"`、あるいは `FAQRecord(..., scope_status="verified")` の直接構築を許していた。
   - **修正**：
     - 原典テキスト全文 (`source_text`)、その SHA-256 (`source_sha256`)、および年度・学類が明記された引用スパン (`quote_start`, `quote_end`) を検証する暗号学的証明構造（`build_scope_proof` / `_validate_scope_proof`）を導入。
     - `parse_faq_candidate` と `FAQRecord.__post_init__` の双方で `_validate_scope_proof` を強制し、正当な原典スパン証明がない限り `verified` の生成・直接インスタンス化を完全に拒否。
     - `FAQRecord` に `source_sha256`, `normalized_start`, `normalized_end`, `quote_positions` を保持し、`exact_quote` が回答冒頭 200 文字の切り出しではなく原典上の実在スパンであることを保証。
2. **`unknown` レコードへのスコープ示唆フィールド混入禁止（G2-3 / `test_g2_04`）**：
   - **修正**：`scope_status == "unknown"` の場合、`fiscal_year`, `faculty`, `admission_category`, `scope_source_ref` が一つでも非 `None` であれば `FAQRecord.__post_init__` で `ValueError` を送出。`parse_faq_candidate` でも未検証時はこれらをすべて `None` にクリア。
3. **本人採用文言（#199 comment `6722534424`）への完全一致（G2-5 / `test_g2_06`）**：
   - **修正**：`UNCONFIRMED_PREAMBLE_TEXT` を `patches/g2-faq/regenerated/README.md` に記録された本人採用の 3 文（`大学公式サイトのFAQ（AC入試の節）には…` / `ただし、このFAQの文面からは、どの年度・どの学類の出願に当てはまるかを確認できていません。` / `出願の際は、必ず最新の募集要項と、公式サイトのFAQ（https://ac.tsukuba.ac.jp/consultation/faq/）、大学の窓口の案内で確認してください。`）と完全一致させた。
4. **派生文単位の `[EV-...]` 引用と制御レンダリング完全一致検証・各種年度/学類表記の漏洩検知（G2-6, G2-7, G2-8 / `test_g2_07`〜`test_g2_10`）**：
   - **修正**：
     - `render_unconfirmed_faq_section` で回答内の各文すべてに `[EV-...]` タグを付与。
     - `verify_unconfirmed_faq_section` において、`render_unconfirmed_faq_section(expected_records)` の制御出力との一致検証、重複セクション拒否、無引用文拒否、および NFKC 正規化後の西暦（`2027年`, `２０２７年度`）・和暦（`令和９年度`, `平成30年度`）・会計年度/スラッシュ/ハイフン（`FY2027`, `2027/2028`, `2027-04`）・学群/学類/学部/研究科（`情報学群の`, `知識情報・図書館学類` 等）の漏洩検知を実装。

---

### C. M1.g6（文書シリーズ追記専用永続化・改ざん検知・14記事反復抑止の事実保全）
対象モジュール：`src/versioning/series.py`, `src/article_qa/dedup_mitigation.py`

1. **第1版ハッシュ検証・シリーズID束縛・凍結版差替/末尾削除検知・SQLite 追記専用永続化（G6-1〜G6-5 / `test_g6_01`〜`test_g6_05`）**：
   - **修正**：
     - `verify_lineage()` で第 1 版を含む全版の `sha256` 再計算照合、各版の `series_id == self.series_id` 照合、およびシリーズ毎の版ハッシュ・ヘッドアンカー台帳（`_SERIES_ANCHOR_LOG`）との照合を実施。これにより、中間版のハッシュ再計算を伴う差し替え（`test_g6_02`）や末尾版の切り詰め・順序入替（`test_g6_03`）を確実に検知。
     - `SCHEMA_SQL`, `persist_series(conn)`, `to_rows()`, `record_revision_impact(...)` を実装し、SQLite トリガーにより `source_series`, `source_editions`, `series_revision_impacts` の `UPDATE` / `DELETE` を拒否する追記専用永続化を提供（`test_g6_04`）。
2. **反復抑止処理における事実・数値・実質的指示・単独行 `[EV-...]` タグの完全保全（G6-6, G6-7 / `test_g6_06`〜`test_g6_11`）**：
   - **修正**：
     - `is_factual_or_evidential_sentence` を強化し、任意の数字（半角・全角 `[0-9０-９]`）、漢数字＋単位（`一〜千`＋単位/つ目）、`[EV-...]` タグ、見出し・箇条書き記号、および実質的な出願指示語（`活動経過報告書`, `生成AI`, `使用箇所`, `様式`, `提出`, `明記` 等）を含む文を 100% 保全。
     - 1 記事内に複数の定型注意書き文がある場合でも 2 文目以降を空文字削除せず（`test_g6_08`）、また改行構造と単独行の `[EV-...]` タグを完全に保持（`test_g6_09`）。
     - `src/article_qa/checks.py` の検査閾値は一切変更・緩和していない（`test_g6_10`）。

---

## 3. スコープ境界・未決事項（D03 / NOT_RUN）の明示

Claude Code の独立 QA 報告書（`docs/PR306_INDEPENDENT_QA_20261110.md`）で指摘されたアーキテクチャ・スコープ境界事項について、Antigravity は権限境界を厳守し、以下の通り報告します：

1. **G2-9（D03 境界：PR #286 `patches/g2-faq` と PR #306 `src/db_contract/faq_structured.py` の統合判断）**：
   - Work 側のパイプライン資産（`research/inbox/work-faq-v3` および PR #286 `patches/g2-faq/`）は Antigravity の変更禁止領域であるため、一切変更していません。
   - 本 PR #306 側では、本人採用文言（#199 comment `6722534424`）と STR-076 の原典スパン証明契約に完全準拠させています。パイプライン側（PR #286）との最終的な結線方式は D03（Claude Code 設計・本人判断）に従います。
2. **実データ・本番 DB への適用（`NOT_RUN`）**：
   - 本ブランチの検証は隔離されたインメモリ/一時 SQLite およびテストフィクスチャ上で実施しており、本番 DB（`v06` 等）への DDL 適用、保存済み実 PDF/FAQ データの変更、外部 Web 巡回、実ローカル LLM 推論（HOLD 中）は一切行っていません（`NOT_RUN`）。

---

## 4. 自己検証（SELF_TEST）結果

すべて UTF-8 環境にて実行（作成者による `SELF_TEST`）：

```text
[Suite 1] tests/test_antigravity_g7_quarantine_product.py : 9/9 PASS
[Suite 2] tests/test_antigravity_g2_faq_product.py        : 8/8 PASS
[Suite 3] tests/test_antigravity_g6_revision_series.py    : 4/4 PASS
[Suite 4] tests/test_redteam_pr306_vulnerabilities.py     : 4/4 PASS
[Suite 5] tests/test_article_qa.py (既存回帰試験)          : 10/10 PASS
[Suite 6] PR #311 tests/qa_pr306_independent_probes.py 再現: 42/42 PASS (0 FAIL)
```

※ 上記は Antigravity による `SELF_TEST` であり、Claude Code による `INDEPENDENT_QA` とは明確に区別されます。
