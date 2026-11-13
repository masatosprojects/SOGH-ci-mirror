# DB スキーマのギャップ分析

契約（`docs/DB_ACCEPTANCE_CONTRACT_V1.md`）と、**リポジトリで確認できる**スキーマ（v0.2 サンプルDB、v0.3、v0.5）の差。実DBは確認できない（[R]）。
証拠：**[S]** スキーマ、**[D]** サンプルデータ／監査の再現、**[C]** コード。「Work の合意」が要る項目は **proposed**（独断で正規スキーマにしない）。

| ID | ギャップ | 証拠 | 影響 | 提案（契約に対して） | Work の合意 |
|---|---|---|---|---|---|
| G-01 | **v0.2 → v0.3 が世代の断絶**：14テーブルが無くなり、共通3テーブルの主キー・列が入れ替わる（`id`→`case_id`/`sha256`/`article_id`）。v0.2 の `publications`（冪等キー付き）・`article_plans`・`review_status`・`audit_events` に当たるものが無い | [S] `reports/db-audit/schema_evolution.json` | 旧データの移行は `legacy_*` 取り込みのみ。記事の企画・承認・投稿の状態が失われた | 移行の要件（`DB_MIGRATION_REQUIREMENTS.md`）。P7 で承認・公開の状態を再導入（G-08） | 要 |
| G-02 | 移行履歴が `schema_versions(version)` だけ（適用日時・元の版・チェックサムなし）。`PRAGMA user_version` 未使用 | [S] | どの版からどう移行したかを再現できない | `schema_migrations(version, from_version, applied_at, checksum)`、`user_version` | 要 |
| G-03 | **索引が0**（v0.3 以降。PK/UNIQUE の自動索引のみ）。`evidence_revisions(case_id)`、`facts(case_id)`、`article_versions(case_id)` などの検索は全走査 | [S] | 実DBが大きくなると遅い。性能は未測定 [R] | 検索に使う列の索引、`EXPLAIN QUERY PLAN` を試験に | 要（性能の合意） |
| G-04 | `UNIQUE(university,faculty,department,…)` は `department` が NULL のとき重複を許す | [S][D] 監査 DB-02 が検出 | 同じサイクルが2行できる | `COALESCE(department,'')` の UNIQUE 索引、または `department` を NOT NULL（空文字） | 要 |
| G-05 | **同じ事実が2つの根拠ID空間に存在**：一般選抜の6事実が `EV-G27-*`（DBの基底状態・全体ビュー）と `EV-G27C-*`（`samples/general`）で同一。**原因はIDの付け方**（`EV-<profile code>-<連番>-<sha6>`、内容でなく `code` と抽出順で決まる。`extract.py:89`）。01（募集人員）は引用位置の訂正があり値は同じ。記事は両方を引用していない。現行の `UNIQUE(case_id, source_sha256, fact_key)` は2つ目を拒否し、同じキーの独立した事実も拒否しうる（今は該当なし） | [C][D] `docs/G05_EVIDENCE_ID_ANALYSIS.md`、`tests/test_evidence_identity.py` | 全納品を1つのDBに入れると失敗。ID再利用の検査には見えない | 内容による同一性（fingerprint）、別名表（旧IDを上書きしない）、UNIQUE に locator を含める案、IDを内容から作る。CI は重複を警告、矛盾を失敗にする（実装済み） | **要（Work のID方針）** |
| G-06 | `published_at`（公式の公表日）が無い。`source_kind`（pdf/html）は record_json のみ | [S][D] | 「公式の公表日」と「取得日時」を区別できない（表示規約 WP0.2） | `source_documents` に `published_at`（nullable）・`source_kind` 列 | 要 |
| G-07 | **改訂記事と根拠の関連がテーブルに無い**（`article_evidence` は初版のみ。改訂は record_json の `evidence_ids`） | [S][D] | 影響する記事の特定が JSON の走査になる | `revised_article_evidence(article_id, evidence_id)` | 要 |
| G-08 | **承認・公開の状態遷移と承認イベントが無い**（`publish_allowed=0` の固定のみ）。note 下書き・公開URL・冪等キーの表も無い（v0.2 の `publications` が最後）。**方針は決定済み（`docs/PUBLICATION_POLICY.md`：編集確認・下書き保存許可・最終公開承認はユーザー本人、非公開下書きを最終承認より前に保存、9つの状態）。状態表・承認表は未合意で、既存DBには追加しない** | [S] | P7 の土台が無い | 9状態と承認イベント（article_id、revision_hash、actor、action、approved_at、content_hash、target_environment、prior/new_state、note_draft_id、冪等キー、ユーザーの証明）の追加のみの表。仕様は `src/db_contract/{publication,approvals}.py`（DBには無い）。v0.2 `publications` の冪等キー設計を再利用 | 要 |
| G-09 | 追記専用がコードだけ（トリガーなし）。別のプロセスや手作業のSQLで旧行を更新・削除できる | [S][C] 監査 DB-09 は事後に検出 | 履歴の破壊を防げず、検出のみ | 追記専用テーブルに `BEFORE UPDATE/DELETE` で `RAISE(ABORT)` するトリガー | 要 |
| G-10 | exports に実施年度が無く、`cycle_dimensions` が年を二重に持つ | [D] `load_export` が `exam_year` を仮定して明記 | 年が2か所にあるとずれる | DB-10 で一致を検査（確定）。単一の置き場にする | 要 |
| G-11 | 改訂の**理由**を持つ列が無い（`update_batches` に理由なし） | [S] | 「なぜ変えたか」を追えない | `update_batches.reason`（または `update_events.detail_json` の規約） | 要 |
| G-12 | `field_proofs` は record_json のみで、構造の検証が登録簿に無い | [S][D] | 項目ごとの原文位置の整合が監査頼み | 登録簿の契約（`proof_indices` が `proofs` の範囲内等）。先行監査では確認済み | 要 |
| G-13 | **実DBが確認できない** | [R] | M1 の合格条件を満たせない | Work がコピーを提供し、`db_audit --target-kind copied_real_db` を実行 | 要（提供） |

## 既に満たしているもの（確認済み）
v0.3 → v0.5 は追加のみ・旧行保全（合成DBで試験）、更新の原子性・同時更新の拒否・冪等性・バックアップ・QA不合格時のhead保全（合成DB）、記事の引用は同サイクル、公開不可の固定、v0.2 サンプルDBの整合（`repository_sample`）。
