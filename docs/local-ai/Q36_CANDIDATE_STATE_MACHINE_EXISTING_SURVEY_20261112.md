# Q36 候補状態機械と既存コード・表・試験の対応調査報告書

- **文書ID**: `SOGH-LOCAL-AI-Q36-STATE-MACHINE-SURVEY-20261112`
- **タスクID**: `A-25`（Q36 候補状態機械の既存コード対応調査）
- **作成担当（Author）**: Google Antigravity（Gemini 4 Argon / Gemini 3.8 Flash, ゲーミングPC）
- **独立QA担当（Independent QA）**: Claude Code（メインPC）
- **位置づけ**: 調査報告・設計整理（文書のみ・コード改変なし）
- **基準master**: `bf39098`
- **準拠方針**: STR-134（Q36 候補状態の型と遷移）、STR-101（`scope_evidence`）、STR-096/097（完全架空・実モデルHOLD）、DB-17/移行 0012〜0014 契約

---

## 1. 目的とスコープ

STR-134 の共同設計 Q36 において、本人が採用した設計方針（Q36=D）である以下の**型付き候補状態機械（Candidate State Machine）**：
```
[OBSERVED]
   │
   ▼
[DIFFERENCE_DETECTED]
   │
   ▼
[SOURCE_SCOPE_CHECKED]
   │
   ▼
[EXTRACTED]
   │
   ▼
[EVIDENCE_VALIDATED]
   │
   ▼
[QA_READY] (※正本DB更新や公開権限は発生しない)

分岐・終端状態:
├── [UNKNOWN_HELD] (未確認・情報欠落時の安全保留)
├── [REJECTED_QUARANTINED] (禁止操作・規約違反・改ざん試行の隔離遮断)
└── [HUMAN_REVIEW_REQUIRED] (高リスク事実・矛盾・人間判断要求)
```

この各状態が、現在の master 上の**どのコード・どのデータベース表・どの実在テスト**に対応しているか、あるいは**未実装のギャップ（当たらない部分）**であるかを厳密に調査・固定します。
すべてのファイルパス・表名・テスト関数名は、master 上で grep / 実在確認を行い、自動検査スクリプト（`scripts/verify_q36_survey.py`）で保証します。

---

## 2. 状態別対応マトリクス（Happy Path 6状態 ＋ 分岐3状態）

| 状態名 | 状態の責務・遷移条件 | 既存コード（実在ファイル） | 既存 DB 表（実在マイグレーション表） | 既存テスト（実在確認済み `ファイル::試験名`） | 実装状況・ギャップ分析 |
|---|---|---|---|---|---|
| **`OBSERVED`** | 原典文書（URL/PDF/HTML）が観測・取得され、ハッシュ・取得日時が記録された状態 | `src/versioning/series.py`<br>`pi/sogh_state/state_api.py` | `source_document_series_editions`<br>(in `0014_g06_source_series.sql`) | `pi/tests/test_state_api.py::test_state_reports_only_the_pi_as_observed`<br>`tests/test_antigravity_g6_revision_series.py::test_series_creation_and_append_lineage` | **部分的に実装済**。<br>原典の版系譜・系列登録および Pi 状態APIによる観測ノード同定は実在。外部 Web サイトの自動自律クローラーは未配備（G02/STR-097 遵守のため閉域限定）。 |
| **`DIFFERENCE_DETECTED`** | 非LLMの差分検出により、先行版との SHA 不一致、新 URL、またはテキスト変化が検知された状態 | `src/versioning/series.py` | `source_document_series_editions`<br>(in `0014_g06_source_series.sql`) | `tests/test_versioning.py::test_new_edition_under_a_new_url_is_matched_through_supersedes`<br>`tests/test_antigravity_g6_revision_series.py::test_series_creation_and_append_lineage` | **実装済**。<br>`supersedes` による版の継続性と SHA-256 変化の検出ロジックは実在。HTML/PDF 構造レベルの非LLM自動差分パーサーは将来課題。 |
| **`SOURCE_SCOPE_CHECKED`** | 募集年度（2027年度等）・学部・選抜方式のスコープ適合性が非LLMで照合され、年度外や他学部が除外された状態 | `patches/g2-faq/work-faq-g2-unconfirmed-section.patch`<br>`src/db_contract/additive_schema.py` | `quarantine_staging_candidates`<br>(in `0013_g07_quarantine_staging.sql`) | `tests/behaviour_g2_scope_evidence.py::test_an_inconsistent_or_unsupported_evidence_is_refused`<br>`tests/test_antigravity_g7_quarantine_product.py::test_table_refusal_matrix_ambiguous_multi_year` | **実装済**。<br>`check_scope_evidence` による年度・学部照合（2028年度等の即時拒絶）および移行 0013 の年度正規化ガードが機能。 |
| **`EXTRACTED`** | 原典から事実候補（日程・定員・資格・制約）が型付きデータ構造として構造化抽出された状態 | `patches/g2-faq/work-faq-g2-unconfirmed-section.patch` | `faq_unconfirmed_evidence`<br>(in `0012_g02_faq_unconfirmed_evidence.sql`) | `tests/behaviour_g2_unconfirmed.py::test_an_unconfirmed_record_gets_its_own_section_that_says_so_first_and_cites_every_sentence` | **部分的に実装済**。<br>`extract_conditions` / `structured_record` による条件抽出は実在。LLM による自律的非定型抽出パイプラインは HOLD（STR-097）。 |
| **`EVIDENCE_VALIDATED`** | 抽出事実の引用位置、正規化引用文、および独立した公式原典（別SHA）の照合が完了した状態 | `patches/g2-faq/work-faq-g2-unconfirmed-section.patch`<br>`src/versioning/series.py` | `alias_provenance_bundles`<br>(in `0011_g05_alias_provenance.sql`)<br>`source_document_series_editions`<br>(in `0014_g06_source_series.sql`) | `tests/behaviour_g2_scope_evidence.py::test_a_binding_with_an_independent_official_evidence_is_accepted`<br>`tests/test_m1_0013_0014_g7_g6_tables.py::test_g6_a_series_is_persisted_verified_against_its_rows_and_linked_to_an_impact` | **実装済**。<br>STR-101 独立公式根拠の検証（自参照・引用不一致拒絶）および `verify_series_against_rows` による永続行照合が機能。 |
| **`QA_READY`** | 独立 QA または人間レビューに必要な暗号学的系譜・SHA が揃い、ステージングで待機している状態（正本反映・公開・推論権限なし） | `src/db_contract/additive_schema.py` | `quarantine_staging_candidates`<br>(in `0013_g07_quarantine_staging.sql`) | `tests/test_antigravity_g7_quarantine_product.py::test_guard_block_unquarantined_canonical_insert`<br>`tests/test_m1_0013_0014_g7_g6_tables.py::test_g7_the_flow_works_on_the_migrated_tables_and_needs_a_registered_human_who_is_not_the_stager` | **実装済**。<br>`quarantine_status = 'QUARANTINED'` / `review_status = 'PENDING'` として隔離表で保持され、トリガー `trg_quarantine_enforce_initial_insert` により正本 DB への直接侵入が物理的に遮断される。 |
| **`UNKNOWN_HELD`** | 原典未確認、適用年度不明、または欠測データを「推測せず」安全側に保留・隔離した状態 | `patches/g2-faq/work-faq-g2-unconfirmed-section.patch`<br>`pi/sogh_state/state_api.py` | `faq_unconfirmed_evidence`<br>(in `0012_g02_faq_unconfirmed_evidence.sql`) | `tests/behaviour_g2_unconfirmed.py::test_the_article_without_an_unconfirmed_record_is_what_it_was`<br>`pi/tests/test_state_api.py::test_missing_measurement_is_none_not_a_guess` | **実装済**。<br>STR-076 未確認節分離および Pi 状態 API における `missing_measurement_is_none`（推測値の禁止）として厳格に機能。 |
| **`REJECTED_QUARANTINED`** | 規約違反、追記専用改ざん、失効エポック、範囲外データが即時フェイルクローズ遮断された状態 | `src/db_contract/additive_schema.py` | `quarantine_staging_candidates`<br>(in `0013_g07_quarantine_staging.sql`) | `tests/qa_chain_0012_0014_probes.py::test_probe_01_recursive_triggers_off_cannot_bypass_0012_immutability`<br>`tests/qa_chain_0012_0014_probes.py::test_probe_08_attached_database_insert_still_enforces_triggers` | **実装済**。<br>移行 0012〜0014 のトリガー群による `IntegrityError`（RAISE(ABORT)）および外部 DB 改ざん注入遮断により担保。 |
| **`HUMAN_REVIEW_REQUIRED`** | 高リスク事実、本文と FAQ の矛盾、または正本 DB への最終昇格（Promotion）のため人間の署名・承認を待機する状態 | `src/db_contract/additive_schema.py` | `_quarantine_approval_seals`<br>`canonical_facts_staging_target`<br>(in `0013_g07_quarantine_staging.sql`) | `tests/test_m1_0013_0014_g7_g6_tables.py::test_g7_the_flow_works_on_the_migrated_tables_and_needs_a_registered_human_who_is_not_the_stager`<br>`tests/test_m1_0013_0014_g7_g6_tables.py::test_g7_a_connection_that_did_not_register_the_function_cannot_approve_or_promote_and_nothing_is_replaced` | **実装済**。<br>ステージング実行者と承認者の職務分離（同一人物の禁止）、登録済み人間のみの認可関数チェックが厳格に機能。 |

---

## 3. 全体的なギャップ分析（現状と Q36 構想の差分）

1. **統一クラスの不在（概念の分散）**:
   - 現状の master では、上記 9 つの状態は単一の `CandidateStateMachine` Python クラスや列挙型（Enum）として一元管理されておらず、`patches/g2-faq/work-faq-g2-unconfirmed-section.patch`（`scope_evidence` の辞書キー）、移行 0013 の `quarantine_status` / `review_status`、および DB トリガーの RAISE(ABORT) に分散して表現されています。
2. **自律クローラー・差分検知エンジンの未配備**:
   - `OBSERVED` や `DIFFERENCE_DETECTED` を自動でトリガーするバックグラウンド巡回デーモンは未配備です（G02 外部送信禁止・STR-097 実モデルHOLD に基づく意図的な制約）。
3. **エポック・フェンシングの未実装**:
   - A-24 でも特定された通り、複数ノード間でのスプリットブレインを防ぐ失効エポック検査（Fencing Token）は DB 層に未実装であり、将来の設計課題です。

---

## 4. 実在性検証スクリプト

引用したすべてのファイル・表・テスト名が master 上に存在することを以下のスクリプトで検証しています：
- スクリプト: `scripts/verify_q36_survey.py`
- 検査対象: 引用された全テスト関数（15件）、全移行 SQL 表（6表）、全実装モジュール（4ファイル）
