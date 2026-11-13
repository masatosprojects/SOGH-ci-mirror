# PR #135（Work の MRIF-1 Phase 1）の独立レビュー（2026-11-04）

**対象：** PR #135 `work/interview-room-synthetic`、head `38bb41c85da6df8652e35cb8943182c79840cc31`（Draft、base `372ff43`）。Claude は統合していない。Work のファイルは編集していない。
**判定：`PASS_WITH_WARNINGS`**（Phase 1 の核として。R2・R3・R7 の Claude の最小決定のうち、台帳・時計の橋・失効は**まだ未実装**で、Work 自身もそう書いている）。M1 は 2/8、NOT ACCEPTED のまま。
**環境：** Windows・Python 3.12.0、一時領域 `D:\sogh-work\tmp`（C: には置かない）。**ローカルの検証で、GitHub Actions の成功ではない。** Linux・Python 3.11 は未実行。

## 1. 実施したこと
- 差分：`research/inbox/work-interview-room/` の 7 ファイル（781 行追加）のみ。`sandbox/`・`tests/`・`docs/`・CI・DB・原典・既存 5 PR の変更なし。
- `mrif.py`（292 行）を全文読了。
- Claude の独立試験 `tests/test_pr135_mrif1_review.py`（28 件、Work の試験は呼ばない）：Work の `mrif.py` に対して**28 件成功**。試験の感度は変異で確認：①`accepted=False→True`（再送）②再送の改変検出を無効化 ③世代の先行チェックを削除、のそれぞれで失敗する（③は下の既知の差異を固定した試験が検出）。
- 全体（`scripts/local_ci.py`、master＋PR #135 の合成）は別途実行（結果は PR コメントに記載）。

## 2. 確認できた点（`PASS`）
| 観点 | 結果 |
|---|---|
| R1 質問の正本 | 3 つの架空ケースで、コントローラ経由の質問列・フィードバックが `InterviewSession` を直接使った結果と一致。Engine の private は使っていない（`_engine.` の属性は公開 API のみ。ソースの AST で確認） |
| 外部通信・永続保存 | 標準ライブラリ＋`interview_sandbox` のみを import（AST）。全試験を `socket` 禁止で実行して成功。設定は凍結で、外部機能を有効にする値はすべて `ValueError` |
| 重複と改変 | 同じキー＋同じ内容の再送は Engine を呼ばず最初の結果を返す。同じキー＋違う内容（本文・経過秒）は `idempotency_conflict`。1 つの `event_id` に 2 つ目の操作は載らない。他セッション・古い世代・古いターンは効果なしで拒否。8 スレッドの同時送信でも確定は 1 回 |
| 経過秒 | `True/False/1.5/"5"/None/-1/3601` はすべて拒否で状態不変 |
| 部分回答 | Engine に届かない（回答数・残り時間が不変） |
| 回答不足 | 0 件・1 件で既存の「判定できません」を生で返し、偽の根拠を作らない |
| 保持 | retry は新しいセッション ID・前の回答を引き継がない。返したオブジェクトを書き換えてもセッションは変わらない。回答の連絡先文字列は保存ターンで伏せられる |

## 3. 警告と既知の差異
- **W-1（R2、固定済み）再送の `accepted=False`**：再送は「確定済みの操作の確認応答」なので、Claude の決定では `accepted=True`・`replayed=True`。Work は意味の確認を依頼していた。→ **`accepted=True` にすることを推奨**（`test_known_issue_pr135_a_replay_is_reported_as_accepted_false` で現状を固定。Work が変えたら反転）。
- **W-2（R2、固定済み）割り込み後の再送**：確定済みの回答を、世代が進んだ後に再送すると `stale_generation`。Claude の決定は「キーを先に見て確認応答を返す」。状態は正しい（二重適用なし）が、送り手が「失敗した」と誤解し得る。→ キーの検査を世代の検査より先にすることを推奨（`test_known_issue_pr135_a_replay_after_an_interruption_...`）。
- **W-3（R2）`seq` の台帳がない**：欠番のない確定順の台帳と `error` イベント（上限 50）は未実装。Work も「新 TurnEvent・順序欠番は未実装」と明記。**Phase 1 の完了条件ではなく次の単位**。
- **W-4（R3）時計の橋がない**：`FakeClock` は進めても Engine の時間は進まない（Work が明記）。呼び出し側が整数の `elapsed_seconds` を直接渡す互換経路のみ。累積の床による導出、無回答の期限（猶予 120 000 ms）、`tick` は未実装。→ 次の単位。参照の意味は `tests/phase1_reference.py` と `tests/test_phase1_reference_contracts.py`。
- **W-5（R7）失効**：再接続 TTL・フィードバック表示 TTL による全破棄は未実装（切断状態自体がない）。
- **W-6** `event_id` は呼び出し側が渡す（Claude の決定ではコントローラが付与）。害はなく、衝突検出もある。次の単位で合わせる。
- **W-7** `retry()` は一度新しい `InterviewSession` を作ってから差し替える（無駄だが無害）。
- **W-8（容量）** Work の実行は D: の専用ディレクトリと G: の複写で、C: の下限 300 MiB を監視している。ただし C: の消費の原因は未特定のままで、Work の消費と断定できない。

## 4. 実行していないこと（`NOT_RUN`）
GitHub Actions の CI、Linux、Python 3.11、人による意味・使いやすさの確認、実音声・映像・LLM、TurnEvent の wire 契約、複数タブ、strict な無回答期限、V2 フィードバック変換。

## 5. Work への依頼（最小）
1. W-1：再送を `accepted=True, replayed=True` にする（または意味を文書に固定して Claude の決定を改める提案を Issue #75 に出す）。
2. W-2：キーの検査を世代の検査の前に置く。
3. 次の単位として R2 の台帳（`seq`、`error` 上限）、R3 の橋（累積の床・`tick`・猶予）、R7 の失効を、`tests/test_phase1_reference_contracts.py` と同じ振る舞いで実装する。
