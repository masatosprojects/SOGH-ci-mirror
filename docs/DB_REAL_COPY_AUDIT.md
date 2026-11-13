# 実DB5世代のコピーの独立監査（Work PR #59、2026-11-01）

対象：Work PR #59（`research/inbox/work-db-copy`、head `20cabcef52c90ec5105f51a96b940fb117e1e9cc`）。使用した監査コード：`src/integration/db_audit.py`（Work が固定した `a6c4474` と**差分なし**）。
証拠：`reports/db-audit/real_copy_independent_audit_2026-11-01.json`（件数・ID・判定・ハッシュのみ。行の値・ローカルパスは含まない）。

## 判定：PR #59 = **PASS_WITH_WARNINGS**（M1 は NOT ACCEPTED）
監査資料としては受け入れ可能（メタデータが内部整合し、実コピーの再計算が Work の報告と一致）。ただし下の警告が残る。**PR #59 の受け入れは M1 の完成ではない。**

## 独立性の水準（混ぜない）
| 水準 | 内容 | 状況 |
|---|---|---|
| A メタデータ | PR #59 の納品物を再計算 | **実施**：215検査すべて合格 |
| B コピー実データ | Claude 自身が同一PCで5つのSQLiteコピーを読み、`db_audit` と自前の別実装で検査 | **実施**（5世代すべてにアクセス可。読み取り専用） |
| C 原典 | 公式PDF・HTMLとの照合 | **not_run** |
| D 原本DB | コピー元の原本との一致 | **not_run**（原本には触れていない。Work の報告のみ） |

## A. メタデータ（PR #59）
- `checksums.json` の42件すべてで存在・SHA-256・バイト数が一致。納品物の全43ファイルが `research/inbox/work-db-copy/` 内。未記載ファイル0（`checksums.json` 自身は自己記載でない。仕様どおり）。
- JSON構造・世代間の整合（行数、README の表、SHA の形式、重複なし）に問題なし。DDL5本を空のメモリDBで実行（INSERT/PRAGMA/ATTACH なし）：表・列が inventory と一致（v02 は索引6・トリガー2を含む）。
- 納品物にDB・PDF・大きなファイル・絶対ユーザーパス・メールアドレスは無い。
- 再現用の Work のテスト5件を別に実行：5成功。

## B. 実コピー
- 5コピーの SHA-256 を再計算：提出値（各 inventory）と**すべて一致**。監査の前後で不変、`-wal`/`-shm` なし。**v05 `b4bb9d1a…`、v06 `a8e48b5b…` も Work の記載と一致**。
- `db_audit`（`copied_real_db`、`--expect-sha256` 指定）の結果は、Work の保存した要約と**5世代すべて一致**（v06 は Work と同じ `--baseline v05` で比較）。

| 比較 | ok | pass | warn | fail | not_run |
|---|---|---|---|---|---|
| v02（normalized_v0_2） | ✅ | DB-01、V02-02〜04 | – | – | DB-09、V02-05 |
| v03 / v04 | ✅ | DB-01〜04・06・10〜12 | DB-14・15 | – | DB-05・07・08・09 |
| v05 | ✅ | DB-01〜08・10〜12 | DB-14・15 | – | DB-09 |
| **v06 vs v05** | ✅ | **DB-01〜12** | DB-14・15 | – | – |
| v05 vs v04 | ✅ | DB-01〜12 | DB-14・15 | – | – |
| **v04 vs v03（Work 未実施）** | ❌ | DB-01〜04・06・10〜12 | DB-14・15 | **DB-09** | DB-05・07・08 |
`ok=true` は「全検査を実施済み」ではない。原典比較はどれも not_run。

自前の別実装（主キーごとの全列比較）でも同じ：**v05→v06 は旧行の削除0・変更0**。追加は根拠改訂1・記事改訂2・batch 3・event 1・batch_evidence 3。動いた head は FAQ の1根拠（`tsukuba-ac-ai-faq`）と2記事（筑波AC の overview・interview）だけ。
有効ビューを DB だけから再計算：**根拠50（46 −祖先1 ＋ head5）・現行記事13（(case, series) 13組）**で Work の報告と一致。**PR #42 の納品ビューとの ID 照合は not_run**（PR #42 は再統合待ち。Work の `database-to-view.json` を独立再生成として数えていない）。
追加の独立検査（v06）：integrity_check ok、foreign_key 違反0、改訂の循環0、親の欠落0、head の欠落0、`publish_allowed` は全21記事で0。

## 警告・所見（Work への依頼）
- **F-1（警告）privacy_report の漏れ**：v05・v06 の `update_batches.qa_json` に、ユーザーのローカルパスを含むセルが 13／14 件あるが Work の privacy_report に無い。原因は Work のパターン `user_path` が区切り文字1つしか許さず、JSON内の二重バックスラッシュに一致しないこと。値は出さない。他の列の件数（artifact_path 12 ほか）と email（6セル、分類は ac.jp が主。公式連絡先かの確認はしていない）は一致。
- **F-2（所見）v03→v04 は追記専用でない**：事実5件が上書き（`profile_version`、うち1件は値から `exam_year` キーが消えた）、記事6版が置換、`article_evidence` 24行・`cycle_editions` 1行が消えた。v04→v05・v05→v06 は旧行を保全。Work はこの組を比較していない。開発途中の上書きだったのか、受容できるかの説明が要る（g3）。
- **F-3（既知・未解決）**：G-04（学科が空のサイクル1件）は v03〜v06、G-05（同じ原典・fact_key・値が2つの case_id）は v04〜v06 に**実在**。解消も受容もされていない（g1）。
- **F-4（軽微）**：`reproduction/inventory_real_databases.py` は整合性・同一性の検査が失敗したとき、書きかけ／未検証のコピーを残す（再実行は上書きを拒否する）。空き容量不足の明示的な扱いも無い。

## M1 の8ゲート（0/8 → **1/8**）
| ゲート | 状態 | 今回の証拠・未達 |
|---|---|---|
| g1 識別 | 未 | DB-02/04/10 は実コピーで pass。**G-04・G-05 が未解消** |
| g2 原典 | 未 | DB-03/04/12 は pass。**原典照合 not_run** |
| g3 保全 | 未 | v05→v06 の DB-05/06/07/09 は pass（独立）。**F-2、G-07・G-09・G-11 が未解決** |
| g4 更新の安全性 | 未 | 実コピーでの中断・復旧・冪等・同時実行は未再現 |
| g5 移行 | 未 | v05→v06 は更新で、移行の実行ではない。v0.2 は保留のまま |
| g6 影響分析 | 未 | 更新→記事改訂の一気通貫は未実施 |
| g7 新様式 | 未 | 未実施 |
| **g8 独立監査** | **✅（範囲：コピーまで）** | Work の結果を5コピーで再計算し一致、差（F-1）は原因つきで説明。**原本・原典は含まない** |

**M1 NOT ACCEPTED**。g8 の合格は「Claude が実コピーで Work の結果を再計算できる」ことの確認であり、DBが正しいことの証明ではない。

## 更新：PR #59 の最新 head `4dd4cf5` の差分の独立確認（2026-11-01）
記録：`reports/db-audit/real_copy_independent_audit_pr59_delta_2026-11-01.json`。判定：**PASS_WITH_WARNINGS**（変更なし）。
- **F-1 修正済み**：Work の privacy_report の user_path は v05 が 36、v06 が 37 セルで、Claude が別に数えた値と**一致**（`update_batches.qa_json` が 13／14）。v02〜v04 の報告は不変。訂正記録のハッシュは実ファイルと一致。値は出していない。
- **F-4 修正済み**：コピーは `.partial` の名前で作り、整合性・外部キー・同一性の検査の後にだけ改名。バックアップ前に空き容量を確認。中断時は `copy_failure.json`。同梱テスト 8 件を別実行して 8 成功。
- **F-2 は記録されたが未説明**：Work の比較は件数（`article_evidence` 24・`article_versions` 6・`cycle_editions` 1・`facts` 5）も変更列も Claude の独自比較と一致。Work は原因を「現在のコードと保存された履歴からは確認できない」とし、追記専用の移行とは主張していない。**この上書きを受容するかはユーザーの判断**。
- 納品物のメタデータ 227 検査合格、`research/inbox/work-db-copy/` の外の変更なし。コピーの SHA は不変で、Work が別ディレクトリに取り直した 2 回目も同じ SHA。
- **未解決**：F-2 の原因、F-3（G-04・G-05）、原本DBとコピーの一致・公式原典（not_run）。**M1 のゲートは変わらない（1/8）。**

## PR #63（Work W-07）の独立監査：M1.g4（2026-11-01）
対象：PR #63 の head `54e4f9c`（`research/inbox/work-copy-faults/` のみ。manifest の4ファイルは SHA・バイト数が一致、未記載ファイルなし、DB・PDF・絶対パスなし）。固定QA：master `36bf15a`（`db_audit` は Work の `a6c4474` と差分なし）。記録：`reports/db-audit/real_copy_g4_audit_pr63_2026-11-01.json`、harness：`src/integration/real_copy_g4_audit.py`。
- **Work の6ケース**：Work の駆動を Claude が別に実行して 6/6（これは Work の駆動の判定で、Claude の計算ではない）。
- **Claude の harness（全ケースが毎回新しい使い捨てコピー。原本のコピーは読み取り専用で SHA 不変）**：検証は Claude が計算 — 全表の全行を元のコピーと比較し、期待する追加・head の移動だけが起きたことを確認、v05 のコピーの head を基準に照合、`db_audit`（DB-09）、integrity_check、外部キー。**21 成功・0 失敗・既知の限界 1**。
  - 中断・復旧：未コミットの書き込み中の異常終了（hot journal が回復）、候補の保存後の異常終了と `recover_candidates`、**承認の文の途中の異常終了**（head 不変）、承認の後のロールバックと2回目の拒否。
  - 冪等・重複：同じ入力2回（`no_change`、業務の記録は増えない）、重複した論理 ID の拒否。
  - 同時実行：別プロセスが head を戻した後の finalize 拒否（相手の head を上書きしない）、ロック、**同時刻の2書き込みを3回**（直列化され破損なし）。
  - 不正データ：スコープ違い、別事実の親、同じ ID で別内容、QA 結果の不一致、公開可の記事、拒否済み batch の finalize、他 case の引用、使えないバックアップ先。**すべて原子的に拒否され、旧行・旧 head は不変**。
  - 有効な承認の経路：動いたのは対象記事の head だけで、旧行はすべて保全（DB-09 pass）。
- 初回の実行で1件失敗した（`db_audit` の DB-06 が、Claude の合成した記事の ID に revision hash が無いことを正しく指摘）。**Claude の試験設計の誤りで、Work の欠陥ではない**。harness を直して再実行した。
- **未実施（not_run）**：ディスク満杯の更新中、電源断・OS の異常（プロセスの異常終了だけを注入）、kill によるバックアップの中断、原本DB・公式原典。
- **既知の限界（G-09）**：DB 自身は head への直接の書き込みを止めない（トリガーなし。`db_audit` の DB-14 は警告）。更新経路は保護するが、迂回した書き込みは止まらない。**合格に数えない**。g4 の正式な条件には含まれず、g3 の課題。
- **M1.g4 の判定：合格（範囲：コピー上の更新経路。コピー・原本・原典の区別を保つ）。M1 は 2/8（g4・g8）。M1 NOT ACCEPTED。** スキーマの追加（G-04・G-05・v0.6）の後は、同じ harness で再実行する。

## PR #61（Work W-02）の独立監査：stage 契約 A の候補（2026-11-01）
対象：PR #61 の head `c0c8e75b`（`research/inbox/work-stage-a/` のみ、manifest 9 ファイル一致）。記録：`reports/db-audit/real_copy_stage_audit_pr61_2026-11-01.json`、harness：`src/integration/real_copy_stage_audit.py`。判定：**PASS_WITH_WARNINGS**。**`stage` は「引用文が使ってよい選考序数」であり、面接の実施段階ではない**（PR #64・Work の WR-01）。
- **候補**：有効ビュー 50 根拠・13 記事のうち、置き換わるのは 2 根拠（interview の親 `EV-T27-04-49cb4d`、fee_refund の親 `EV-U-2895dfe26d3b`）だけで、他の 48 根拠は完全に同一。候補の値・証拠・スコープ・年度・原典 SHA は親と同じで、変わるのは `stage:[1]`・新 ID・`parent_evidence_id` など。候補 ID は DB に無く（旧 ID の再利用なし）、親は現行の版。**旧 ID の改名なし**。
- **記事**：変わるのは 2 本（筑波 AC の overview・interview）だけで、本文の違いは引用 ID の置換のみ、他 11 本は同一。親記事は v06 の現行 head、`revision_hash` は Work の式と一致、`publish_allowed=false`。
- **原典**：保存した公式 PDF を別の抽出器で読み、SHA-256 が一致、全ての引用が引用のページに在り、「第 1 次選考」を名指す引用がそれぞれ在る。fee_refund の PDF は DB の `source_documents` に**未登録**（保存ファイルは Work の出力に在る）。
- **変異（Claude の既存 helper と自前のループ）**：序数の入れ替えの検出は **10/14 → 14/14** を独立に再現。新しく検出されるのは対象 2 記事の 4 件。正常な本文に新しい指摘は出ない。
- **負例**：候補の stage を [2] に改ざんすると元の文が指摘される／stage を外すと盲点に戻る／[1,2] は両方を許す。**Claude の QA の盲点を発見**：入れ替えを漢数字（「第二次」「二次選考」）で書くと 0/14 で見逃した → **Claude 担当の序数の読み取りを修正**（漢数字 一・二、「第二次世界大戦」「一次情報」等は除外）し、試験を追加。修正後は 4 つの書き方すべてで 14/14。
- **使い捨てコピーでの有効化（Claude の harness、`SELF_VALIDATED`）**：8 成功・所見 1。有効化で増えるのは根拠改訂 2・記事改訂 2 などの追記と head の移動だけで旧行の削除・変更 0（DB-09 pass）。クローンから再計算した有効ビューが候補のビューと一致。同じ候補の再実行は `no_change`。ロールバックで元の head に戻り 2 回目は拒否。QA 拒否で head 不変。年度違い・別事実の親は原子的に拒否。
- **所見**：fee_refund の原典 SHA が `source_documents` に未登録（更新経路はこれを止めない。`evidence_revisions` に外部キーが無い）→ g2。
- **運用DBへの有効化は未実施・未承認**（Work の判断とユーザーの承認が要る）。**Issue #12 は閉じない。M1 のゲートは変えない。**
