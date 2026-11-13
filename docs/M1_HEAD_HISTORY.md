# M1 過去時点の取得：`head_history`／`read_as_of`（M-14、Claude の代行、2026-11-02）

**ラベル：`SELF_VALIDATED`・`WORK_REVIEW_PENDING`・`USER_APPROVAL_REQUIRED`（運用への適用）。** どの運用DB・原本・監査コピーにも適用していない。M1 は 2/8、**NOT ACCEPTED**。

## 何ができるようになったか
過去のある時点で、どの根拠の版が head だったかを、**記録された出来事から再生**して答える（head の履歴を別に持たない）。承認のたびに `update_batches.after_json` が**その時点の head の全体**を保存し、rollback は `before_json` の状態へ戻す。この 2 種類の出来事を順に並べたのが移行 `0009` の `v_head_events`（行は変えない）。
- `heads_as_of(db, 時刻)`：その時刻までの最後の承認／rollback が作った head（根拠・記事）。何も無ければ空。**候補・中断・却下の batch は head だったことがないので現れない。**
- `read_as_of(db, logical_id, 時刻)`：その時点の根拠の版（無ければ `None`）。**記事が引いた版にはこれを使わない**（記事は引いた版のまま：`cited_version`）。
- **DB-18**：現在の head ＝ 記録された承認・rollback の再生（最後の出来事の状態）。承認で説明できない head、または記録された承認が head に出ていない場合は**失敗**。能力を持つ接続が head を書き換えても（D2 の限界）、ここで**検出**される。承認の記録が一度も無い系統は `not_run`（**pass にしない**）。

## 検証（`SELF_VALIDATED`）
- 合成：`tests/test_head_history.py`（5）：承認 2 回と rollback の各時点（承認前＝空、最初の承認後、訂正の承認後、rollback 後）、候補・中断・却下は現れない、head の削除を DB-18 が失敗として検出、承認の記録が無い系統は `not_run`。全体 1123 件成功。
- **実コピー v06 の使い捨てクローン**：追加型監査 **20/20**（新規 E1：再生＝現在の head〔証拠・記事とも〕、最初の承認より前は空、DB-18 pass）、g4 **22/22**（9 本の移行チェーン）。監査コピーの SHA は不変。記録：`reports/db-audit/real_copy_head_history_2026-11-02.json`。
- 副作用の修正：`load_export`（参照用ローダー）と `test_db_audit` の合成データは、承認が作った head の状態を `after_json` に記録するようにした（以前は `{}` で、承認と head が食い違っていた）。

## 限界
公開の更新 API の `effective_at` 引数は**未実装**（読み取り側の関数のみ）。再生は記録された出来事の精度に依る。全国規模の性能・ディスク満杯・電源断は NOT_RUN。Work の独立レビュー前。
