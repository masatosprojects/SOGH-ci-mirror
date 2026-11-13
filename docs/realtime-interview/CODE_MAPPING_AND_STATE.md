# 成果物B：既存コード → 新機能の詳細対応表と状態遷移（`PROPOSED`）

**状態：`PROPOSED`。** 対象は master `fe36208` の `sandbox/interview_sandbox/`（`models.py` 109 行、`engine.py` 260 行、`feedback.py` 184 行、`guards.py` 63 行、`cases.py` 65 行）と `sandbox/evaluation/`、Work の `research/inbox/work-night-integration/demo/`。**型・関数・試験を実際に読んで**書いている【W】。変更は提案で、Work の所有ファイルは編集しない。
分類：**再利用**（そのまま）／**拡張**（後方互換で足す）／**互換を壊す変更**（避ける、または版を上げる）。

## 1. 型ごとの対応
### 1.1 `InterviewSession` → 面接進行コントローラ
| 既存の事実（コード） | 新しい役割 | 分類 |
|---|---|---|
| `state` ∈ {`setup`,`in_progress`,`ended`}、`start()` は `setup` からのみ（二重開始は `RuntimeError`） | コントローラの**外側の状態** | **再利用** |
| `answer(turn_id, text, elapsed_seconds)`：`turn_id` が未回答の質問と一致しなければ `duplicate_or_stale_turn` で**拒否**（`rejected_events` を加算、何も変えない）。`elapsed_seconds` は 0〜3600 の整数、それ以外は `ValueError` | **冪等・古いイベントの拒否**の既存の性質。`TurnEvent.idempotency_key` と世代 ID に引き継ぐ | **再利用**（性質を保つ） |
| 時間：`remaining_seconds = plan.total_seconds − Σ elapsed`、0 で `time_up`（質問の途中では切らず、回答の後に終了） | 時間管理の正本。音声では**単調時計（ミリ秒）**から `elapsed_seconds` を導出 | **拡張**（ミリ秒を持ち、秒へ丸めて既存へ渡す） |
| 追質問：`_follow_up` が回答の曖昧語・活動語・理由語・短さから**規則で**選ぶ。引用位置 `quote`、上限（質問ごと／全体）、同じ言葉は二度尋ねない（今回修正済み） | **規則ベースの追質問は下限（フォールバック）として残す**。LLM の候補は別経路（`QuestionProposal`） | **再利用** |
| 禁止断定を含む回答：中立の追質問に置き換え、`claim_not_repeated` の通知 | LLM 出力の検証でも同じ方針（引用しない） | **再利用** |
| `end(reason)`、`_finish`、`feedback()`（`ended` のみ）、`retry()`（新しいセッション） | 終了・振り返り・再挑戦 | **再利用** |
| `variant`（質問プールの選択）、`SessionConfig` | 質問の選択の決定性、外部接続の旗 | **再利用／変更しない**（§1.7） |
**結論**：`InterviewSession` を**捨てず**、その上に薄い `RealtimeInterviewController` を置く。進行の判断（質問数・時間・上限・終了・安全）は `InterviewSession` が正本として持ち続け、コントローラは「音声のイベントを `answer()` の呼び出しへ翻訳し、`Turn` を `SpeechInstruction` へ翻訳する」層に限る。**進行の正本は 1 つ**。

### 1.2 `InterviewContext` → 検証済み大学情報を受け取る読み取り境界
| 既存 | 新 | 分類 |
|---|---|---|
| `case_id`・`university`（架空を含む）・`faculty`・`method`・`fiscal_year`・`official_facts`・`experience_reports`・`practice_questions`・`plan`・`interview_is_official`（frozen dataclass） | `InterviewContextV2` に**そのまま含める**（ネストした `legacy: InterviewContext` か、同名フィールド） | **再利用** |
| `OfficialFact(fact_id,label,value,status,source_version,kind)`：`confirmed` は値が必須、`unknown` は値が `None`（`__post_init__` で検証） | 出所（資料 ID・版 ID・SHA・頁・位置）を足した `OfficialFactV2` | **拡張** |
| `fiscal_year` 1 つ | `entry_year`（入学年）と `exam_year`（実施年）を**別に**持つ。Sandbox の `fiscal_year` への写像は `fiscal_year_basis` で**明示**（未決） | **拡張**（写像は【要承認】） |
| 発行元・作成時刻・有効期限・版の固定が無い | `snapshot_id`・`issuer`・`created_at`・`expires_at`・`context_sha256` | **拡張** |
| 経験報告 `ExperienceReport(report_id,fiscal_year,summary,certainty,consent_scope)` | 同意範囲・出所・年度を保つ。**公式事実と別の欄**（既存の分離を維持） | **再利用** |

### 1.3 `PracticeQuestion` → LLM の質問候補と検証済み練習質問
| 既存 | 新 | 分類 |
|---|---|---|
| `PracticeQuestion(question_id,category,text,basis_fact_ids,kind="ai_practice_material")`、`cases._q` が `assert_clean` を通す | 人が確認した**練習質問バンク**＝LLM が使えない時のフォールバック。`ValidatedQuestion` の一種として扱う | **再利用** |
| カテゴリごとに `variant % len(pool)` で 1 問を選ぶ | `QuestionProposal`（LLM）は**同じカテゴリ・同じ予算**の枠に入る。採用されなければ従来の選択 | **拡張** |
| `basis_fact_ids` の事実は `confirmed` なら版つきで併記、`unknown` なら「公式には確認できていません」 | 同じ規則を `ValidatedQuestion.grounding` に | **再利用** |

### 1.4 `Turn` → 会話イベント（音声・字幕・発話区間・イベント ID）
| 既存の欄 | `TurnEvent` の欄 | 分類 |
|---|---|---|
| `turn_id`（`{case}:v{variant}:t{n}`）、`role`、`text`、`origin`（`ai_practice_material`／`official_fact_based`／`follow_up_to_the_answer`／`user_input`）、`question_id`、`basis`、`followup_of`、`quote`、`elapsed_seconds` | **すべて保つ** | **再利用** |
| （無い）イベント ID、順序番号、世代 ID | `event_id`、`seq`（単調増加）、`generation_id`、`idempotency_key` | **拡張** |
| （無い）暫定／確定、開始・終了時刻（ミリ秒）、発話の出どころ | `text_status`（`partial`/`final`）、`t_start_ms`/`t_end_ms`、`source`（`stt`/`controller`/`typed`/`system`） | **拡張** |
| `origin` に `llm_proposed_validated`（新） | LLM 由来で検証を通した質問を区別 | **拡張**（既存 4 値は不変） |
**互換**：既存の `Turn` を `TurnEvent` から**再構成できる**こと（`final` のみ、`seq` 順）。既存の試験は `Turn` を使い続ける。

### 1.5 `feedback.py` → 詳細分析モデルの入力・結果の契約
| 既存 | 新 | 分類 |
|---|---|---|
| `build_feedback(session)`：5 項目（明瞭さ・具体性・一貫性・根拠となる経験・学びと志望のつながり）、段階 `STAGES`（要改善／一部できている／できている）、`Evidence`（本人の言葉の位置または伏せ字）、`LIMITS`、`notes`（終了理由、**質問されなかった分野**、お知らせ） | **規則ベースの下限**として残す。`FeedbackReportV2` の `items` と同じ形 | **再利用** |
| `RUBRIC_VERSION="practice-rubric-v1.2"`、同じ回答は同じ結果（決定的） | LLM 評価は**別の版**（`llm-feedback-vN`）で、規則ベースと**並べて**出せる。ルーブリックの版は変更しない | **拡張** |
| 根拠は `Evidence(quote, span)` | 発話区間（`turn_id`＋位置、音声なら `segment_id`）を足す | **拡張** |
| 入力は `InterviewSession` | `FeedbackInput`＝確定した `TurnEvent` の列＋文脈の SHA＋予定カテゴリ（音声の生データは渡さない既定） | **拡張** |
**性質試験の再利用**：改善例が本人の述べていない数字・事実を足さない／改善した回答が下がらない／引用は本人の言葉の位置か伏せ字（`tests/test_sandbox_quality_properties.py` ほか）を、LLM 出力にも適用する。

### 1.6 `guards.py` → LLM 出力・自由記述・音声発話の安全制約
| 既存 | 新 | 分類 |
|---|---|---|
| `forbidden_claims_in`（禁止断定、否定形は許す）、`assert_clean` | **発話の直前に必ず**通す（`ValidatedQuestion` の `V-GUARD`） | **再利用** |
| `mask_personal`・`has_personal`（メール・電話・URL・ハンドル・郵便番号・全角・変種） | 入力の文字起こしの保存前、出力の発話前（`V-PII`） | **再利用** |
| `SENSITIVE_TERMS`（家庭、宗教、思想、健康など） | LLM の質問候補の拒否（`V-SENS`）、追質問の対象外 | **再利用** |
| ガードは**既知のパターン**だけ（氏名・住所・言い換え・意味は対象外） | LLM では不十分。**検証層を足す**（根拠の一致、他ケースの語、数字の出所、プロンプトインジェクション、AI 開示。`INTERFACE_CONTRACTS_V1.md` §4） | **拡張**（ガードは無効化しない） |

### 1.7 `SessionConfig` → そのまま保つ
`SessionConfig(llm_enabled=False, persist=False)` は、真にすると `NotImplementedError`。**これは意図した安全装置**で、有効化しない。新しい接続は別の設定型（`RealtimeSessionConfig`）に分け、既定は `providers=none`（すべてモック）、`recording=none`、`persist=false`。`RealtimeSessionConfig` が外部提供者を許す条件は、(1) ユーザー承認、(2) 同意記録（`ConsentRecord`）、(3) 提供者ごとの能力宣言、(4) 費用の上限、のすべてを満たす場合に限る。

## 2. 状態遷移の対応（面接進行の正本は 1 つ）
**外側（既存・不変）**：`setup`（準備室）→ `in_progress` → `ended`（`end_reason`）。**`ended` からは戻らない。** 再挑戦は新しいセッション。
**内側（新・`in_progress` の副状態。コントローラが持つ）**：
| 副状態 | 意味 | 入る条件 | 出る条件・イベント |
|---|---|---|---|
| `interviewer_speaking` | 面接官が発話中 | `SpeechInstruction` を発行 | 発話の完了／**割り込み（`barge_in`）**／取消 |
| `listening` | 受験生の発話を聞く | 面接官の発話の完了 | 発言終了の判定（`final`）／長い沈黙の規則 |
| `deliberating` | 次の質問を決める（追質問候補の生成・検証） | 受験生の確定した回答 | `ValidatedQuestion` の確定、または**フォールバックの質問** |
| `paused` | 本人の中断・休憩 | 中断の操作 | 再開／終了 |
| `reconnecting` | 回線の切断から復旧を待つ | 切断の検知 | 期限内に復旧（メモリ内の状態で継続）／期限切れで**保存せず終了** |
| `degraded_text` | 文字モードへの縮退 | 音声・映像の障害、本人の選択 | 回復しても文字のまま続けられる |
**対応**：`start()`＝準備室から最初の質問の発話の開始、`answer()`＝`listening` の確定（`final`）から `deliberating` への遷移、`end()`／`time_up`＝`ended`。**コントローラは副状態の遷移を決めるが、質問数・上限・終了の判断は `InterviewSession` の結果を使う**（二重に持たない）。切断で `InterviewSession` を作り直さない（メモリ内で保持）。

## 3. 再利用／拡張／互換を壊す変更のまとめ
| 区分 | 項目 |
|---|---|
| **再利用** | `InterviewSession` の状態・冪等・時間・上限、`PracticeQuestion` のバンク、`Turn` の欄、`feedback.py` のルーブリック v1.2 と性質、`guards.py` の全関数、`SessionConfig` の拒否、決定的なモック |
| **拡張（後方互換）** | `InterviewContextV2`（年度・出所・版）、`TurnEvent`（ミリ秒・世代・暫定／確定）、`QuestionProposal`/`ValidatedQuestion`、`FeedbackReportV2`（発話区間・生成者）、`RealtimeSessionConfig`、副状態、`origin` の新値 |
| **互換を壊す（避ける）** | `SessionConfig` の旗の意味を変える／`fiscal_year` を黙って `entry_year` か `exam_year` にする／`Turn` の既存欄の型を変える／ルーブリックの段階の付け方を変える（版を上げる別の判断）／`guards` の既存パターンを緩める |

## 4. 正本が複数にならないための規則
1. **進行の正本＝`InterviewSession`（コントローラが包む）**。音声・アバター・LLM は進行を決めない。
2. **確定した会話記録の正本＝`TurnEvent` の `final` 列**。映像・音声のバッファ、提供者のログは記録の正本ではない。
3. **時間の正本＝コントローラの単調時計**。提供者のタイムスタンプは参考。
4. **公式事実の正本＝`InterviewContextV2`（`context_sha256` 固定）**。モデルは事実を足せない。
5. **同意の正本＝`ConsentRecord`**。提供者への送信は、記録された範囲だけ。

## 5. Work のデモ（`research/inbox/work-night-integration/demo/`）との関係
Work のデモは `/api/new`・`/api/start`・`/api/answer`・`/api/end`（セッション最大 4、30 分で失効、メモリ内）で既存の `InterviewSession` を呼ぶ【W】。**新しい基盤は、この HTTP のデモを置き換えず、並べて**モックの音声経路を足す（デモの試験を壊さない）。
