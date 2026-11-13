# 旧DB v0.2 の保全と移行の方針

**決定（ユーザー、2026-11-01）：旧DB v0.2 は保全対象とし、実DBの独立監査が完了するまで、v0.5 系への全面移行を実施しない。**
技術的な移行要件は `docs/DB_MIGRATION_REQUIREMENTS.md`、ギャップは `docs/DB_SCHEMA_GAP_ANALYSIS.md`（G-01）。この方針はそれらと矛盾しない：移行要件は「移行するときの条件」、この文書は「いつ移行を検討するか」。

## 1. 現在の方針
- v0.2 は**保全**する。移行・削除・上書きをしない。リポジトリにある v0.2 のサンプルDB（`research/inbox/work-db-v02-20261101/data/admission_media_v0_2.sqlite.gz`）も変更しない。
- v0.5 系は**当面の開発基盤**として扱うが、実DBの正式な現行版と断定しない。Work から**実DBのコピーまたは監査可能な構造情報**を得るまで、断定しない（Issue #55、`docs/WORK_BACKLOG.md` W-03）。
- 実DBの**現状監査**（読み取り専用・独立コピー）は急ぐ。実DBの**変更・移行**は、監査と契約合意の後。現状確認のために変更を伴う操作をしない。

## 2. 保全対象（v0.2 に存在し、v0.5 系に対応する保存先が無いもの）
v0.2 の次の情報は、移行時に**黙って破棄してはならない**。対応する保存先が無ければ、保存できない項目として一覧に載せる。
| v0.2 の情報 | v0.2 の置き場 | v0.5 系の対応 |
|---|---|---|
| 大学・学部・入試方式の識別子 | `universities` / `academic_units` / `admission_routes` | `admission_cycles` の文字列（独立した行・ID は無い） |
| 募集情報・根拠 | `fact_claims` / `fact_evidence`（`locator`・`excerpt`）/ `source_snapshots` | `facts`（record_json）、`source_documents`（sha256） |
| 記事企画 | `article_plans`（`state`・`subject_key`・`priority`）/ `article_series` | **無し** |
| 記事版 | `article_versions`（`version_no`・`prompt_version`・`generation_model`・`input_fingerprint`） | `article_versions`（別の構造） |
| レビュー状態・承認状態 | `article_versions.review_status`・`approved_at`、`fact_claims.review_status` | **無し**（`publish_allowed=0` の固定のみ） |
| 投稿履歴・冪等キー・外部公開URL | `publications`（`idempotency_key`・`external_post_id`・`external_url`・`publish_status`） | **無し** |
| 監査イベント | `audit_events` | `update_events`（更新のみ） |
| 公式の公表日・資料の種別 | `source_documents.issued_at` / `source_kind` | 公表日は無い、種別は record_json のみ（G-06） |
サンプルDBの行数（2026-11-01 時点、`reports/db-audit/schema_v0_2_sample_db.json`）：大学2、サイクル2、事実27、記事版6、記事企画6、投稿0、監査イベント6。**実DBの行数は不明**（[R]）。

## 3. 移行を再検討する条件（すべて満たしたときに限り、正式な承認を検討）
1. Work の実DBの構造を確認した（コピー、または `sqlite3 .schema` と行数）。
2. v0.2 の全テーブル・行・重要な状態の棚卸しを終えた。
3. 旧IDと新IDの対応表がある。
4. 保存できない項目の一覧がある（上表の「無し」をどうするか）。
5. 移行の前後で全行を照合できる（`db_audit --baseline`、DB-09）。
6. バックアップと復元の試験に合格した。
7. 途中で止まったときの安全性を確認した。
8. 冪等性を確認した（2回実行しても2回目は何も変えない）。
9. Claude が独立に監査した。
10. **ユーザーが移行の実行を承認した。**
**この10条件は、「検討を始める」ための条件で、移行の許可ではない。** 実行にはユーザーの明示承認（10）が要る。

## 4. 状態（`docs/development_progress.json` の WP と対応）
| 条件 | 現状 |
|---|---|
| 1 実DBの構造 | **未確認**（実DBが無い） |
| 2 棚卸し | サンプルDBのみ（`reports/db-audit/`）。実DBは未確認 |
| 3 ID対応表 | 無い |
| 4 保存できない項目 | 上表（サンプルDBの構造から。実DBの確認前） |
| 5 全行照合 | 手段はある（`db_audit --baseline`）。実行対象が無い |
| 6〜8 復元・中断・冪等 | 合成DBでは v0.3→v0.5 の追加のみの移行で確認。**v0.2→v0.5 は未実施** |
| 9 独立監査 | 未実施 |
| 10 ユーザーの承認 | 未取得 |
**したがって、v0.2→v0.5 の移行は計画も実行もしない。** 保全と、実DBの現状監査が先。

## 5. 補足
- v0.2 の `publications`（冪等キー付き）と `review_status` の設計は、将来の公開・承認の状態管理（`docs/PUBLICATION_POLICY.md`、G-08）の参考になる。再利用するかは Work と合意する。
- 実DB・秘密情報を GitHub に保存しない。コピーの扱いは `docs/DB_COPY_PROCEDURE.md`。
