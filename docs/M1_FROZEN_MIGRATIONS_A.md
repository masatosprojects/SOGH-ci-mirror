# M1 凍結 SQL への再発行（その 1）：0002（G-04）・0003（G-05）と、スキーマ状態の検証（Claude の代行、2026-11-02）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** 根拠：`docs/architecture/M1_SAFE_MIGRATION_PLAN.md` の段 2・3、`M1_DESIGN_DECISION_MATRIX.md` の M-06・M-08・M-10。**どの運用DB・原本・監査コピーにも適用していない。使い捨てクローンだけ。** M1 は 2/8、**NOT ACCEPTED** のまま。

## 何を変えたか
| 項目 | 変更 | 直した欠陥 |
|---|---|---|
| 凍結 SQL | `src/db_contract/migrations/0002_*.sql`・`0003_*.sql`。定義の checksum＝**ファイルのバイト列の SHA-256**。実際に実行した文の番号を `schema_migrations.applied_statement_ids` に記録（系統によって適用しない文があるため） | M-06 |
| 0002 offering | 同一性は case・round・入学月（NULL＝未特定）・scope。**原典を外す**。`offering_sources`（追記専用）で offering と原典を結ぶ。既存 offering の原典は移行時に 1 行ずつ追加。`INSERT OR IGNORE` で捨てられる改訂資料の offering も、トリガーが原典の関係を追加する。同じ offering に 2 原典が既にある DB は移行を止める（preflight） | D7 |
| 0003 root | `v_evidence_root`（再帰ビュー、任意の深さ）、`v_evidence_orphans`（root を持たない系列を列挙：黙って消さない）。固定版の判定は世代数でなくビューで行う | D6 |
| 関数 | `root_of`（系列の root。引用・読み取りの版ではない）、`read_version`（alias は固定版か現行 head）、`resolve`（旧名、`read_version` と同じ）。改訂版 ID は自身の版を指し、root は本来の root | D6 |
| スキーマ状態 | `verify_schema_state`：適用済み移行が作った全オブジェクトを `sqlite_master` と（空白を正規化して）照合し、欠落・編集・名前空間内の未知のオブジェクトを報告。記録された適用 SQL の SHA を、凍結ファイルの該当文と比較。`plan` と `apply` が毎回実行し、ずれがあれば適用を拒否 | D5 |
| 監査 | `db_audit` に **DB-16**（全 revision に root がある。ビューを使わない独立の再帰クエリ）と **DB-17**（スキーマ状態） | D5・D6 |

## 検証
| 何を | 結果（区分） |
|---|---|
| 全体試験 | 後述の件数（`SELF_VALIDATED`、合成 DB） |
| D5：トリガーの削除・弱体化・名前空間内の未知の追加・適用 SQL の編集をすべて検出し、`apply` が拒否 | 合格（合成）。修正前の特性化試験を反転（`test_fixed_d5_*`） |
| D6：6 世代目・100 世代の固定版を受理、他の root の版は拒否、改訂版の root が本来の root、巡回系列が孤児として列挙される | 合格（合成）（`test_fixed_d6_*`） |
| D7：同じ offering の 2 つ目の原典は offering を増やさず、関係に追加される。移行前の offering の関係を補う。既存の重複は移行を止めファイルを変えない | 合格（合成） |
| **実コピー v06 のクローン**（既存の追加型監査 14 ケース） | **14 合格・0 失敗**、`offering_sources` の行数＝offering の行数、スキーマ状態の問題 0、DB-16・DB-17 pass、旧行は 1 行も変わらず、監査コピーの SHA は不変 |

記録：`reports/db-audit/real_copy_additive_frozen_a_2026-11-02.json`。

## 限界・次
- 0004（G-09）はまだコードが生成する旧案で、**D1〜D4 は未修正**。次の PR が凍結 SQL（能力ゲート・承認済み head だけ・`recursive_triggers` 前提）に置き換え、PR #76 のパッチ版の更新経路で g4 を再実行する。
- 再帰ビューの全国規模の性能は NOT_RUN（実コピーは 5 case）。G-03 の索引（`evidence_revisions(parent_evidence_id)` など）は後の移行。
- `cited_version`（記事が引いた版）は G-07 の関係表と同時に実装する。
- Work の独立レビュー前。運用DBへの適用は別の承認が要る。
