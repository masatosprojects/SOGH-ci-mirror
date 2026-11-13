# DB 現状監査（P1）— 何が実装され、何が確認でき、何が確認できないか

作成: 2026-11-01。**推測を完成扱いにしない**ための記録。根拠の種類を5つに分ける（本文の各項目に付ける）：
**[C]** GitHub のコードから確認　**[S]** GitHub のスキーマファイルから確認　**[D]** GitHub のサンプルデータで再現　**[W]** Work の報告（独立再現していない）　**[R]** ローカル実DBが必要で**確認できない**。
機械可読な結果は `reports/db-audit/`（`python -m src.db_contract.reports` で再生成）。実DBは手元に無い。**Work のローカル実DBがここにある2つのスキーマと同じである保証は無い。**

## 1. リポジトリにあるデータベースの3世代（[S]・[D]、`reports/db-audit/schema_*.json`）
| 世代 | 入手元 | テーブル | 外部キー | 索引（PK/UNIQUE 以外） | 実データ |
|---|---|---|---|---|---|
| **v0.2（正規化型）** | `work-db-v02-20261101/data/admission_media_v0_2.sqlite.gz`（実際のSQLite） | 17 | 20 | 6 | 大学2・サイクル2・事実27・記事版6・投稿0 |
| **v0.3/v0.4（平坦型）** | `work-national-v1/database-schema.sql` | 14 | 15 | **0** | なし（スキーマのみ） |
| **v0.5（平坦型＋版管理）** | `work-updates-v2/database-schema.sql` | 21 | 24 | **0** | なし（スキーマのみ） |

- v0.2 → v0.3 は**世代の断絶**：14テーブルが無くなり（`universities` `academic_units` `admission_routes` `fact_claims` `fact_evidence` `source_snapshots` `article_plans` `article_series` `article_version_facts` `publications` `audit_events` `selection_stages` `experience_*`）、共通の3テーブル（`admission_cycles` `article_versions` `source_documents`）も**主キーと列が入れ替わった**（`id`→`case_id`／`sha256`／`article_id`）。移行経路は `legacy_*` の取り込み（27事実の照合）だけで、v0.2 の `publications`（冪等キー付き）、`article_plans` の状態、`review_status` に当たるものは v0.3 以降に無い。
- v0.3 → v0.5 は**追加のみ**（7テーブル追加、削除と列の変更なし）。後方互換 [S]。
- どの世代にも `schema_migrations` が無い。v0.3 以降は `schema_versions(version)` に版名を入れるだけ（適用日時・チェックサム・元の版なし）。

## 2. コードから確認できた動作（[C]、`research/inbox/work-updates-v2/pipeline/admissions_pipeline/{store,revisions}.py`）
- 取り込み `EvidenceStore.ingest`：`BEGIN IMMEDIATE`、`INSERT OR IGNORE`、**同じ `evidence_id` で内容が違えば `ValueError`（不変）**。`save_article` も同様（記事版は不変）。
- `RevisionStore`：作成時に**スキーマ変更の前にバックアップ**（`snapshot`）。`stage` は候補（`candidate`）を作り `input_sha`（入力・登録簿・有効版・refresh のハッシュ）に結ぶ。越境（大学・学部・学科・方式・年度の不一致）、親の別事実・別サイクル、論理ID変更、同ID内容違いは拒否。
- `finalize`：`BEGIN IMMEDIATE`、候補のみ承認可、登録簿ハッシュ一致、**有効版が `stage` 時から変わっていれば拒否（同時更新）**、QA 成功かつ入力・記事ハッシュに結合、記事は `publish_allowed=False`、引用の集合が `evidence_ids` と一致、引用は同サイクル。
- `recover_candidates`（中断した候補を `interrupted` に）、`rollback_batch`、`pack` は有効な更新があるサイクルを拒否（旧経路で更新を落とさない）。`ProcessLock`（カーネルのロック）。
- ここまで [C]。**独立再現 [D]**：`tests/test_audit_work_v2.py`（27件）と `tests/test_db_acceptance_*.py` が**合成DB**で Work のコードを動かして確認（種別 `synthetic`）。

## 3. 監査 CLI の結果（[D]、`src/integration/db_audit.py`）
| 対象 | 種別 | 結果 |
|---|---|---|
| v0.2 サンプルDB | repository_sample | 合格：DB-01、V02-02〜04（スナップショットのハッシュ、検証済み事実に公式の根拠、記事版は同サイクルの事実のみ）。`V02-05`（投稿）は行が0で **not_run** |
| 全体ビュー＋基底状態を v0.5 スキーマに投入（`load_export`） | repository_sample（**派生**。Work のDBではない） | 合格：DB-01〜08、11、12（根拠46＋改訂5、記事13、改訂6）。DB-09（旧コピーとの比較）、DB-10 は not_run |
| **全納品を一緒に投入** | repository_sample（派生） | **失敗**：同じ一般選抜の事実6件が2つの根拠ID空間（`EV-G27-*` と `EV-G27C-*`、内容は同一）に存在し、`UNIQUE(case_id, source_sha256, fact_key)` が2つ目を拒否する。ID再利用の検査（`fullview`）はIDが違うので見えない。→ ギャップ G-05 |

## 4. 確認できない項目（[R]：ローカル実DBが必要。**推測で埋めない**）
- 実DBが v0.5 と同じスキーマか、実際のテーブル・行数・索引、`schema_versions` の中身。
- 実DBの有効版（`evidence_heads` / `article_heads`）、`update_batches` の履歴、`candidate` の残り。
- 実DBでの更新・中断・復旧・冪等性（合成DBでの再現は実DBでの検証ではない）。
- 実DBの旧行保全（DB-09 は旧コピーが無いと実行できない）、容量・性能（索引が0であることの影響）。
- 原典（PDF/HTML原本）との照合（`original_source_comparison` は常に `not_run`）。

## 5. 実装済み／未検証／不足の一覧
| 項目 | 状態 | 根拠 |
|---|---|---|
| 識別子（大学・学部・学科・方式・入学年度・実施年度） | 実装済み（v0.3+）。**学科 NULL の重複を UNIQUE が防がない** | [S] `UNIQUE(university,faculty,department,…)`、監査 DB-02 |
| 原典と事実の対応（URL・sha256・取得日時・引用位置） | 実装済み。**公表日なし。種別（pdf/html）は record_json のみ** | [S][D] |
| 根拠の版と有効版 | 実装済み（v0.5）。親版・有効版・不変チェックは**コードのみ**（トリガーなし） | [S][C] |
| 記事の版と有効版 | 実装済み。**改訂記事と根拠の関連はテーブルに無い**（record_json のみ） | [S] |
| 承認・公開の状態 | **v0.3+ に無い**（`publish_allowed=0` 固定）。v0.2 には `review_status`・`publications` があった | [S] |
| 更新の原子性・同時更新・冪等 | コードで実装、**合成DBで再現** | [C][D] |
| バックアップ・ロールバック | スキーマ変更前の `snapshot`、`rollback_batch` | [C][D] |
| スキーマ移行履歴 | **不十分**（`schema_versions` のみ、適用記録なし） | [S] |
| 索引 | **v0.3+ は 0**（PK/UNIQUE の自動索引のみ） | [S] |
| 実DB | **確認不可** | [R] |
