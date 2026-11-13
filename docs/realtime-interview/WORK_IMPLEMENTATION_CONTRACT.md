# 成果物G：Work への実装契約（最初の開発単位、`PROPOSED`）

**状態：`PROPOSED`。** 実装の担当は Work（`docs/COORDINATION.md` の役割分担）。Claude は契約・独立試験・レビューを担当し、Work の所有ファイルを編集しない。ユーザーの承認なしに外部 API・モデル・実データ・費用を使う実装は含まない。**M1 の受け入れ基準と日程に影響しない**（架空データ・ローカルのみ）。

## 1. 最初の開発単位：`MRIF-1`（Mock Realtime Interview Foundation）
**外部 API を使わない、モックのリアルタイム面接基盤。** 実際の音声・映像・LLM の代わりに、決定的な偽物（台本で動く）で、**進行・世代管理・検証・縮退・記録・費用と遅延の記録の形式**を先に固める。実機の品質は何も主張しない。

## 2. 入力データ
| 入力 | 内容 |
|---|---|
| 文脈 | 架空の `InterviewContextV2`（`INTERFACE_CONTRACTS_V1.md` §1。既存の架空ケース 3 件から変換する薄いアダプターを含む）。`fiscal_year_mapping.decided_by` は `pending`（実接続は拒否） |
| プラン | `InterviewSessionPlan`（既定 `mode:"text"`、`recording:"none"`） |
| 台本つきの受験生 | 時刻つきの発話の列（`{t_ms, text, partials[]}`）、割り込み・沈黙・切断・再送・欠番・古い世代のパケットの**注入指示** |
| 質問候補の台本 | `ScriptedProposer`：各ターンで返す `QuestionProposal`（**悪意のある候補を含む**：禁止断定、unknown の肯定、他ケースの語、個人情報、質問が 2 つ、予算超過、回答に無い引用、人間を名乗る） |
| 固定文の許可リスト | 相づち・つなぎ・時間案内の固定文（ID つき） |

## 3. 出力データ
1. `TurnEvent` の列（JSONL、`seq` 単調、`generation_id` つき）。確定（`final`）だけが記録の正本。
2. 各ターンの `QuestionProposal` → `ValidatedQuestion`（理由コードつき）。
3. `SpeechInstruction`・`AvatarInstruction`（検証済みの文だけ。SHA 一致）。
4. 既存の `InterviewSession` の結果と一致する `Turn` 列（互換）と、既存の `feedback.build_feedback` の結果。
5. `FeedbackReportV2`（`generator.kind:"rule"`）。
6. `ProviderUsageRecord`（偽の単位・費用 0・`price_basis` はフィクスチャ）。
7. 遅延の内訳の記録（偽の単調時計。**実機の値として報告しない**）。
8. 障害注入ごとの結果（縮退の成否、確定記録の保全）。

## 4. 呼び出す既存コード（変更しない）
`sandbox/interview_sandbox/` の `InterviewSession`（`start`／`answer`／`end`／`feedback`／`retry`）、`InterviewContext`・`PracticeQuestion`・`OfficialFact`（変換元）、`guards.forbidden_claims_in`・`has_personal`・`mask_personal`・`sensitive_in`・`assert_clean`、`feedback.build_feedback`、`sandbox/evaluation/llm_metrics.py`（`ungrounded_university_facts`・`pii_leak_count`・`forbidden_claim_count`・`reproducibility`）。

## 5. 新規に追加するアダプター（Work の所有領域。例：`research/inbox/work-realtime-mock/`）
| 部品 | 役割（すべて決定的・ネットワークなし） |
|---|---|
| `RealtimeInterviewController` | `InterviewSession` を包む。副状態（`interviewer_speaking／listening／deliberating／paused／reconnecting／degraded_text`）、世代管理、`TurnEvent` の発行、`answer()` への翻訳 |
| `QuestionValidator` | `V-GUARD`〜`V-INJECTION` の決定的な検査。LLM を含まない。失敗なら練習質問バンクまたは既存の規則ベース追質問へ置換 |
| `FakeVoiceGateway` | 偽の STT（台本の partial／final を時刻どおりに発行）と偽の TTS（文字数から発話時間を見積り、`AudioSegment` のメタデータだけを返す。音声のバイトは作らない） |
| `FakeAvatarGateway` | `AvatarInstruction` を記録し、決定的な同期ずれを返す |
| `FakeTransport` | メモリ内のキュー。**遅延・重複・順序の逆転・欠番・切断**を注入できる |
| `ScriptedProposer` | 台本どおりの `QuestionProposal`（悪意のある候補を含む） |
| `RealtimeSessionConfig` | `providers:"none"` 固定（外部は拒否）、`recording:"none"`、`persist:false` |

## 6. 変更禁止領域
`sandbox/interview_sandbox/`（特に `SessionConfig` の拒否、`guards.py`、`feedback.py` のルーブリック v1.2 の段階の付け方）／`sandbox/evaluation/`／`tests/`（Claude の所有）／`docs/` の契約文書（提案の変更は Issue #75 で）／実 DB・監査コピー／M1 の QA のしきい値／`src/` の DB 契約。**`SessionConfig.llm_enabled`／`persist` を有効化する変更はしない。** `fiscal_year` の写像を黙って確定しない。

## 7. 正常系の試験（最低限）
1. 既存の 3 ケースで、コントローラ経由の結果が `InterviewSession` を直接使った結果と**同じ質問列・同じフィードバック**（互換）。
2. 台本どおりの 1 回の面接が `ended` に至り、`TurnEvent` の `final` から既存の `Turn` を再構成できる。
3. 検証済みの質問だけが `SpeechInstruction` になり、`text_sha256` が一致する。
4. 時間管理：`remaining` の減少、時間警告、`time_up` の挙動が既存と一致。
5. 追質問の上限（質問ごと・全体）、同じ言葉を二度尋ねない、が保たれる。
6. 質問されなかった分野が `FeedbackReportV2.coverage.unasked_categories` に入る。
7. 再挑戦が新しいセッションで、前の回答を引き継がない。
8. 同じ入力は同じ出力（決定性）。

## 8. 異常系・攻撃の試験（最低限。すべて「拒否される／発話されない」を確認）
1. **世代**：割り込みで旧世代の `SpeechInstruction`・音声・映像が取り消され、遅れて届いた旧世代のパケットが**再生されない**。
2. **重複・欠番・逆転**：同じ `idempotency_key` は一度だけ処理、`seq` の欠番を検知して `error`、順序の逆転を整列するか拒否。
3. **悪意のある質問候補**（§2）：すべて `rejected` → フォールバック。**発話ゼロの経路は無い**（検証器が止まったら固定文か文字モード）。
4. **プロンプトインジェクション**：受験生の回答に「以前の指示を無視して…」を入れても、質問候補の検証と発話が影響を受けない。
5. **個人情報**：回答に入れたメール・電話・URL・ハンドル・郵便番号（全角・`(at)`・+81 の変種）が、記録・フィードバック・発話に再掲されない。
6. **unknown**：未確認の事実について肯定の質問・発話をしない。数字が文脈と回答に無ければ拒否。
7. **他ケースの語**：他の大学・方式・`case_id` を含む候補を拒否。
8. **切断**：期限内の復旧は同じ状態から継続、期限切れは**保存せず終了**（確定済みの記録は残さない既定）。
9. **縮退**：音声・アバターの障害で文字モードへ。確定記録は保全され、質問の途中で終わらない。
10. **AI 表示**：`ai_label_visible:false` の指示は拒否、人間を名乗る発話は拒否。
11. **既定**：録音・映像・保存・外部提供者が**既定で無効**であること（`RealtimeSessionConfig` が外部を許さない）。
12. **ネットワーク**：試験中にソケットを開かないこと（`socket` を禁止しても全試験が通る）。
13. **ログ**：回答の本文がログに出ない。

## 9. 完了条件
- 上の試験がすべて成功し、skip なし。既存の Sandbox の試験・Claude の独立試験を**無変更で**再実行して成功。
- Claude の契約試験（`tests/test_realtime_contracts_schema.py`）の正例が Work の出力で受理され、負例が Work の検証器でも拒否される（構造＋内容）。
- 新規ファイルは Work の所有領域のみ。`git diff` が上の禁止領域を含まない。
- 実行環境・コマンド・件数・未実行を PR に明記（CI は停止中のため、ローカル実行はそう書く）。独立レビューの head を指定。
- **実機の遅延・品質・費用を主張しない。** M1 は 2/8、NOT ACCEPTED のまま。

## 10. 未承認でも実装できる範囲
**できる**：上記すべて（架空データ、ローカル、モック、ネットワークなし、費用 0）。提供者の**能力宣言**（`capabilities`／`unsupported`）の型と、記録済みの偽の応答による契約試験。文字モードの縮退。
**できない（承認が要る）**：外部 LLM・音声・映像 API の呼び出し／モデルのダウンロード／実利用者の音声・映像・文章の取得／アバター事業者の試用／有料サービスの契約／`SessionConfig` の旗の有効化／実 DB への接続／`fiscal_year` の写像の確定。

## 11. 協調
Claude が提供：スキーマと契約試験（済）、検証器の負例集の追加依頼への応答、Work の PR の独立レビュー。Work が提供：実装 PR（`work/` ブランチ）、`entry_year`／`exam_year` の扱いの案（PR #109 の W3 v2 と整合させる。**確定はユーザー**）。同じファイルを同時に編集しない。差分があれば Issue #75 で議論し、ユーザー判断が要る点は選択肢として提示する。
