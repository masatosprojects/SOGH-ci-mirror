# G-02 移行履歴の契約と G-09 追記専用の保護（Claude の代行実装、2026-11-01）

**ラベル：`SELF_VALIDATED`（Claude が実装し Claude が試験）・`WORK_REVIEW_PENDING`・`WORK_CONTRACT_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用DBへの適用）。** 実装：`src/db_contract/additive_schema.py`（移行 `0004` と G-02 のランナー）。**どの運用DB・原本・監査コピーにも適用していない。使い捨てクローンだけ。** M1 のゲートは変更しない。

## 1. G-02：移行履歴の契約の不一致と解決
| 項目 | 要件（`docs/DB_MIGRATION_REQUIREMENTS.md`） | PR #70 の下書き | 本実装 |
|---|---|---|---|
| 履歴表 | `schema_migrations(version, from_version, applied_at, checksum)` | `(migration_id, description, statements_sha256, applied_at)` | **要件の列名に合わせた**：`version`・`from_version`・`applied_at`・`checksum`＋追加の列（`description`・`seq`・`statements_applied_sha256`） |
| `PRAGMA user_version` | 移行ごとに更新 | 更新していなかった | **最後に適用した移行の連番**に更新。履歴と食い違えば**ドリフトとして拒否** |
| from_version | 移行元の版 | 無かった | 最初は `schema_versions` の最後の版名（**事実を記録するだけ**。「0001 の基線」を捏造しない）、以後は直前の移行 ID |
| checksum | 適用済みの SQL が変わったら検出 | 記録だけで再実行時に比較していなかった | **移行の定義の SHA-256** を記録し、毎回比較。**適用後に編集された移行は拒否**（系統ごとに変わる文と分けるため定義に対して取る）。実際に流した文の SHA は別の列 |
| 順序・欠番 | 順序どおり | 検査なし | 適用済みは**チェーンの先頭からの連続**でなければ拒否。`only` は次に適用される移行だけ |
| 未知の移行 | — | 検査なし | コードの知らない適用済み移行（データベースの方が新しい）は拒否 |
| 途中失敗 | 中途半端な記録を残さない | 1 トランザクション | 同じ（`user_version` も同じトランザクション） |
| 下書きの形の履歴表 | — | — | 検出して拒否（使い捨てコピーを作り直す。運用DBにはまだ存在しない） |
既存の `schema_versions`（版名の文字列）はそのまま。`PRAGMA user_version` は全ての実コピーで 0 だった（G-02 の指摘どおり）。**合意済みの契約を変える必要は無く、実装を契約に合わせた。**

## 2. G-09：全テーブルの分類（現行契約と Work の更新経路から）
Work のコード（`research/inbox/work-faq-v3/pipeline`）の `UPDATE`・`DELETE`・`INSERT OR REPLACE`・`ON CONFLICT` を 2026-11-01 に全て確認した。
| 区分 | テーブル | 根拠 | 保護 |
|---|---|---|---|
| **A 追記専用** | `facts`・`source_documents`・`source_pages`・`evidence_revisions`・`article_versions`・`revised_articles`・`article_evidence`・`batch_evidence`・`update_events`・`cycle_editions`・`qa_runs`・`schema_versions`・`schema_migrations`（`evidence_aliases` は 0003） | 更新・削除する文が Work のコードに無い。DB-09 の追記専用の対象 | UPDATE・DELETE を拒否するトリガー |
| **B 正当な更新あり** | `evidence_heads`・`article_heads`（upsert、ロールバックで削除して再挿入）、`update_batches`（状態遷移） | `revisions.py` | **削除は許可**（ロールバック）。head は「**その論理 ID の改訂で、更新 batch に属する**」ものだけを許可。`update_batches` は **candidate→interrupted／rejected／approved、approved→rolled_back だけ**、識別の列は不変、QA の結果は決定と同時だけ、削除は拒否 |
| **C 意図的な置換** | `legacy_fact_links`（`INSERT OR REPLACE`） | `legacy.py` | **保護しない**（Work の判断待ち） |
| **D 契約未確定** | `legacy_imports`・`legacy_records`・`admission_cycles`・`admission_offerings`・`cycle_dimensions` | — | サイクルの**識別の列の更新**と、cycle・offering・dimension の**削除**だけ拒否（他の列の更新は未確定のまま） |
他のデータベース（監視器の `targets`・`runs`・`checks`）は入試DBではなく範囲外。**全テーブルに無差別に拒否を付けていない。**

## 3. 限界（合格に数えない）
- `INSERT OR REPLACE` は、暗黙の削除で DELETE トリガーが走らない（接続が `recursive_triggers` を ON にしていなければ）。BEFORE INSERT のトリガーは Work が意図して使う `OR IGNORE` と区別できない。**上書きは事後に db_audit DB-09 で検出するしかない**（試験で明記）。
- SQLite には DDL トリガーが無く、`DROP TABLE`・`DROP TRIGGER` は止められない。
- head は「同じ論理 ID の別の有効な改訂」へは直接動かせてしまう（ロールバックと同じ形）。QA のゲートを迂回する書き込みの完全な防止ではない。
- トリガーは**将来の書き込み**を守る。**過去の v03→v04 の履歴の欠落（F-2）を復元せず、受容もしない。** 過去の記録は書き換えていない。

## 4. 検証
- 合成：`tests/test_additive_schema.py`・`tests/test_g09_and_runner.py`（合計 58）。履歴・checksum・順序・user_version・途中失敗・A 区分の各表・別接続・`foreign_keys` OFF・`update_batches` の遷移（許可と拒否の表）・head の規則・正常な更新経路（QA 拒否・承認・復旧・ロールバック・承認の途中の失敗）・alias との両立・2 回目で変更なし。
- v06 の使い捨てクローン（`reports/db-audit/real_copy_g02_g09_2026-11-01.json`）：14/14。**Work の更新経路（g4 harness）は G-02/04/05/09 を適用したクローンで 22 成功・0 失敗**（以前の「head の直接書き込みは止まらない」は、別の論理 ID の改訂へは拒否される形に変わった）。バックアップから復元しても行・トリガー・`user_version` が同じ。
