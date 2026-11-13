# M1 凍結 SQL への再発行（その 3-2）：0007（G-06）・0008（G-03）— 統一設計の移行チェーンの完成（Claude の代行、2026-11-02）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** これで `M1_SAFE_MIGRATION_PLAN.md` の段 2（0002〜0008 の凍結ファイル化）が揃う。**どの運用DB・原本・監査コピーにも適用していない。使い捨てクローンだけ。** M1 は 2/8、**NOT ACCEPTED**（8 ゲートは動かない）。

## 0007：原典のメタデータと検証水準（G-06）
`source_documents` は追記専用なので、後から分かる公表日・種別・検証の状況は**別の追記専用の表**に置く。
- `source_document_metadata`（版つき）：**公表日が不明なら `NULL`＋`unknown`（推測しない。日付と確かさの矛盾は拒否）**。取得日は `source_documents` の別の列。新しい版＝新しい行（連番を強制）、最新は `v_source_document_current`。**根拠（basis）が空なら拒否**。保存されていない原典への登録は、外部キーが OFF でも拒否（トリガー）。
- `source_verification_events`：行われた確認だけを 1 件ずつ記録。水準は ①保存バイトの SHA が記録と一致 ②保存ファイルが記録と一致 ③**公式サイトでの真正性** ④内容の意味の確認（QA）。**水準ごとに別の結果（pass／fail／not_run）と証拠が要る**（証拠の空は拒否）。`v_source_verification_status` は、**確認がない水準は必ず `not_run`**：保存して SHA が一致しても、③を確認していなければ「公式原典として検証済み」とは出ない。後の fail は消えない（pass も履歴に残る）。
- 書き込みはゲート（素の接続は拒否）、更新・削除は拒否。

## 0008：索引 6 本（G-03）＋改訂記事の関係の 1 本
`evidence_revisions(parent_evidence_id)`・`(logical_id)`、`article_evidence(evidence_id)`、`facts(source_sha256)`、`update_events(batch_id)`、`batch_evidence(evidence_id)`、`revised_article_evidence(evidence_id)`。実コピーの `EXPLAIN QUERY PLAN` で全走査だった検索と、root ビュー・影響分析・監査が繰り返す検索だけ。**他は索引しない**。同名の索引が既にあれば移行は止まる（ファイルは不変）。

## 検証（`SELF_VALIDATED`）
- 合成試験：`tests/test_g06_g03_frozen.py`（9）。全体 1104 件前後が成功。
- **実コピー v06 の使い捨てクローン**：追加型監査 **19/19**（新規 D1：保存されている原典の全てで、4 つの水準すべてが `not_run`、メタデータ 0 行・検証イベント 0 件＝**何も検証済み・日付ありと偽っていない**。D2：7 つの検索が索引を使う〔5 case の小さなデータ。性能の証拠ではない〕）、g4（Work の更新経路＝パッチ版）**22/22（完全なチェーン）**。監査コピーの SHA は不変。記録：`reports/db-audit/real_copy_frozen_d_2026-11-02.json`。

## 残り・限界（`NOT_RUN` を含む）
- **実コピーの原典 3 件の未登録、公表日、公式サイトでの確認はしていない**（登録は `source_documents` への行の追加＝運用データの変更で、ユーザーの承認と原典の確認が要る。保存ファイルの存在・SHA 一致は ①②であって ③ではない）。
- 全国規模の性能・ディスク満杯・電源断は NOT_RUN。**Work の独立レビュー前**。運用への適用は別の承認が要り、**PR #76 のパッチの取り込みが先**。
- チェーン後に残る M1 の作業：`head_history`／`read_as_of`（過去時点の取得）、F-2 の条件つき受容の手続き（条件成立後・ユーザーの署名）、G-08 の署名（鍵は未決）。
