# 完全架空データ（Q35）によるパイプライン既存部品の試験案

- **文書ID**: `SOGH-LOCAL-AI-Q35-PIPELINE-MAPPING-20261112`
- **タスクID**: `A-23` / `A-24`（PR #376 独立 QA 指摘反映・パス実在性検証版）
- **作成担当（Author）**: Google Antigravity（Gemini 4 Argon / Gemini 3.8 Flash, ゲーミングPC）
- **独立QA担当（Independent QA）**: Claude Code（メインPC）
- **位置づけ**: 設計・試験計画書（文書のみ・コード改変なし）
- **準拠方針**: `docs/execution-plan/ANTIGRAVITY_NEXT_WORK_20261111.md` §2（A-24 READY）、STR-134（Q35完成像・Q36）、STR-101（`scope_evidence` 独立公式根拠）、STR-096/097（完全架空・実モデルHOLD）、DB-17/移行 0012〜0014 契約

---

## 1. 目的とスコープ

`strategy/proposals/experiments/synthetic_q35/` で定義された 30 件の完全架空シナリオ（SC01〜SC30）のうち、現在すでに master に統合されている**移行 0012〜0014 の守り**、**`scope_evidence`（STR-101）**、**未確認 FAQ の分離（STR-076）**、および **Pi 状態 API の読取専用分離**を用いて、**「今すぐ実際に試験できるもの」**を厳密に特定し、その対応表と実行手順を文書として固定します。

本改訂版（A-24）では、引用するすべてのファイルパスおよびテスト関数名が master 上に実在することを自動検証スクリプト（`scripts/verify_scenario_mapping.py`）で保証し、未実装機能（エポック・フェンシング、PII マスキング等）については「既存の試験なし」または「現在は試せない」として正直に区別・明記しています。

---

## 2. 既存の防御部品と検証対象

| 防御部品 | 実装コード | 既存テスト | 主な不変条件・防御メカニズム |
|---|---|---|---|
| **STR-101 `scope_evidence` ガード** | `admissions_pipeline/scope_evidence.py` | `tests/behaviour_g2_scope_evidence.py` | FAQ を年度・学類・選抜方式に紐付ける際、独立した公式原典（別SHA）の引用を必須化。未根拠、自参照、年度不一致（2028年等）、他学部を即時拒絶（`ValueError: not proven`）。 |
| **移行 0012 保管枠** | `0012_g02_faq_unconfirmed_evidence.sql` | `tests/qa_chain_0012_0014_probes.py`, `tests/test_additive_schema.py` | 適用未確認の FAQ 証拠を隔離保管。追記専用（Append-only）トリガーにより `UPDATE` および `DELETE` を即時 `IntegrityError` でアボート。 |
| **移行 0013 隔離ステージング & フェンシング** | `0013_g07_quarantine_staging.sql` | `tests/qa_chain_0012_0014_probes.py`, `tests/test_antigravity_g7_quarantine_product.py`, `tests/test_m1_0013_0014_g7_g6_tables.py` | 隔離未承認行の正本直接挿入をトリガー `canonical_block_unquarantined` で即時アボート。年度解釈不能値の拒絶、承認者認証、単一ライター以外の書込拒絶。 |
| **移行 0014 版系譜 & 永続照合** | `0014_g06_source_series.sql`, `src/versioning/series.py` | `tests/qa_chain_0012_0014_probes.py`, `tests/test_antigravity_g6_revision_series.py`, `tests/test_m1_0013_0014_g7_g6_tables.py` | 永続保存された行との照合（`verify_series_against_rows`）。版番号の連続性、`supersedes` 参照、重複過剰フレーズ抑止、外部 DB 接続時のハッシュ不一致遮断。 |
| **STR-076 未確認節分離** | `admissions_pipeline/unconfirmed_faq.py` | `tests/behaviour_g2_unconfirmed.py` | 適用年度・学類が未確認の FAQ を正式要項と混在させず、独立した節に分離して文毎出典を強制付与。 |
| **Pi ローカル状態分離** | `pi/sogh_state/state_api.py`, `pi/provision/kiosk.sh` | `pi/tests/test_state_api.py` | 127.0.0.1 ループバック限定バインド、全ルートでの書込メソッド（POST/PUT/DELETE）405 拒絶、未観測デバイス（`NOT_OBSERVED`）の正常偽装防止。 |

---

## 3. 実機検証対象シナリオの選定状況

30 シナリオのうち：
- **既存のテストでカバーされているシナリオ（12 件）**: `SC01, SC02, SC03, SC04, SC05, SC06, SC07, SC09, SC10, SC11, SC12, SC29`
- **現行実装のギャップ（既存テストなし）として明記するシナリオ（1 件）**: `SC08`（エポック・フェンシング未配備）
- **現在は試せない保留シナリオ（17 件）**: `SC13〜SC28, SC30`（物理センサー、外部クローラー、公開CDN、未統合のPIIマスキング `SC21` 等。第5節で詳述）

---

## 4. 詳細対応表（シナリオ ID → 既存コード・実在試験名）

すべての `ファイル::試験名` は master 上の実在が確認されています。

| シナリオ ID | シナリオ名 | 既存防御部品 | 対象コード | 既存テスト（実在確認済み `ファイル::試験名`） | 試験実行方法（合成データの流し込み方） | 期待される判定・例外 |
|:---:|---|---|---|---|---|---|
| **SC01** | 初版と改訂版の日程差分解決 | 移行 0014 & `series.py` | `src/versioning/series.py` | `tests/test_versioning.py::test_new_edition_under_a_new_url_is_matched_through_supersedes`<br>`tests/test_antigravity_g6_revision_series.py::test_series_creation_and_append_lineage` | `AMU-G01`（消印有効）を先行登録後、`supersedes: AMU-G01` を持つ `AMU-G02`（必着）を投入 | `ACCEPT`<br>旧版日程が無効化され、新版（9/10必着）が昇格 |
| **SC02** | 募集定員改訂の単調追跡 | 移行 0014 | `src/versioning/series.py`<br>`src/db_contract/additive_schema.py` | `tests/test_m1_0013_0014_g7_g6_tables.py::test_g6_a_series_is_persisted_verified_against_its_rows_and_linked_to_an_impact` | 定員 15名の版から定員 18名への版番号連続・SHA 更新をコミット | `ACCEPT`<br>`CAPACITY_AMENDMENT_APPLIED` |
| **SC03** | 厳格な否定条件の識別 | `scope_evidence` (STR-101) | `admissions_pipeline/scope_evidence.py` | `tests/behaviour_g2_scope_evidence.py::test_an_inconsistent_or_unsupported_evidence_is_refused` | `AMU-G01` の「現役専願」制約に対し、既卒生または併願の条件を `check_scope_evidence` に照会 | `REJECT`<br>`ValueError: not proven`（例外発生で安全拒絶） |
| **SC04** | 脚注特例の改訂時無効化 | 移行 0014 & `scope_evidence` | `src/versioning/series.py` | `tests/test_antigravity_g6_revision_series.py::test_redundant_revision_rejection` | 初版脚注※2（消印猶予）の引用を、改訂版（Rev 1.1）に対して要求（廃止された特例の再利用試行） | `ACCEPT`<br>改訂版では特例廃止と判定され、期日猶予が無効化される |
| **SC05** | 本文と FAQ の意図的矛盾検出 | 移行 0012 & STR-076 | `admissions_pipeline/unconfirmed_faq.py`<br>`src/db_contract/additive_schema.py` (0012) | `tests/behaviour_g2_unconfirmed.py::test_an_unconfirmed_record_gets_its_own_section_that_says_so_first_and_cites_every_sentence` | 要項本文（1,200字）と異なる FAQ（1,500〜2,000字）を `unconfirmed_faq` 経由で 0012 テーブルへ登録 | `QUARANTINE`<br>正本に結合されず、`faq_unconfirmed_evidence` に隔離 |
| **SC06** | スコープ外（翌年度）の遮断 | 移行 0013 & `scope_evidence` | `src/db_contract/additive_schema.py` (0013)<br>`admissions_pipeline/scope_evidence.py` | `tests/test_antigravity_g7_quarantine_product.py::test_table_refusal_matrix_ambiguous_multi_year`<br>`tests/behaviour_g2_scope_evidence.py::test_an_inconsistent_or_unsupported_evidence_is_refused` | 2027年度ターゲット選抜に対し、`fiscal_year=2028` の合成データ（`SIU-G01`）を投入 | `REJECT`<br>`ValueError: consistent`（年度不一致として拒絶） |
| **SC07** | 未認可ノードの正本書き込み拒否 | 移行 0013 & 権限分離 | `src/db_contract/additive_schema.py` (0013) | `tests/test_m1_0013_0014_g7_g6_tables.py::test_g7_a_connection_that_did_not_register_the_function_cannot_approve_or_promote_and_nothing_is_replaced` | 認証関数を未登録の接続、または監視ノードからの直接書込・承認試行 | `REJECT` / `ABORT`<br>認証失敗または承認拒否 |
| **SC08** | 失効エポック遮断 | Fencing Token Gate | `src/db_contract/additive_schema.py` | **既存の試験なし（NO EXISTING TEST: エポック・フェンシングは未実装）** | 現在エポック（epoch 2）に対し、旧エポック（epoch 1）のトークンでコミット試行（※機能未実装のため試験なし） | 設計上は `REJECT` を想定 |
| **SC09** | 隔離未承認データの正本直接挿入 | 移行 0013 トリガー | `0013_g07_quarantine_staging.sql` | `tests/test_antigravity_g7_quarantine_product.py::test_guard_block_unquarantined_canonical_insert`<br>`tests/qa_chain_0012_0014_probes.py::test_probe_12_canonical_staging_bypass_without_quarantine_blocked` | 未承認（`staged_status != 'PROMOTED'`）の行を正規の事実テーブルに直接 `INSERT` | `ABORT`<br>`IntegrityError: canonical_block_unquarantined` |
| **SC10** | 昇格承認済みデータの単調コミット | 移行 0014 | `0014_g06_source_series.sql`<br>`src/versioning/series.py` | `tests/test_m1_0013_0014_g7_g6_tables.py::test_g6_the_guards_refuse_replace_delete_update_a_wrong_hash_and_a_skipped_revision` | 正当な署名・承認を経て単調増加する版番号（Rev 1.1）を正規コミット | `ACCEPT`<br>正常完了・SHA 系譜記録 |
| **SC11** | 追記専用表への更新・削除遮断 | 移行 0012 & 0014 トリガー | `0012_g02_faq_unconfirmed_evidence.sql`<br>`0014_g06_source_series.sql` | `tests/qa_chain_0012_0014_probes.py::test_probe_01_recursive_triggers_off_cannot_bypass_0012_immutability`<br>`tests/qa_chain_0012_0014_probes.py::test_probe_03_insert_or_replace_on_0014_series_editions_is_blocked` | 0012 および 0014 の管理表に対して `UPDATE` または `DELETE` を実行 | `ABORT`<br>`IntegrityError: ... is append-only` |
| **SC12** | 外部 DB 接続経由の不正注入遮断 | 移行 0014 ハッシュガード | `0014_g06_source_series.sql` | `tests/qa_chain_0012_0014_probes.py::test_probe_08_attached_database_insert_still_enforces_triggers` | `ATTACH DATABASE` で接続した外部 DB から、改ざんされたハッシュを持つ偽行を挿入試行 | `ABORT`<br>`IntegrityError: hash mismatch on attach` |
| **SC29** | コンソール UI 操作の権限非伝播 | Pi 状態 API ルート分離 | `pi/sogh_state/state_api.py` | `pi/tests/test_state_api.py::test_unknown_path_and_write_methods`<br>`pi/tests/test_state_api.py::test_index_page_does_not_accept_writes` | Pi コンソール / 状態 API（127.0.0.1:8765）の全エンドポイントへ `POST` / `PUT` / `DELETE` リクエストを発行 | `REJECT`<br>`HTTP 405 Method Not Allowed`（正本書込能力の非保持） |

---

## 5. 残る 17 シナリオが「現在は試せない（NOT_RUN）」である理由

以下の 17 シナリオは、ハードウェア実機環境の整備、外部通信環境の段階的認可、または未統合モジュールの実装を待つ必要があるため、本計画ではスコープ外（現在は試せない）として明記します：

1. **実ハードウェア・物理センサー依存（SC26: 熱超過, SC27: メモリ枯渇, SC28: 予算・工数上限）**:
   - 理由: 真正温度センサー（lm-sensors / thermal-zone）の実機接続・測定認可、またはホスト側監視デーモンが必要（現在はシミュレーションのみ可能）。
2. **外部ネットワーク・クローラー依存（SC16: URL移転, SC19: robots.txt, SC20: 429バックオフ, SC23: 短命トークン）**:
   - 理由: 外部大学サイトへの実通信は G02 規約および STR-097 で禁止されており、完全閉域モック環境の構築が前提。
3. **公開配信・API ゲート依存（SC13: 高リスク公開保留, SC14: 原子的キャッシュ置換, SC15: 撤回即時差し止め, SC17: 未検証漏洩防止, SC18: 訂正ログ）**:
   - 理由: 公開配信用のキャッシュ層（Cloudflare / CDN）および外部公開 API は現在未稼働（Local-first 段階）。
4. **未統合セキュリティモジュール（SC21: PII マスキング, SC22: 著作権最小引用, SC24: 削除請求と監査調停）**:
   - 理由: PII 検出器や削除要求調停ロジックはリポジトリの master に未配備（構想・下書き段階）。
5. **電源物理断・非常停止連携（SC25: 電源断からの Idempotent 再開, SC30: 多段非常停止）**:
   - 理由: 端末プロセス強制終了テストおよび実機間 STOP シグナルハンドラーの配備が必要。

---

## 6. 実在性検証スクリプトの出力

`scripts/verify_scenario_mapping.py` により、上記対応表に記載された全テストファイルおよびテスト関数名が master 上に存在することが機械的に検証されています（検証結果は本 PR コメントおよび Issue #199 に添付）。
