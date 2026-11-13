# DB v1 受け入れ契約（P2 / M1 の合否条件）

「DB完成」を、**自動で合否を判定できる条件**に変える。独立監査は `python -m src.integration.db_audit <DBのコピー> --target-kind <種別> [--baseline <旧コピー>]`（読み取り専用）、
試験は `tests/test_db_acceptance_{normal,invalid,history,faults,compat}.py` と `tests/test_db_audit.py`。

## 0. 契約の扱い
- **確定（confirmed）**：納品済みスキーマ（v0.5）に**すでにある**構造と、Claude 独立監査だけで決められる検査。Work の合意は不要。
- **提案（proposed）**：スキーマの追加・変更を要する項目。**Work の合意までは契約として扱わない**（`docs/DB_SCHEMA_GAP_ANALYSIS.md`、Issue）。
- 結果は `pass` / `fail` / `warn` / `not_run`。**`not_run`（行が0・旧コピーが無い・原典が無い）は `pass` ではない。**
- 対象の種別を必ず記録：`synthetic`（合成）、`repository_sample`（リポジトリのサンプル）、`copied_real_db`（実DBの独立コピー）、`production_read_only`（本番を読み取り専用）。**合成での成功を実DBの成功と呼ばない。**

## DB-1 識別子・スコープ
| 項目 | 内容 | 状態 |
|---|---|---|
| サイクル | `admission_cycles(case_id TEXT PK, university, faculty, department NULL, admission_method, fiscal_year INT[2000,2100], exam_year INT[2000,2100])`、UNIQUE(大学,学部,学科,方式,入学年度) | 確定 |
| 同名の方式が複数大学にある | 別のサイクル（大学が違えば UNIQUE が衝突しない） | 確定、試験あり |
| 年度が違えば別サイクル | `fiscal_year` が UNIQUE に含まれる | 確定、試験あり |
| 実施年度 | 入学年度と同じか前年（外れたら警告）。`cycle_dimensions` が持つ年と一致（DB-10） | 確定（警告） |
| 学科が NULL の重複 | UNIQUE は NULL を等しいとみなさない → **DB-02 が重複を失敗にする**。恒久対策は `COALESCE(department,'')` のUNIQUE索引 | 確定（監査）／提案（索引） |
| 失敗時 | 越境（大学・学部・学科・方式・年度の不一致）は `stage` が `ValueError` で拒否し何も書かない | 確定 |
検査：DB-02、DB-10。試験：`test_db_acceptance_normal`（新大学・新年度・同名方式）、`_invalid`（越境）。

## DB-2 原典と事実の対応
| 項目 | 現状の置き場 | 状態 |
|---|---|---|
| `source_id` | `source_documents.sha256`（PK）。別の source_id は無い | 確定（sha が識別子） |
| `source_url` / `retrieved_at` | `source_documents.url / retrieved_at`、record_json | 確定 |
| `source_kind`（pdf/html） | **record_json のみ**（`source_documents` に列なし） | 提案（列を足す） |
| `published_at`（公式の公表日。不明は null） | **どこにも無い** | 提案（nullable 列） |
| `source_sha256` | `facts.source_sha256`（FK）。record の値と一致（DB-04） | 確定 |
| `evidence_id` / `logical_id` / `fact_key` / `value` / `scope` / `proofs` | `facts`（初版）、`evidence_revisions`（版）、record_json | 確定 |
| `field_proofs`（項目ごとの原文位置） | record_json のみ。構造 `{項目: {value, actor, action, applies_to, proof_indices, exceptions}}` | 確定（形）／提案（検証規則） |
| 引用が保存ページにある | DB-12（保存した**写し**との照合。**原典との照合ではない**） | 確定 |
不変条件：事実の `source_sha256` は `source_documents` に存在、ページ本文は `text_sha256` と一致（DB-03）、record の ID・fact_key・値・年度・方式・大学・学部が行と一致（DB-04）。
**未合意の項目（`published_at`、`source_kind` 列、`field_proofs` の必須化）を既成事実にしない。**

## DB-3 条件と例外
- 値は登録簿（`docs/FACT_KEYS.md`）の fact_key ごとの型。**不明な項目は省略。`false`・`0` に置き換えない**（登録簿の契約）。DB-11 が、未登録 fact_key・型違い・不正な `stage` を失敗にする。
- 条件と例外の**意味**（義務・許可・禁止の取り違え）は記事のQA（登録簿の assertions）の範囲で、DB の不変条件ではない。DB は値の形と出所まで。
- 根拠が不足する値は「未検証」として報告（`semantic_coverage`）。
状態：確定（監査）。試験：`_invalid`（DB-11）、`_compat`（新 fact_key・`stage`）。

## DB-4 版管理と履歴
| 項目 | 内容 | 状態 |
|---|---|---|
| 原典の旧版・新版 | `source_documents`（sha256ごとの行）。旧行は消さない | 確定 |
| 根拠の論理IDと版 | `evidence_revisions(evidence_id PK, logical_id, parent_evidence_id)`、`evidence_heads(logical_id PK)` | 確定 |
| 記事の論理IDと版 | `article_versions`（初版）、`revised_articles(article_id, base_article_id)`、`article_heads`。改訂の ID は `<base>:revision:<hash16>` で、`revision_hash` の接頭辞（DB-06） | 確定 |
| 親版の整合 | 親が存在・同サイクル・同 fact_key・循環なし（DB-05） | 確定 |
| 旧版の保全 | **旧コピーの全行が新DBに同じ内容で残る**（追記専用の12テーブル。DB-09） | 確定 |
| 追記専用の強制 | 現状は**コードのみ**。トリガー（UPDATE/DELETE を拒否）が望ましい | 提案 |
| 改訂理由・承認記録・有効化日時 | 承認は `update_batches.qa_json` と `update_events('approved', created_at)`（DB-07）。**改訂理由の列は無い** | 確定（承認）／提案（理由） |

## DB-5 更新処理の安全性
| 項目 | 内容 | 状態 |
|---|---|---|
| 候補→独立QA→承認→原子的有効化 | `stage`（候補）→ `finalize`（`BEGIN IMMEDIATE`、QAは入力と記事のハッシュに結合） | 確定、合成DBで試験 |
| 不合格時の保全 | QA 不合格は `rejected`、有効版は不変 | 確定、試験あり |
| ロールバック・バックアップ | スキーマ変更前の `snapshot`、`rollback_batch`、バックアップを旧コピーとして DB-09 | 確定、試験あり |
| 途中停止 | 例外は全体をロールバック、`candidate` が残れば警告（DB-07）、`recover_candidates` で `interrupted` | 確定、試験あり |
| 同時実行・二重起動 | 有効版が変わっていれば拒否、`ProcessLock` | 確定、試験あり |
| 冪等性 | 同じ入力は `no_change`、重複行なし | 確定、試験あり |
失敗時の動作：**旧有効版が壊れない**。不完全なバックアップはDBとして開けないか DB-09 が失敗する。

## DB-6 記事との連携
- 記事が引用する根拠は DB に存在し**同じサイクル**（DB-06）。改訂記事の引用も同様。
- 根拠1件の変更で影響する記事を特定：初版の記事は `article_evidence` で関係表になっている。**改訂記事は関係表が無く record_json の `evidence_ids` のみ** → 提案（`revised_article_evidence`）。現状は引用文（`[EV-…]`）の走査で再現できる（`src/versioning` が export で実施）。
- 影響のない記事は不変（旧コピーとの比較 DB-09）。

## DB-7 汎用性と移行
- 新しい大学・年度を足すのに**スキーマ変更なし**：`test_db_acceptance_normal`（合成）、v0.5 の3大学（`repository_sample`、`test_db_acceptance_compat`）。
- 既存の事実・記事の整合性が保たれる：DB-09。**v0.3 → v0.5 は追加のみ**（試験あり）。**v0.2 → v0.3 は世代の断絶**（`docs/DB_SCHEMA_GAP_ANALYSIS.md` G-01）。
- 将来のスキーマ変更の要件：`docs/DB_MIGRATION_REQUIREMENTS.md`。
- 索引：v0.3 以降は 0 → 性能の要件を提案（G-03）。

## 検査と試験の対応
| 検査 | 内容 | 失敗の種類 |
|---|---|---|
| DB-01 | integrity_check、外部キー | fail |
| DB-02 | サイクルの重複（NULL 学科）、実施年度 | fail／warn |
| DB-03 | 原典のハッシュ、ページの `text_sha256` | fail |
| DB-04 | 事実が所属サイクルの年度・方式・大学・学部と一致、値・ハッシュ一致 | fail |
| DB-05 | 版の親・循環・有効版 | fail |
| DB-06 | 記事の引用は同サイクルで実在、公開不可、改訂ハッシュ、有効版は改訂の関係 | fail |
| DB-07 | 承認済みバッチのQA・イベント、残った候補、最新の承認と有効版 | fail／warn |
| DB-08 | 同じ内容の版の重複 | warn |
| DB-09 | **旧コピーの全行の保全** | fail |
| DB-10 | `cycle_dimensions` の年の一致 | fail |
| DB-11 | fact_key・値の型・`stage`（登録簿） | fail |
| DB-12 | 引用が保存ページにある | fail |
| DB-14 | 追記専用テーブルに、UPDATE・DELETE を拒むトリガーがある（構造。行が無くても判定）。現状は無い（G-09） | warn |
| DB-15 | 検索に使う列（`case_id` など）に索引がある（構造）。現状は無い（G-03） | warn |
| V02-02〜05 | v0.2 世代：スナップショット、検証済みの事実に公式の根拠、記事版は同サイクルの事実、投稿は承認済みの記事版のみ | fail／warn |
- レポートには、監査したファイルの **SHA-256 とバイト数**（`copy_identity`）、スキーマ（表・索引・トリガー・移行の状態）、旧コピーとの**構造差分**を含む。`--expect-sha256` で、告知されたコピー以外のファイルを拒否する。必要な入力は `--describe-inputs`、作り方は `docs/DB_COPY_PROCEDURE.md`。
- **原典との照合は常に `not_run`**。M1 の合格には、実DBのコピー（`copied_real_db`）での実行が必要（`docs/DEVELOPMENT_MASTER_PLAN.md` の Gate P2）。
