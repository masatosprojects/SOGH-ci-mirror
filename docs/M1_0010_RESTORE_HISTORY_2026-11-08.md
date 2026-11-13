# M1.g3：凍結移行 0010-g03-restore-history（復元履歴の保存先）｜Claude の実装（2026-11-08）

**ラベル：`SELF_TEST`・`INDEPENDENT_QA_PENDING`（Antigravity）・`WORK_REVIEW_PENDING`。** 受容でも適用でもない。M1 は 2/8 NOT_ACCEPTED のまま。どの運用DBにも適用していない。
根拠：ユーザーの 2026-11-08 の承認（候補A〜H。C の推奨＝`0010` として登録、rowid 表のまま、再投入は拒否）。契約：`docs/G03_READ_CONTRACT_2026-11-07.md`、`docs/G03_REPLACE_GUARD_REVIEW_2026-11-08.md`（#261）。

## 何を作ったか
| 物 | 内容 |
|---|---|
| `src/db_contract/migrations/0010_g03_restore_history.sql`（凍結、SHA-256 `35d2a68fb2f4348f2674aca196596bb34e0446d4457b7ed523bfeeb7bd1a5ec2`） | 復元履歴の 5 表（`restore_events`／`restore_revocations`／`restored_articles`／`evidence_history_versions`／`article_history_pins`）と、各表の 4 つのガード（UPDATE 拒否・DELETE 拒否・全ユニークキーと明示 rowid の REPLACE 拒否・負の rowid 拒否）＝計 20 トリガー。**行を 1 つも入れない**（表は空）。他の表の行を変えない。#261 が試験した `historical_read.history_ddl(True)` から生成した |
| `additive_schema.py` | 0010 の登録（`MIGRATIONS` の最後、`user_version` 10）。事前検査 `preflight_g03_history`：同名の表が既にあれば停止（未確認の定義を採用しない）。同名系統のトリガーが既にあれば `verify_schema_state` の『どの移行も作っていない物』として停止 |
| 試験 | `tests/test_m1_0010_restore_history.py`（59 件） |

## 番号の判断（要確認）
Work の F-2 アーカイブの SQL 候補（PR #96）は `0010` を名乗っていた（契約 `F2_G2_MIGRATION_AND_DB17_CONTRACT` では、状態 B の復元の記録は『0011 以降』）。本人の承認（C＝`0010` として登録）に従って、**復元履歴を 0010 にし、F-2 アーカイブは 0011 になる**（連鎖は先頭から順にしか進まないため）。Work のアーカイブの SQL ファイル自体は変えていない（登録はまだ無い）。それを前提にしている**Claude 側の試験**（`test_f2_archive_db17_prototype.py`、`test_pr96_*`）の番号と期待値を 0011／user_version 11 に直した。`test_pr96_*` は Work の配布物（PR #96）が無いと実行されず、**この環境では実行していない（NOT_RUN）**。アーカイブを 0010 のままにしたい場合は、この PR の番号を入れ替える必要がある（本人／Work の判断）。

## 検証（すべて SELF_TEST。合成DBと、実コピーの**複製**）
| 何を | 結果 |
|---|---|
| 凍結ファイルの SHA 固定、#261 の提案 SQL との文単位の一致（25 文）、CREATE のみ・INSERT／DROP／ALTER なし | 合格 |
| 合成DB：0009 までのコピーに 0010 を適用 → 5 表が空、トリガー 20、他の全表が行単位で不変、`schema_migrations` の旧 8 行は不変で 1 行追加、`user_version` 10、`history_preflight` 空、`history_guards_for` が空（完全に保護）、`verify_history`／`verify_schema_state`／来歴が空 | 合格 |
| 新規DBで一括適用 → 受容ゲート `verify_history_for_acceptance` が空。**0009 で止まったコピー（候補A）は『0010 が欠けている』と報告し、完全な履歴と誤認されない**（`through` 指定なら従来どおり） | 合格 |
| 二度目は no-op、`plan()` は読み取り専用で 0010 を次の手順に挙げる | 合格 |
| 同名の表／トリガーが既にある → 適用されず、ファイルは 1 バイトも変わらない | 合格 |
| 文の途中の失敗 → 全体が巻き戻り、ファイルはバイト同一 | 合格 |
| 移行後の表のガード：5 表×（UPDATE／DELETE）×（`recursive_triggers` 0／1）、7 通りのユニークキー衝突の `INSERT OR REPLACE`／`REPLACE`／`INSERT`、既存 rowid の明示指定、負の rowid、CHECK／NOT NULL（9 通り） | 合格 |
| DB-17：ガードの削除・弱いものへの差し替え・余分なトリガーを検出（`verify_schema_state` も）、DB-09 pass | 合格 |
| 変異試験：SQL 10＋コード 4＝14 個の使い捨ての変異 | **全 14 個を検出**（SQL の固定と #261 との一致を外した『振る舞いの試験だけ』では 13 個。残る 1 個『0010 の定義文を別の文に取り違える』は、固定の試験でのみ検出） |
| 既存の試験の修正：全表を数える試験に 5 表を追加、F-2 アーカイブの試作の番号、`test_head_history` | 修正済み。全体のローカルCI は下記 |
| **実コピー v06 の複製**（候補A の結果の複製に適用。原本は読み取りのみで不変） | 0010 を 1 件適用、ロールバックなし。`verify_history`／`verify_schema_state`／来歴／受容ゲートがすべて空、5 表が空、旧表の行数は不変、`user_version` 10。`db_audit`（copied_real_db）：失敗 0、DB-09・DB-17 pass、警告 2（DB-14・15、候補A と同じ）。**原本の v06 から一括で 0010 まで適用した結果と指紋が同一** |

## 残る条件・限界（g3 は受容されない）
- 5 表は**空**。復元そのもの（F-2 状態 B、30 行）、署名つき承認（候補D、本人のみ）、`restored_articles` の登録は別の工程。**この移行は復元の許可ではない**。
- 誰でも行を足せる（INSERT の能力ゲートは設けていない）。ガードは『足した行は消せず、置き換えられない』ことを守る。追記の権限（誰が足してよいか）は復元道具の承認マニフェスト側の課題で、能力は認証ではない（`F2_G2_MIGRATION_AND_DB17_CONTRACT` D2/G-08）。
- DB-19（復元の記録の検査）は未実装。Work の復元道具は未着手。
- NOT_RUN：Antigravity による独立QA、Work のレビュー（停止中）、`test_pr96_*`（配布物が無い）、Windows 以外・Python 3.11、GitHub Actions（課金によりジョブ未開始）。
- この PR の差分には #261（`2bda2f4`）と #268（`7f4ab7b`）のコミットが含まれる（0010 はそれらの上に作った。#261 の `history_ddl` と #268 の受容ゲートが前提）。**レビューは『#261・#268 の後』のコミットだけを見ればよい。**
