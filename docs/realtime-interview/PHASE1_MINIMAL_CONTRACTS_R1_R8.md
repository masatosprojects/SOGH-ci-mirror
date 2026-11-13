# MRIF-1 Phase 1：最小契約の決定（R1〜R8、2026-11-04）

**状態：`DECIDED_FOR_PHASE1`（Claude の契約判断）。** 範囲は Phase 1（架空データ・外部接続なし・費用 0・音声映像 LLM なし）だけ。後続 Phase、実 DB 接続、`fiscal_year` の写像、実音声は**未承認のまま**。M1 は 2/8、NOT ACCEPTED で、これらの決定は M1 に何も加えない。
根拠：Issue #75 の Work の返信（`#issuecomment-6608317449`、`#issuecomment-6608642875`）、`docs/realtime-interview/INTERFACE_CONTRACTS_V1.md`、既存の `sandbox/interview_sandbox/engine.py`・`feedback.py`。
機械で確かめる形：`tests/test_phase1_reference_contracts.py`（26 件、`tests/phase1_reference.py` の参照の意味と**無変更の本物の `InterviewSession`** を組み合わせる）、`tests/test_realtime_contracts_schema.py`（93 件、R4 の修正を含む）。これらは Work の実装ではなく、Work の PR を同じ観点で審査する基準。

各項目は「受け入れる案／拒否する案／修正する契約／Work が依存してよい範囲／負例試験／未解決」の順。

## R1：質問の正本 — 解決（Phase 1）
- **受け入れる**：既存 `InterviewSession` が選んだ質問だけが正式な質問。`ScriptedProposer` の候補は shadow 検査（検証器の結果の記録）にだけ使い、画面・発話・記録に出さない。エンジンの private 状態（`_open`・`_elapsed` など）は読まない・書かない（公開 API `start`／`answer`／`end`／`feedback`／`retry` のみ）。
- **拒否する**：画面と Engine で質問が食い違う構造、候補の質問が進行に影響する経路、エンジンの private への依存。
- **修正する契約**：`WORK_IMPLEMENTATION_CONTRACT.md` §5 の `QuestionValidator`／`ScriptedProposer` は Phase 1 では shadow のみ（発話に繋がない）。公開の注入点（外部提案者）は Phase 2 以降で、別に承認。
- **依存してよい**：既存の 3 つの架空ケースと、`InterviewSession` の公開 API。
- **負例**：悪意のある候補（禁止断定・unknown の肯定・他ケースの語・個人情報・2 つの質問・予算超過・偽の引用・人間の名乗り）が採用されない・発話にならない・Engine の質問列を変えない（質問列が候補の有無で同一）。
- **未解決**：外部提案者の正式採用（Phase 2、承認）。

## R2：イベントの正本 — 決定（Phase 1 の最小）
役割を分ける。
| 項目 | 役割 | 誰が決めるか |
|---|---|---|
| `event_id` | 台帳に入った 1 件のイベントの一意名（不透明） | コントローラ（コミット時） |
| `idempotency_key` | **送り手の 1 つの論理操作**の重複排除キー | 送り手（コマンドに必須） |
| `seq` | **台帳の確定順**。1 から欠番なし。コミット時にだけ付く | コントローラ。**送り手の順序は信頼しない・採用しない** |
| `generation_id` | 面接官の質問の世代。質問の発行ごとに 1 つ進む（Phase 1 は音声がないので質問単位） | コントローラ |
| `session_epoch`・`revision`・`producer_seq` | **Phase 1 では持たない**（現行スキーマに無い。未知の欄を足さない） | — |
- **受け入れる**：Phase 1 の入口は `TurnEvent` ではなく**コマンド**（`answer(session_id, turn_id, generation_id, text, now_ms, idempotency_key)`）。`TurnEvent` はコントローラが**出力**する台帳の行。送り手の送信順とサーバーの確定順を混ぜない。
- **同じキー**：同じ正規化ペイロードなら、最初の結果を `replayed:true` で返し、**Engine を呼ばず台帳に追加しない**。ペイロードが違えば `idempotency_conflict` で拒否し、最初の結果は有効のまま。
- **古い世代・他セッション・キー無し**：拒否（Engine は呼ばない）。Engine の拒否は成功として記憶しない。**世代は整数のみ**：現在の世代と等しい `int` だけを受け入れ、古い世代・**新しい世代**・欠落・`True`／`1.0`／文字列は `stale_generation` で拒否する。**確定済みの同一操作の再送は、世代の検査より先にキーを照会して最初の結果を返す**（世代が進んだ後でも `replayed=True`、台帳に追記しない）。同じキーで `generation_id` だけ違う再送は、内容が違うので `idempotency_conflict`。
- **エラーの台帳**：拒否は `error` イベント 1 件（`seq` を消費）。1 セッションで **50 件**まで。超えた分は数だけ数え、台帳は増やさない。
- **複数タブ／再接続の競合**：Phase 1 は**1 セッション 1 コントローラ**。2 つ目の接続は `session_already_attached` で拒否し、乗っ取りを認めない。`session_epoch`・`revision` は後続 Phase で、スキーマの版を上げて導入する（移行方針：現行の `additionalProperties:false` は保ち、版つきで追加。今は足さない）。
- **依存してよい**：`event_id`・`session_id`・`seq`・`generation_id`・`idempotency_key`（現行スキーマにある欄）だけ。
- **負例**：`tests/test_phase1_reference_contracts.py` の R2（順序入れ替え→連番、再送、改変再送、古い世代、他セッション、キー無し、Engine 拒否、洪水）。
- **未解決**：複数タブ・`session_epoch`／`revision`（後続 Phase）。

## R3：時間の正本 — 決定
- **正本**：コントローラの単調な整数ミリ秒（`FakeClock`、注入）。Engine の `elapsed_seconds` は**コントローラが累積から導出して渡す**整数。
- **変換**：`engine_total_s = floor(clock_total_ms / 1000)` を保つ。各回答で渡すのは「累積の床の差」。回答ごとの切り捨てではない（0.9 秒を 10 回で 0 秒にならず 9 秒）。端数は次の回に持ち越し、失わない。1 回の差が 3600 秒を超えれば 3600 を渡し、**残りは次回に持ち越す**（捨てない）。
- **時計の逆行・bool・float・負数**：`ClockRegression`／`ValueError`。黙って丸めない。同じ値（同一ミリ秒の 2 イベント）は許す。
- **無回答の期限**：Engine は回答の後でしか時間を評価しない（`remaining_seconds == 0` は `answer` の中）。よって無回答では Engine は自分で終了しない。コントローラが `tick(now_ms)` で **開始＋`total_seconds`** を過ぎたことを検知し、`state_changed(deadline_passed)` を出す。`end_policy:"finish_current_question"` なら**開いている質問への回答は猶予内だけ受理**（既定 **120 000 ms**、設定の範囲 0〜600 000 ms）。猶予を過ぎたら回答を `answer_after_grace` で拒否し、`end()` で終了する。
- **終了と確定回答の競合**：台帳の確定順が勝つ。`end` が先にコミットされたら、その後の回答は古い世代・終了済みとして拒否。
- **pause**：Phase 1 は**未対応**（`not_supported_phase1` で拒否）。切断中の時計は**止めない**（経過に数える）。切断が再接続の TTL（既定 **60 000 ms**）を超えたら期限切れ。**retry**：新しいセッション ID・新しい時計（0 から）・前の回答を引き継がない。
- **依存してよい**：整数ミリ秒の注入時計、上の変換式、Engine の公開 API の `elapsed_seconds`（0〜3600 の整数）。
- **負例**：`test_r3_*`（累積ドリフト、持ち越し、逆行、型）。
- **未解決**：pause の意味（後続）、音声の発話時間を時計にどう入れるか（Phase 2 以降）。

## R4：回答不足の評価 — 解決（スキーマを V1.1 に修正）
- **受け入れる**：Phase 1 は既存の `feedback.build_feedback` の出力を**そのまま**返す（V2 への変換は後続 Phase）。0 件・1 件の回答では既存どおり「判定できません（回答が足りません）」。
- **拒否する**：V2 のために項目を消す、偽の根拠（偽 span）を作る、ルーブリックを弱める。
- **修正する契約**：`FeedbackReportV2` の項目で、`stage:"判定できない"` のときは `evidence` を **0 件**に限る（1 件でもあれば拒否）。それ以外の `stage` は従来どおり `evidence` が 1 件以上。つまり「判定できない」は偽の根拠なしに表せる。V2 の `stage` と旧 `NOT_ENOUGH` 文字列の対応は、後続の変換器の仕事（`判定できません（回答が足りません）` ⇄ `判定できない`、変換は 1 対 1 で情報を足さない）。スキーマは `docs/realtime-interview/schemas/realtime_contracts_v1.schema.json`（V1.1）。
- **依存してよい**：旧フィードバックの生出力（Phase 1）。V2 は使わない。
- **負例**：「判定できない」＋偽の根拠が拒否される、「要改善」で根拠 0 件が拒否される（既存）、0 件・1 件の回答の旧フィードバックに根拠がない（`test_r4_*`）。
- **未解決**：V2 変換器（後続）。

## R5：文脈の契約 — Phase 1 は旧ケース直接でよい
- **受け入れる**：Phase 1 は既存の架空 3 ケース（`fiction-ac-1` など）を**不透明な合成文脈**として直接使う。`InterviewContextV2` への変換、`practice_bank`、`fiscal_year` の写像、W3 v2 の scope は**使わない**（後続）。
- **拒否する**：Phase 1 での実大学 DB 接続、`fiscal_year` の写像の確定、`entry_year` の既定採用。
- **修正する契約**：`practice_bank` は `InterviewContextV2` に既にあるが、`QuestionProposal` の生成元としての扱いは後続 Phase。W3 v2 の完全 scope（`university_id`〜`stage`、`exam_year`）の不足は PR #109 側の課題として残す。
- **依存してよい**：`CASES`（架空）。
- **負例**：`fiscal_year_mapping.decided_by=pending` で実接続モードが拒否される（既存のスキーマ負例）。
- **未解決**：`fiscal_year` の写像（D-5、ユーザー判断）、`practice_bank` の確定、W3 v2。

## R6：依存と意味検査 — Phase 1 の範囲を限定
- `sandbox/evaluation/llm_metrics.py` は master にある（PR #130）。確認済みで依存してよい。
- **受け入れる**：スキーマを通っただけを意味検証と見なさない。Phase 1 の shadow 検査は 12 項目（`V-GUARD`〜`V-INJECTION`）の**決定的な実装**で、各項目に負例を付ける。意味の正しさ（言い換え・氏名・住所）は保証しない旨を明記する。
- **未解決**：12 項目の網羅の独立試験は Work の PR の head を見てから、Claude が追加する（現時点では NOT_RUN）。

## R7：保持と再接続 — 決定
- **受け入れる**：メモリのみ。JSONL は**シリアライズ表現**で、既定でファイルへ書かない（`persist:false`、`recording:"none"`）。
- **TTL**：再接続 60 000 ms 超で期限切れ、終了後のフィードバック表示 600 000 ms 超で期限切れ。期限切れでは**回答・ターン・イベント・フィードバックをすべて破棄**（確定記録も残さない）。終了済み・期限切れのセッションは再接続できない。
- **retry**：新しいセッション ID。旧世代の音声・字幕（後続）は拒否。
- **試験の境界**：core は**ソケット禁止でも全試験が通る**。将来の loopback 限定 UI の試験は別の試験で、外部への接続禁止と区別する。
- **依存してよい**：メモリ内の台帳、JSONL へのシリアライズ関数（書き出しは呼び出し側が明示した場合のみ）。
- **負例**：`test_r7_*`（TTL、終了後の再接続、ソケット禁止）。
- **未解決**：失効時の具体的な消去対象の列挙は実装の PR で確認（Work の PR を独立レビュー）。

## R8：音声の安全境界 — 同意（Phase 1 をブロックしない）
- **受け入れる**：Phase 1 は実音声ゼロ、固定テキストのみ。将来の strict mode は、**発話前に検証できる**方式（検証済みの確定テキストの TTS、または許諾済みの固定音源）だけを公式の方式とする。ネイティブ音声モデルの事後監査を、発話前検証と同等と扱わない。生成後の取消は、既に聞こえた誤情報を取り消せない（記録に「取り消したが再生済み」と残す）。
- **拒否する**：「事後に allowlist で監査するので strict と同じ」という扱い。
- **修正する契約**：`PROVIDER_COMPARISON_2026-11-03.md` §方式 B（リアルタイム音声モデル）は、許可リストの固定文のみ。この修文は `THREAT_MODEL_AND_PRIVACY.md` の T7 に既にある。
- **未解決**：実音声の提供者選定（承認なし）。

## Work が今すぐ着手してよい範囲（Phase 1）
1. 安全な `config`（全機能 disabled）。2. `FakeClock`（R3）。3. Engine の公開 API を呼ぶ薄い `RealtimeInterviewController`（new／start／current／answer／end／raw feedback／retry）。4. 台帳（R2）と期限（R3）と保持（R7）の最小実装。5. 旧フィードバックの生出力（R4）。所有範囲は `research/inbox/work-interview-room/`。`sandbox/`・`tests/`・`docs/` の契約文書・既存の 5 PR は変更しない。実音声・LLM・SDK・カメラ・マイク・外部通信は使わない。
**独立レビューの観点**：本ファイルの各「負例」の試験が Work の実装でも成り立つこと（`tests/test_phase1_reference_contracts.py` と同じ振る舞い）、外部通信ゼロ、永続保存ゼロ、既存質問列・フィードバックと完全一致、容量使用量。

## 変更前の曖昧さと修正理由（要約）
| 項目 | 変更前 | 修正 |
|---|---|---|
| R2 | `seq` を送り手が付けるのか台帳が付けるのか未定義 | 台帳（コミット時）。入口はコマンド |
| R3 | 累積の丸めが未定義。無回答の期限が Engine に無い | 累積の床で渡す。コントローラの `tick` と猶予 |
| R4 | V2 の `evidence` が最低 1 件で、旧「判定できません」を表せない | 「判定できない」は 0 件、偽の根拠は拒否（スキーマ V1.1） |
| R7 | 失効時の消去対象と TTL が未定義 | TTL 60 秒／600 秒、全破棄 |
