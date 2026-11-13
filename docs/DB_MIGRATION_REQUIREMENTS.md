# DB 移行の要件

スキーマを変える・別の世代へ移すときに**必ず満たす条件**。実DBでは、必ず**独立コピー**で先に実行する。検査は `db_audit --baseline <移行前コピー>`（DB-09）。

## 1. 一般要件（すべての移行）
1. **バージョンを伴う**：移行は `schema_migrations(version, from_version, applied_at, checksum)` に記録し、`PRAGMA user_version` を更新する（現状は無い：G-02）。
2. **事前にバックアップ**：移行前の完全な複製を作り、`integrity_check` が ok であること（`RevisionStore` は既にスキーマ変更の前に `snapshot` を取る）。
3. **行を失わない**：移行前コピーの追記専用12テーブルの全行が、移行後に**同じ内容で**ある（DB-09）。列・テーブルの削除は、同じ内容を別の場所に移した証拠（対応表）が無ければ失敗。
4. **追加を先に（expand → migrate → contract）**：新しい列・テーブルを足し、データを移し、検証してから、古いものを廃止する。廃止は別の移行・別の合意。
5. **原子的**：1つの移行は1トランザクション。途中で失敗したら移行前のまま。
6. **冪等**：同じ移行を2回実行しても、2回目は何も変えない。
7. **ドライラン**：コピーで実行し、前後の `db_audit`（fail 0）と行数の差分を報告してから本番に適用する（本番の変更はユーザーの許可後）。
8. **逆方向**：移行後に問題が見つかったとき、バックアップから復元して DB-09 が pass（`tests/test_db_acceptance_normal.py` の復元の試験）。
9. 記事・根拠の**ID を変えない**。変える場合は旧IDの対応表を移行に含め、旧IDで引ける。

## 2. v0.3 → v0.5（実績：追加のみ）
7テーブル追加、既存14テーブルの列・テーブルは不変。合成DBで前後 DB-09 が pass（`test_moving_from_the_v0_3_schema_to_v0_5_only_adds_and_loses_no_row`）。**次の世代もこの試験（`test_the_delivered_schemas_have_not_lost_anything_since_the_previous_generation`）に通ること。**

## 3. v0.2（正規化型）→ v0.5（平坦型）：未解決の世代の断絶（G-01）
| v0.2 | v0.5 の相当 | 状況 |
|---|---|---|
| `universities` `academic_units` `admission_routes` | `admission_cycles` の `university` `faculty` `department` `admission_method`（文字列） | 大学・学部の**独立した行**が無い。ID から文字列へ |
| `admission_cycles(id, route_id, entry_year, round_name)` | `admission_cycles(case_id, …, fiscal_year, exam_year)`＋`cycle_dimensions(round_name)` | 主キーが入れ替わる。`round_name` は別テーブル |
| `source_documents(id, kind, issued_at, …)` + `source_snapshots(content_sha256)` | `source_documents(sha256, url, retrieved_at)` | 公表日（`issued_at`）と種別が失われる（G-06） |
| `fact_claims` + `fact_evidence(locator, excerpt)` | `facts`（record_json に proofs） | 27事実は `legacy_fact_links` で照合（Work 報告 [W]：未再現） |
| `article_plans` / `article_versions(version_no, review_status, approved_at)` / `article_version_facts` | `article_versions(article_id, publish_allowed=0)` / `article_evidence` | 企画と承認の状態が失われる（G-08） |
| `publications(idempotency_key, external_url, publish_status)` | **無し** | P7 で再導入が必要（冪等キーの設計は再利用できる） |
| `audit_events` | `update_events`（更新のみ） | 一般の監査イベントは無い |
要件：v0.2 → v0.5 を行うなら、(a) 全行の対応表、(b) v0.2 の `publications` と `review_status` を失わない保存先、(c) 旧 `id` で新 `case_id` を引ける対応、(d) 前後の `db_audit`。**現状この移行は未実施で、必要かどうかは Work とユーザーの判断**（v0.2 のデータは2サイクル・27事実のサンプル）。

## 4. 将来の変更で追加する要件（提案）
- 改訂記事の関係表（G-07）、公式公表日・種別（G-06）、改訂理由（G-11）、承認・公開の状態（G-08）、索引（G-03）、NULL 学科の索引（G-04）、追記専用トリガー（G-09）。それぞれ**追加のみ**で、既存行は不変。
- トリガーを足したあとは、移行ツール自身が旧行を更新できなくなる点に注意（移行は新しいテーブルへの追加で行う）。
