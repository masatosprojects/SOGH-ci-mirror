# PR #306｜DB-17 対応：`init_*_schema` の DDL 非保持化設計案（`A-01`）

- **作成日**：`2026-11-11`
- **担当**：`Google Antigravity`（ゲーミングPC）
- **対象ブランチ**：`antigravity/m1-g2-g6-g7-implementation-candidate`（Draft PR #306）
- **根拠**：`STR-106`、PR #338 `docs/DB17_MIGRATION_DESIGN_DRAFT_20261111.md`（§3–§5）、`docs/execution-plan/ANTIGRAVITY_NEXT_WORK_20261111.md`（`A-01`）
- **位置づけ**：`DRAFT`（正式な移行ファイル `0012` / `0013`・移行番号予約・`src/db_contract/additive_schema.py` 編集は別承認 `U1` 待ちのため一切作成・編集しない）

---

## 1. 背景（DB-17 指摘事項）

Claude Code による独立 QA Round 2（`r2_g7_11`, `r2_g6_00`）において、以下の DB-17 契約違反が指摘された。

1. `init_quarantine_schema(conn)`（`src/db_contract/quarantine_staging.py`）および `init_series_schema(conn)`（`src/versioning/series.py`）が、`src/db_contract/additive_schema.py` のマイグレーション連鎖の外で `CREATE TABLE IF NOT EXISTS` / `CREATE TRIGGER IF NOT EXISTS` を直接実行していた。
2. そのため、`additive_schema.apply()` 済みの DB に対して `init_*_schema(conn)` を呼ぶと、`schema_migrations` に記録されていない `trg_quarantine_*` / `trg_series_*` トリガー群が生成され、`verify_schema_state(conn)` がスキーマドリフトとして拒否していた。

---

## 2. PR #306 側での実装整理（`DB17_MIGRATION_DESIGN_DRAFT_20261111.md` §4 R1 準拠）

正式な凍結 SQL（`0012` / `0013`）と `additive_schema.py` の更新は本人判断 `U1` 承認後の Claude Code 作業（`C-04`）となるため、PR #306 側では以下の通り責務を分離した。

### 2.1 DDL を持たない接続ガード登録・スキーマ存在検査関数の新設

| モジュール | 関数名 | 役割（DDL 実行有無） |
|---|---|---|
| [`src/db_contract/quarantine_staging.py`](../src/db_contract/quarantine_staging.py) | `register_quarantine_connection_guards(conn)` | **DDL なし**。`PRAGMA recursive_triggers = ON` と SQLite 接続関数 `_g7_verify_hmac_seal` のみを登録する。 |
| [`src/db_contract/quarantine_staging.py`](../src/db_contract/quarantine_staging.py) | `verify_quarantine_schema_ready(conn)` | **DDL なし**。`quarantine_staging_candidates` / `_quarantine_approval_seals` と 5 トリガーの存在を `sqlite_master` から読み取り専用で検査し、不足一覧を返す。 |
| [`src/versioning/series.py`](../src/versioning/series.py) | `register_series_connection_guards(conn)` | **DDL なし**。`PRAGMA recursive_triggers = ON` と SQLite 接続関数 `_g6_sha256_hex` のみを登録する。 |
| [`src/versioning/series.py`](../src/versioning/series.py) | `verify_series_schema_ready(conn)` | **DDL なし**。`source_document_series_editions` / `series_revision_article_impacts` と 7 トリガーの存在を `sqlite_master` から読み取り専用で検査し、不足一覧を返す。 |

### 2.2 移行済み DB における DDL 実行の完全抑止

- `init_quarantine_schema(conn)` および `init_series_schema(conn)` は、接続先 DB に履歴付きの `schema_migrations` 表が存在する場合（`_is_migration_managed_db(conn) == True`）、**いかなる `CREATE TABLE` / `CREATE TRIGGER` も実行せず**、`register_*_connection_guards(conn)` のみを行って返る。
- これにより、移行済み DB 上で `init_*_schema(conn)` を呼び出しても `verify_schema_state(conn)` の整合性（`problems == []`）が 100% 維持される（`r2_g7_11`・`r2_g6_00` 解消）。
- 単体テスト用の未移行 `:memory:` 接続（`schema_migrations` が存在しない接続）に限り、テストハーネス互換のため `_bootstrap_*_schema_for_tests(conn)` へフォールバックしてテーブル・トリガーを初期化する。

---

## 3. `U1` 承認後（`0012` / `0013` 凍結 SQL 導入後）の最終形移行案

本人判断 `U1` で `0012_g07_quarantine_staging.sql`・`0013_g06_series_editions.sql` の採番と `additive_schema.py` への登録が承認された後は、以下の 2 ステップで `_QUARANTINE_DDL_STATEMENTS` / `_SERIES_DDL_STATEMENTS` を本体モジュールから完全撤去できる。

1. **本体モジュール（`quarantine_staging.py` / `series.py`）**：
   - `init_*_schema(conn)` を「`register_*_connection_guards(conn)` ＋ `verify_*_schema_ready(conn)` が空でなければ `RuntimeError` / `MigrationError` を送出する」純粋な検査・関数登録ラッパーに置換し、モジュール内の `_QUARANTINE_DDL_STATEMENTS` / `_SERIES_DDL_STATEMENTS` を削除する。
2. **単体テスト（`tests/`）**：
   - `:memory:` テストフィクスチャは `additive_schema.py` の凍結 SQL（`0012` / `0013`）を直接読み込んで適用する test helper に統一し、本体コードと凍結 SQL の二重定義を完全に排除する。
