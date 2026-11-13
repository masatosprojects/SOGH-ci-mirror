# 成果物C：インターフェース契約 V1（`PROPOSED`）

**状態：`PROPOSED`。名前は仮称。** 既存の `sandbox/interview_sandbox/models.py` の型と衝突しないよう、`V2`・新名にした。機械で確かめられる形は `docs/realtime-interview/schemas/realtime_contracts_v1.schema.json`（JSON Schema）と `tests/test_realtime_contracts_schema.py`（正例・負例）にある。**ここの「必須条件」は検証器の仕様であり、LLM や提供者を信頼する前提ではない。**
共通の規則：①未知の欄は拒否（`additionalProperties:false`）／②すべての時刻は `*_ms`（セッション開始からの単調なミリ秒）／③ID は不透明な文字列（個人情報を含めない）／④未確認の事実は `null`＋`status:"unknown"`、**補完しない**／⑤エラー時は「取り消して固定文または文字モードへ縮退」（沈黙して続行しない）。

## 1. `InterviewContextV2`（読み取り境界。M1 の結果を面接へ渡す）
| 欄 | 型・条件 |
|---|---|
| `contract_version` | `"interview-context-v2"` 固定 |
| `snapshot_id`・`issuer`・`created_at`・`expires_at` | 必須。`expires_at` を過ぎたらセッション開始不可。発行元の文字列は信頼の根拠にならない（検証は呼び出し側）【W-3・PR #109】 |
| `context_sha256` | 64 桁の小文字 16 進。セッション開始時に固定し、途中で変えない |
| `scope` | `case_id`・`university`・`faculty`・`department`（`null` 可）・`offering`・`method`・`entry_year`（整数）・`exam_year`（整数または `null`）・`entry_month`（任意）・`stage`。**`fiscal_year` は持たない**（写像は別欄） |
| `fiscal_year_mapping` | `{target:"sandbox.fiscal_year", basis:"entry_year"\|"exam_year", decided_by:"user"\|"pending"}`。`pending` の間は実接続不可（架空データのみ）【要承認】 |
| `official_facts[]` | `{fact_id,label,status:"confirmed"\|"unknown",value(confirmed のみ),version_id,source_ref{document_id,revision_id,sha256,page,span_start,span_end}}`。`unknown` は `value:null`・`source_ref:null`。**`unknown` の説明に推測の数字を入れない** |
| `experience_reports` | `{count,items[]}`。既定 `count:0`。各項目に同意範囲・年度・確かさ。公式事実と別の欄 |
| `practice_bank[]` | 人が確認した練習質問（既存 `PracticeQuestion` 相当）。フォールバック用 |
| `interview_is_official` | 真偽。偽なら「公式の面接」として演じない |
**負例**：`unknown` に値がある／`confirmed` に出所が無い／期限切れ／`context_sha256` 不一致／未知の欄／`entry_year` が文字列／`fiscal_year_mapping.decided_by=pending` で `mode` が実接続。

## 2. `InterviewSessionPlan`
| 欄 | 条件 |
|---|---|
| `plan_id`・`session_id` | 必須 |
| `categories[]` | `{name,min_questions,max_questions}`。既存の `SessionPlan.categories` と対応 |
| `total_seconds` | 60〜7200。既存の上限（回答 3600 秒）と整合 |
| `max_followups_per_question`・`max_total_followups` | 既存の既定 2・5 以下 |
| `end_policy` | `"finish_current_question"`（既存の挙動）または `"cut"` |
| `time_warning_ms[]` | 例：残り 5 分・1 分 |
| `mode` | `"text"`・`"voice"`・`"voice_avatar"`。既定 `"text"`。外部提供者を含む `voice*` は同意が前提 |
| `interviewer_count` | 1（初期）。複数は将来 |
| `difficulty` | 列挙。威圧・人格否定を含む設定は無い |
| `recording` | `"none"`（既定）/`"memory"`/`"stored"`（`ConsentRecord` が前提） |
**負例**：`total_seconds` が範囲外／`max_followups_per_question` が既定を超える／`recording:"stored"` で同意が無い／`categories` が空／同じ名前の重複。

## 3. `QuestionProposal`（LLM などの**提案**。発話ではない）
| 欄 | 条件 |
|---|---|
| `proposal_id`・`session_id` | 必須 |
| `after_turn_id`・`answer_turn_id` | 追質問の元の発言（確定した `TurnEvent`）。最初の質問は `answer_turn_id:null` |
| `answer_span` | `[start,end]`。追質問は元の回答の**実在する範囲**を引用（検証で照合） |
| `text` | 1〜400 文字。**質問は 1 つ**（疑問の終わりが複数なら拒否） |
| `category` | プランのカテゴリのいずれか |
| `intent` | 列挙：`clarify`（曖昧さ）・`deepen_reason`・`role`・`evidence`・`consistency`・`verification_method`・`transition` |
| `origin` | `"ai_generated"` 固定（人が書いた質問でも、LLM 提案の経路では AI 生成として扱う） |
| `grounding` | `{official_fact_ids[],fact_version_ids[],uses_unknown:false}`。公式事実に触れるなら ID と版が必須。**`uses_unknown:true` は拒否** |
| `claims_official` | 真偽。真なら `grounding.official_fact_ids` が非空で、すべて `confirmed` |
| `budget` | `{followups_used,followups_remaining,remaining_ms,expected_duration_ms}`。**期待時間が残り時間を超えれば拒否** |
| `proposer` | `{provider_id,model_id,prompt_version,temperature}` |
| `status` | `"proposed"` 固定（検証前） |
**負例**：公式の数字（定員・時間）を含むが `grounding` が無い／`uses_unknown:true`／他のケースの大学名を含む／質問が 2 つ／回答に無い語を引用していると称する／禁止断定／個人情報／機微な話題／「あなたは AI ではなく人間です」のような開示違反／予算超過。

## 4. `ValidatedQuestion`（発話してよい唯一の質問）
検証器（決定的、LLM を含まない）が `QuestionProposal` に対して次を**すべて**行う。1 つでも失敗すれば `rejected`（理由コードつき）で、**フォールバック（練習質問バンクまたは既存の規則ベース追質問）**を使う。
| コード | 検査 |
|---|---|
| `V-GUARD` | `guards.forbidden_claims_in` が空（NFKC 正規化後） |
| `V-PII` | `guards.has_personal` が偽、質問に受験生の個人文字列を再掲しない |
| `V-SENS` | `guards.sensitive_in` が空 |
| `V-GROUND` | 数字・日付・制度名が `context` と回答に実在（`sandbox/evaluation/llm_metrics.ungrounded_university_facts` が空）。公式事実に触れるなら `claims_official` と一致 |
| `V-UNKNOWN` | `unknown` の事実について肯定の主張をしない |
| `V-SCOPE` | 他のケースの大学・学部・方式・`case_id` を含まない |
| `V-BUDGET` | 追質問の上限と残り時間の範囲内 |
| `V-QUOTE` | `answer_span` が実在し、引用語が回答に含まれる |
| `V-REPEAT` | 同じ言葉を二度尋ねない（既存の規則と同じ） |
| `V-FORM` | 質問が 1 つ・長さ内・指示文でない |
| `V-DISCLOSURE` | 人間を名乗らない・合否や出題の予告をしない |
| `V-INJECTION` | 受験生の文字起こしに含まれた指示（「以前の指示を無視」など）に従った形跡が無い（質問が回答内の命令文を実行・復唱していない） |
| 欄 | `proposal_id`・`status:"validated"\|"rejected"\|"replaced_by_fallback"`・`validated_text`・`checks[{code,result,detail}]`・`validator_version`・`validated_text_sha256`・`fallback_question_id`（置換時） |
**重要**：`validated_text` は**検証した文字列そのもの**。`SpeechInstruction.text` はこれと一致しなければ発話しない（SHA 照合）。検証の後に文面を書き換える経路を作らない。
**検証の限界**：既知のパターンと数字の照合であり、意味の正しさ・言い換えによる主張・氏名や住所は保証しない。人による評価が別に要る。

## 5. `TurnEvent`（会話の正本）
| 欄 | 条件 |
|---|---|
| `event_id`（一意）・`session_id`・`seq`（単調増加、欠番は検知） | 必須 |
| `kind` | `utterance_started`・`partial`・`final`・`cancelled`・`barge_in`・`silence`・`state_changed`・`error` |
| `turn_id`・`generation_id` | 面接官の発話は世代で管理。割り込みで世代が進む |
| `role`・`origin`・`question_id`・`basis`・`followup_of`・`quote` | 既存の `Turn` と同じ意味。`origin` に `"llm_proposed_validated"` を追加 |
| `text`・`text_status` | `partial` は**保存・評価に使わない**。`final` のみが記録の正本 |
| `t_start_ms`・`t_end_ms`・`source` | `stt`/`controller`/`typed`/`system` |
| `segment_ids[]`・`idempotency_key` | 音声区間との対応、再送の重複排除 |
**エラー時**：欠番・順序の逆転・古い `generation_id` のイベントは**捨てて**`error` を記録（既存の `duplicate_or_stale_turn` の一般化）。
**負例**：`partial` を評価に使う／同じ `idempotency_key` の二重処理／古い世代の `final` を採用／未来の `t_start_ms`／`seq` の巻き戻し。

## 6. `AudioSegment`
| 欄 | 条件 |
|---|---|
| `segment_id`・`session_id`・`turn_id`・`direction`（`in`/`out`） | 必須 |
| `codec`・`sample_rate_hz`・`channels` | 例：入力 16 kHz／24 kHz の PCM16（提供者の公式仕様に合わせる）。**採用前に一次情報で確認** |
| `t_start_ms`・`t_end_ms` | 必須 |
| `storage` | `"none"`（既定：バイトを永続化しない）／`"memory"`（セッション内）／`"encrypted_store"`（`ConsentRecord.recording_retention` が前提） |
| `sha256` | 保存する場合のみ |
**負例**：`storage:"encrypted_store"` で同意が無い／`in` の音声に `turn_id` が面接官のもの／保持期限が無い。**既定では音声のバイトを残さず、確定した文字だけを残す。**

## 7. `SpeechInstruction`（コントローラ → 音声層）
| 欄 | 条件 |
|---|---|
| `instruction_id`・`generation_id`・`turn_id` | 必須 |
| `source` | `"validated_question"`（`validated_question_id` が必須）または `"fixed_phrase"`（許可リストの固定文 ID） |
| `text` | `validated_text` / 固定文と**完全一致**（`text_sha256` で照合） |
| `language` | `"ja"` |
| `voice_id`・`pace`・`pause_before_ms`・`pause_after_ms` | 提供者中立の指示。範囲を制限 |
| `interruptible` | 既定 `true` |
| `deadline_ms` | これを過ぎたら発話せず取り消し（遅れて届いた旧世代の再生を防ぐ） |
**負例**：検証されていない文／`text` と SHA の不一致／許可リスト外の固定文／旧世代／`deadline` 超過／`language` が `ja` 以外（初期）。

## 8. `AvatarInstruction`（コントローラ → アバター層）
| 欄 | 条件 |
|---|---|
| `instruction_id`・`generation_id`・`speech_instruction_id` | 必須 |
| `state` | 列挙：`idle_listening`・`speaking`・`thinking`・`attentive`・`closing` |
| `gesture` | 列挙（小さな範囲）：`nod_small`・`nod_slow`・`blink`・`gaze_camera`・`none`。**受験生の表情・感情への反応を表す値は持たない** |
| `intensity` | 0〜1。小さい既定 |
| `ai_label_visible` | `true` 固定（AI 表示を消せない） |
| `identity` | `{avatar_id,license_ref}`。**実在人物の肖像・声でないこと**の根拠（許諾ID） |
**負例**：`ai_label_visible:false`／感情を推定する値（例 `mirror_user_emotion`）／実在人物を示す `avatar_id`／旧世代。

## 9. `ConsentRecord`
| 欄 | 条件 |
|---|---|
| `consent_id`・`session_id`・`subject_pseudonym` | 氏名を持たない |
| `age_band` | `"under18"`/`"18plus"`/`"unknown"`。`under18`／`unknown` は保護者の関与の手続き（**法令は未調査**）が整うまで、外部提供者・保存を許さない |
| `scopes` | `{audio_processing,video_processing(既定 false),transcript_retention,recording_retention,send_to_provider[],experience_sharing}`。各 `send_to_provider` は `{provider_id,purpose,data_kinds[],region,retention,training_use}` |
| `consent_text_sha256`・`granted_at`・`expires_at`・`revoked_at` | 同意文の版を固定。撤回すると以降の送信・保存は不可、削除要求を発行 |
**負例**：`video_processing:true` で `send_to_provider` に映像が無い（矛盾）／`training_use` が `unknown`／`age_band:under18` で外部送信／撤回後の送信／同意文の版が不明。

## 10. `FeedbackReportV2`
| 欄 | 条件 |
|---|---|
| `report_id`・`session_id`・`rubric_version`（`practice-rubric-v1.2` など）・`generator{kind:"rule"\|"llm",provider_id,model_id,prompt_version}` | 必須 |
| `items[]` | `{key,label,stage,reason,evidence[{turn_id,start,end,segment_id?}],improvement_example,uncertainty}`。**`evidence` が空の項目は出さない（または `NOT_ENOUGH`）** |
| `coverage` | `{planned_categories[],asked_categories[],unasked_categories[]}`。質問されなかった分野に依存する項目は注記 |
| `limits[]` | 既存の `LIMITS` を含む。合否・出題の保証をしない |
| `comparison_with_previous` | 同じ条件の再挑戦で、`STAGES` の順で比較。判定不能なら「増減」と呼ばない |
| `inference_from_appearance` | `false` 固定（表情・声色・見た目からの推定をしない） |
**負例**：`improvement_example` に本人が述べていない数字／根拠が他人の発言／`uncertainty` の欠落／合否や確率の記述／外見からの推定。

## 11. `ProviderUsageRecord`
| 欄 | 条件 |
|---|---|
| `usage_id`・`session_id`・`provider_id`・`model_id`・`model_version_or_snapshot` | 必須（版が無い結果は比較に使わない） |
| `kind` | `stt`/`llm`/`tts`/`avatar`/`realtime`/`transport`/`feedback_llm` |
| `t_start_ms`・`t_end_ms`・`units` | `{audio_seconds_in,audio_seconds_out,input_tokens,output_tokens,avatar_seconds}`（提供者の課金単位に合わせる） |
| `price_basis` | `{price_version,retrieved_on,currency}`。**請求書ではなく推定**であることを示す |
| `cost_estimate` と `cost_billed` | 推定と実請求を**別欄**。実請求が無い間は `null` |
| `region`・`data_policy_ref`・`status`・`retries` | 必須 |
**負例**：`price_basis` が無い／`cost_billed` を推定で埋める／版の欠落。

## 12. 型の検証が守る不変条件（まとめ）
1. 発話できるのは、検証済みの質問か固定文だけ（SHA 一致）。 2. `unknown` を肯定しない。 3. 古い世代のイベントは採用しない。 4. 既定で音声・映像・個人情報を保存・送信しない。 5. AI 表示は消せない。 6. 実在人物の肖像・声を使わない。 7. 外見・声色から人物を推定しない。 8. 数字は文脈か回答にある。 9. 追質問は上限と残り時間の内。 10. 費用の推定と請求を混ぜない。
