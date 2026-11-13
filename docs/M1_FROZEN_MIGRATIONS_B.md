# M1 凍結 SQL への再発行（その 2）：0004（G-09）のガード（Claude の代行、2026-11-02）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** 根拠：`M1_UNIFIED_DATA_ARCHITECTURE_RFC.md` §9（方式 B）、`M1_DESIGN_DECISION_MATRIX.md` の M-01〜M-04。**どの運用DB・原本・監査コピーにも適用していない。使い捨てクローンだけ。** M1 は 2/8、**NOT ACCEPTED**。

## ガードの中身（`src/db_contract/migrations/0004_*.sql`、62 文）
| 規則 | 内容 | 直す欠陥 |
|---|---|---|
| 能力ゲート | 履歴表・head・batch・識別の表への書き込み（INSERT／head と batch は UPDATE・DELETE も）は `sogh_write_ok()` を呼ぶ。**SOGH 自身の接続だけが登録する**ので、他のプログラムは `no such function` で失敗側に倒れる（読み取りは自由：`db_audit`・エクスポート） | D1・D2（外部から）・D4 |
| 追記専用 | 履歴表の UPDATE・DELETE は、**能力を持つ接続でも拒否**（ゲートに依存しない）。`recursive_triggers=ON` の接続では `INSERT OR REPLACE` の暗黙の削除も拒否される | D4 |
| head | head は**承認済み（`approved`）の batch の改訂**だけを指せる。`candidate`・`rolled_back` は不可。head の削除は SOGH 接続に許す（rollback） | D1・D3 |
| batch | `candidate → interrupted\|rejected\|approved`、`approved → rolled_back` だけ。識別列は不変、削除不可 | — |
| 生成の廃止 | 0004 は**生成せず凍結ファイル**。ファイルが `src/db_contract/guard_sql.py` の出力と一致することを試験が固定（表の一覧とファイルのずれを防ぐ） | D5 |

**ランナー**は自分の接続に能力を登録する（移行中の補充・履歴の書き込みのため）。`register_alias` も、分類した上で書く正規の書き手として接続に能力を登録する。

## 直ったこと・残ること
| 欠陥 | 状況 |
|---|---|
| D1 candidate を head に | **修正**（SOGH 接続でも拒否。配布版の `finalize` は head を先に書くため拒否される＝PR #76 のパッチが先に要る） |
| D3 rolled_back の根拠を head に | **修正** |
| D4 `INSERT OR REPLACE` | **修正**（SOGH 接続は pragma ON で拒否、他のプログラムはゲートで拒否）。**限界**：能力を持つが pragma を忘れた接続は上書きできる（事後の DB-09 で検出） |
| D2 偽造した QA による承認 | **限界として残る**：能力を持つ接続は承認を偽造できる。外部のプログラムからは拒否される。**QA 結果の署名（G-08）が最後の手段**（鍵の管理は未決） |
| 検出であって防止でないもの | 能力関数を登録できる主体・ファイルを書き換えられる主体は止められない。トリガーの削除・編集は `DB-17`／`plan` が検出し、`apply` が拒否する |

## 検証（`SELF_VALIDATED`）
- 全体試験（合成 DB）：`tests/test_guard_migration.py`（7）、g09・追加型・反証の各試験を最終ガードで更新。テストの既定は、**配布版 v3 パイプライン＋段 1 のパッチ（一時コピー）**に変えた。
- **実コピー v06 の使い捨てクローン**：g4 の 22 ケースが**最終の移行チェーン（0002〜0004）の上でパッチ版の更新経路を通して 22/22**（X10：head への直接書き込みも拒否）。追加型監査 15/15（新規 B7：能力のない素の接続の書き込み・REPLACE・偽造は全て拒否、行は不変）。監査コピーの SHA は不変。
- 記録：`reports/db-audit/real_copy_frozen_b_2026-11-02.json`。

## 限界・次
- 配布版（パッチ前）の Work のコードは、このガードの下では動かない（`behaviour_work_stage1.py`）。**パッチの取り込みが運用への適用より先**。
- G-07（記事と根拠の版）・G-11（理由）・G-06（原典メタデータ）・索引は次の凍結 PR。全国規模の性能・ディスク満杯・電源断は NOT_RUN。Work の独立レビュー前。
